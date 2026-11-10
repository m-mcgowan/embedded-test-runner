"""READY/RUN/DONE bidirectional test orchestration protocol.

Parses protocol sentinels from device serial output. The protocol
supports test filtering and deep sleep orchestration:

1. Device boots, prints ``ETST:READY`` (``ETST:READY proto=2`` if it
   acknowledges commands)
2. Host sends ``RUN_ALL``, ``RUN: <filter>``, or ``RESUME_AFTER: <name>``;
   to a protocol-2 device, framed as ``ETST:BEGIN`` / ``ETST:ARGS`` /
   ``ETST:CMD`` with a transaction id
3. A protocol-2 device replies ``ETST:ACK id=<id>`` (or ``ETST:NAK``)
4. Device runs tests, may print ``ETST:SLEEP ms=<N>`` for deep sleep
5. Device prints ``ETST:DONE`` when finished

The handler is a pure receiver — it parses state but does not send.
The test runner reads its state to decide when to send commands, and
calls ``poll()`` so an unacknowledged command is resent. When a resend is
justified is documented in ``docs/design.md`` ("Command delivery").
"""

import enum
import logging
import time

from .protocol import parse_line, parse_payload

logger = logging.getLogger(__name__)


class ProtocolState(enum.Enum):
    """Protocol state machine states."""

    WAITING_FOR_READY = enum.auto()
    READY = enum.auto()
    RUNNING = enum.auto()
    SLEEPING = enum.auto()
    FINISHED = enum.auto()
    ERROR = enum.auto()


class ReadyRunProtocol:
    """Parses ETST:READY/DONE/SLEEP/TEST:START protocol from device output.

    State transitions::

        WAITING_FOR_READY → READY (on "ETST:READY" line)
        READY → RUNNING (on ``command_sent()`` call)
        RUNNING → READY (resend: ``poll()`` for protocol 2, a second
                          unexplained READY for protocol 1)
        RUNNING → SLEEPING (on "ETST:SLEEP" line)
        RUNNING → FINISHED (on "ETST:DONE" line)
        SLEEPING → WAITING_FOR_READY (on ``reset_for_wake()``)
    """

    # Transaction protocol (a device announcing ``ETST:READY proto=2``):
    # resend when the device refused a line and has then been quiet this long
    # without acknowledging (the NAK may be for noise in front of an intact
    # command, whose ACK follows at once) ...
    NAK_QUIET_S = 0.5
    # ... or when nothing at all came back. The device reads its input every
    # 10 ms while it waits, so an ACK normally arrives within milliseconds.
    ACK_TIMEOUT_S = 2.0
    # Resends of one command before the run is failed.
    MAX_RESENDS = 5

    def __init__(self) -> None:
        self._state = ProtocolState.WAITING_FOR_READY
        self._device_proto: int = 1
        self._txn_id: str = ""
        self._sent_at: float = 0.0
        self._resend_at: float = 0.0
        self._resends: int = 0
        self._resend_pending: bool = False
        self._command_taken: bool = False
        self._unexplained_readies: int = 0
        self._sleep_duration_ms: int = 0
        self._current_test_suite: str = ""
        self._current_test_name: str = ""
        self._current_test_timeout: int = 0  # per-test timeout from doctest annotation
        self._sleeping_test_name: str = ""
        self._completed_tests: list[str] = []  # test names seen across all cycles
        self._test_total: int = 0
        self._test_skip: int = 0
        self._test_run: int = 0
        self._expected_run: int = 0
        self._expected_run_latched: bool = False
        self._busy_until: float = 0  # monotonic time when busy period ends
        self._accumulated_args: list[str] = []
        self._error_code: str = ""
        self._error_message: str = ""

    def feed(self, message: bytes | str) -> None:
        """Feed a line of device output."""
        line = (
            message.decode("utf-8", errors="replace")
            if isinstance(message, bytes)
            else message
        )
        line_stripped = line.strip()

        parsed = parse_line(line_stripped)

        if self._state == ProtocolState.WAITING_FOR_READY:
            if parsed and parsed.tag == "READY" and parsed.crc_valid is not False:
                self._state = ProtocolState.READY
                self._accumulated_args.clear()  # Fresh configure phase
                proto = parse_payload(parsed.payload_str).get("proto", "1")
                try:
                    self._device_proto = int(proto) if isinstance(proto, str) else 1
                except ValueError:
                    self._device_proto = 1
                logger.info("Device ready (protocol %d)", self._device_proto)
            return

        # Accumulate ARGS while in READY state (ARG and ARGS are synonyms)
        if self._state == ProtocolState.READY:
            if parsed and parsed.tag in ("ARGS", "ARG") and parsed.crc_valid is not False:
                self._accumulated_args.append(parsed.payload_str)
                return
            if parsed and parsed.tag == "ERROR" and parsed.crc_valid is not False:
                parts = parsed.payload_str.split(None, 1)
                self._error_code = parts[0] if parts else ""
                self._error_message = parts[1].strip('"') if len(parts) > 1 else ""
                self._state = ProtocolState.ERROR
                logger.error("Device error (%s): %s", self._error_code, self._error_message)
                return
            # A resend is pending, but the device has just shown it took the
            # command after all (an ACK, COUNTS, a test starting). Cancel the
            # resend and handle the line as the run it belongs to.
            if (self._resend_pending and parsed and parsed.crc_valid is not False
                    and parsed.tag not in ("READY", "ARGS", "ARG", "NAK")):
                self._state = ProtocolState.RUNNING
                self._resend_pending = False

        if self._state != ProtocolState.RUNNING:
            return

        if not parsed:
            return
        if parsed.crc_valid is False:
            logger.warning("CRC mismatch, ignoring: %s", parsed.raw)
            return

        if parsed.tag == "ACK":
            payload = parse_payload(parsed.payload_str)
            if self._txn_id and payload.get("id") == self._txn_id:
                self._command_taken = True
                self._resend_at = 0.0
                logger.info("Device acknowledged command %s%s", self._txn_id,
                            " (already run)" if payload.get("dup") else "")
            return

        if parsed.tag == "NAK":
            if self._device_proto >= 2 and not self._command_taken:
                # Do not resend yet: the refused line may be noise in front of
                # our transaction, whose ACK is on its way. poll() resends if
                # the device stays quiet.
                self._resend_at = time.monotonic() + self.NAK_QUIET_S
                logger.info("Device refused a line (%s)", parsed.payload_str)
            return

        # A READY while we think we're RUNNING, before any test started.
        if parsed.tag == "READY" and not self._current_test_name:
            self._on_ready_while_running()
            return

        if parsed.tag in ("CASE:START", "COUNTS"):
            self._command_taken = True

        # Track test names for sleep attribution and resume-after
        if parsed.tag == "CASE:START":
            payload = parse_payload(parsed.payload_str)
            suite = payload.get("suite", "")
            name = payload.get("name", "")
            timeout = payload.get("timeout", "")
            if suite and isinstance(suite, str):
                self._current_test_suite = suite
            if name and isinstance(name, str):
                self._current_test_name = name
                full = f"{self._current_test_suite}/{name}" if self._current_test_suite else name
                if full not in self._completed_tests:
                    self._completed_tests.append(full)
            # Per-test timeout from doctest::timeout(N) annotation
            self._current_test_timeout = int(timeout) if timeout else 0

        # Test count report
        elif parsed.tag == "COUNTS":
            payload = parse_payload(parsed.payload_str)
            self._test_total = int(payload.get("total", 0))
            self._test_skip = int(payload.get("skip", 0))
            self._test_run = int(payload.get("run", 0))
            # Latch the first cycle's runnable count as the expected total for
            # the whole session. Later cycles are resumes, whose counts shrink
            # as completed tests are excluded, so only the first is the full
            # picture. Used to detect a session that silently under-runs.
            if not self._expected_run_latched:
                self._expected_run = self._test_run
                self._expected_run_latched = True

        # Check for sleep or restart sentinel
        elif parsed.tag == "SLEEP":
            payload = parse_payload(parsed.payload_str)
            ms_str = payload.get("ms", "0")
            self._sleep_duration_ms = int(ms_str) if isinstance(ms_str, str) else 0
            self._sleeping_test_name = self._current_test_name
            self._state = ProtocolState.SLEEPING
            logger.info(
                "Sleep requested: %dms (test: %s)",
                self._sleep_duration_ms,
                self._sleeping_test_name,
            )

        elif parsed.tag == "BUSY":
            payload = parse_payload(parsed.payload_str)
            ms_str = payload.get("ms", "0")
            self._busy_until = time.monotonic() + int(ms_str) / 1000.0
            logger.info("Device busy for %sms", ms_str)

        elif parsed.tag == "RESTART":
            self._sleep_duration_ms = 0  # No sleep, just restart
            self._sleeping_test_name = self._current_test_name
            self._state = ProtocolState.SLEEPING  # Reuse sleep flow
            logger.info(
                "Restart requested (test: %s)",
                self._sleeping_test_name,
            )

        # Check for completion
        elif parsed.tag == "DONE":
            self._state = ProtocolState.FINISHED
            logger.info("Device reported DONE")

        elif parsed.tag == "ERROR":
            parts = parsed.payload_str.split(None, 1)
            self._error_code = parts[0] if parts else ""
            self._error_message = parts[1].strip('"') if len(parts) > 1 else ""
            self._state = ProtocolState.ERROR
            logger.error("Device error (%s): %s", self._error_code, self._error_message)

        elif parsed.tag == "WARN":
            logger.warning("Device warning: %s", parsed.payload_str)

    def _on_ready_while_running(self) -> None:
        """Decide whether a READY after our command means it was lost.

        It is not proof. A v0.3.x device re-announces READY when a line fails
        its CRC, and that line may be noise in front of an intact command
        (seen on hardware: a USB hub agent's probe frame glued to the first
        ``ETST:ARGS`` line), in which case the device runs the command anyway
        and a resend runs it a second time. So:

        - protocol 2: never. The device acknowledges by id; ``poll()`` resends
          on a NAK or a missing ACK, and the device drops a duplicate id.
        - protocol 1: only on the second READY with no sign the command was
          taken (``ETST:COUNTS``, ``ETST:CASE:START``). A device that took the
          command is busy running it and does not announce READY again; one
          that is still waiting announces it every second.
        """
        if self._device_proto >= 2 or self._command_taken:
            return
        self._unexplained_readies += 1
        if self._unexplained_readies >= 2:
            self._state = ProtocolState.READY
            self._resend_pending = True
            logger.info("Device re-sent READY twice with no sign of the command — "
                        "command was lost, retrying")
        else:
            logger.info("Device re-sent READY — waiting to see whether the "
                        "command was taken")

    def command_sent(self, txn_id: str = "") -> None:
        """Signal that the host has sent a command (or resent it).

        Transitions from READY to RUNNING.

        Args:
            txn_id: The transaction id the command was sent under (protocol
                2). A resend passes the same id.
        """
        if self._state == ProtocolState.READY:
            self._state = ProtocolState.RUNNING
            if txn_id and txn_id == self._txn_id:
                self._resends += 1
            else:
                self._resends = 0
            self._txn_id = txn_id
            self._sent_at = time.monotonic()
            self._resend_at = 0.0
            self._resend_pending = False
            self._command_taken = False
            self._unexplained_readies = 0

    def poll(self, now: float | None = None) -> None:
        """Resend a protocol-2 command the device has not acknowledged.

        Call regularly while the device is silent as well as when it talks.
        Moves RUNNING back to READY (the runner then resends with the same
        id) after a NAK followed by ``NAK_QUIET_S`` of silence, or
        ``ACK_TIMEOUT_S`` with no reply. After ``MAX_RESENDS`` the run fails
        with ``ETST:ERROR``-style state (code ``protocol``).
        """
        if (self._state != ProtocolState.RUNNING or self._device_proto < 2
                or self._command_taken or not self._txn_id):
            return
        now = time.monotonic() if now is None else now
        due = (self._resend_at and now >= self._resend_at) or (
            now - self._sent_at >= self.ACK_TIMEOUT_S)
        if not due:
            return
        if self._resends >= self.MAX_RESENDS:
            self._error_code = "protocol"
            self._error_message = (
                f"device did not acknowledge command {self._txn_id} after "
                f"{self._resends} resends")
            self._state = ProtocolState.ERROR
            logger.error("%s", self._error_message)
            return
        self._state = ProtocolState.READY
        self._resend_pending = True
        logger.info("No acknowledgement for command %s — resending", self._txn_id)

    @property
    def device_proto(self) -> int:
        """Protocol version from the device's last ETST:READY (1 if none given)."""
        return self._device_proto

    @property
    def command_taken(self) -> bool:
        """True once the device acknowledged or started running the command."""
        return self._command_taken

    def reset_for_wake(self) -> None:
        """Reset protocol state for a wake cycle after sleep.

        Transitions from SLEEPING back to WAITING_FOR_READY.
        """
        if self._state == ProtocolState.SLEEPING:
            self._state = ProtocolState.WAITING_FOR_READY

    @property
    def state(self) -> ProtocolState:
        """Current protocol state."""
        return self._state

    @property
    def sleep_duration_ms(self) -> int:
        """Requested sleep duration in milliseconds."""
        return self._sleep_duration_ms

    @property
    def sleeping_test_name(self) -> str:
        """Name of the test that requested sleep."""
        return self._sleeping_test_name

    @property
    def current_test_suite(self) -> str:
        """Current test suite name from ETST:CASE:START markers."""
        return self._current_test_suite

    @property
    def current_test_name(self) -> str:
        """Current test name from ETST:CASE:START markers."""
        return self._current_test_name

    @property
    def current_test_timeout(self) -> int:
        """Per-test timeout in seconds from doctest::timeout(N), or 0 if unset."""
        return self._current_test_timeout

    @property
    def current_test_full(self) -> str:
        """Full test identifier (suite/name)."""
        if self._current_test_suite and self._current_test_name:
            return f"{self._current_test_suite}/{self._current_test_name}"
        return ""

    @property
    def is_busy(self) -> bool:
        """True if device signalled ETST:BUSY and the period hasn't expired."""
        return time.monotonic() < self._busy_until

    @property
    def test_total(self) -> int:
        """Total registered tests reported by device."""
        return self._test_total

    @property
    def test_skip(self) -> int:
        """Tests skipped (by RESUME_AFTER)."""
        return self._test_skip

    @property
    def test_run(self) -> int:
        """Tests to run this cycle."""
        return self._test_run

    @property
    def expected_run(self) -> int:
        """Runnable tests reported by the device's first cycle.

        The number the whole session is expected to execute. 0 if no COUNTS
        was ever received (e.g. a device that never reported).
        """
        return self._expected_run

    @property
    def completed_tests(self) -> list[str]:
        """Test names seen across all cycles (for resume-after exclude)."""
        return list(self._completed_tests)

    @property
    def accumulated_args(self) -> list[str]:
        """Args accumulated from ETST:ARGS lines during READY state."""
        return list(self._accumulated_args)

    @property
    def error_code(self) -> str:
        """Error code from ETST:ERROR (e.g. 'config', 'hardware')."""
        return self._error_code

    @property
    def error_message(self) -> str:
        """Error message from ETST:ERROR."""
        return self._error_message

    def reset(self) -> None:
        """Reset all state for a fresh test cycle.

        Preserves completed_tests across cycles so the runner can build
        an EXCLUDE list for remaining-tests cycles after sleep resume.
        """
        self._state = ProtocolState.WAITING_FOR_READY
        self._sleep_duration_ms = 0
        self._current_test_suite = ""
        self._current_test_name = ""
        self._current_test_timeout = 0
        self._sleeping_test_name = ""
        self._test_total = 0
        self._test_skip = 0
        self._test_run = 0
        self._accumulated_args.clear()
        self._error_code = ""
        self._error_message = ""
        self._device_proto = 1
        self._txn_id = ""
        self._sent_at = 0.0
        self._resend_at = 0.0
        self._resends = 0
        self._resend_pending = False
        self._command_taken = False
        self._unexplained_readies = 0

    def reset_all(self) -> None:
        """Full reset including completed test history."""
        self.reset()
        self._completed_tests.clear()
        # Session-scoped, like completed_tests: survives reset() between
        # cycles (the first cycle's count is the session's expected total)
        # but is cleared for a genuinely fresh session.
        self._expected_run = 0
        self._expected_run_latched = False
