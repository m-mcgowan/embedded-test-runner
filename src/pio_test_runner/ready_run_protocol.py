"""READY/RUN/DONE bidirectional test orchestration protocol.

Parses protocol sentinels from device serial output. The protocol
supports test filtering and deep sleep orchestration:

1. Device boots, prints ``READY``
2. Host sends ``RUN_ALL`` or ``RUN: <filter>``
3. Device runs tests, may print ``SLEEP: <ms>`` for deep sleep
4. Device prints ``DONE`` when finished

The handler is a pure receiver — it parses state but does not send.
The test runner reads its state to decide when to send commands.
"""

import enum
import logging
import re

logger = logging.getLogger(__name__)


class ProtocolState(enum.Enum):
    """Protocol state machine states."""

    WAITING_FOR_READY = enum.auto()
    READY = enum.auto()
    RUNNING = enum.auto()
    SLEEPING = enum.auto()
    FINISHED = enum.auto()


_SLEEP_RE = re.compile(r"SLEEP:\s*(\d+)")
_TEST_START_RE = re.compile(r">>> TEST START(?:\s*\[.*?\])?:\s*(.+)/(.+)")


class ReadyRunProtocol:
    """Parses READY/RUN/DONE/SLEEP protocol from device output.

    State transitions::

        WAITING_FOR_READY → READY (on "READY" line)
        READY → RUNNING (on ``command_sent()`` call)
        RUNNING → SLEEPING (on "SLEEP: <ms>" line)
        RUNNING → FINISHED (on "DONE" line)
        SLEEPING → WAITING_FOR_READY (on ``reset_for_wake()``)
    """

    def __init__(self) -> None:
        self._state = ProtocolState.WAITING_FOR_READY
        self._sleep_duration_ms: int = 0
        self._current_test_suite: str = ""
        self._current_test_name: str = ""
        self._sleeping_test_name: str = ""

    def feed(self, message: bytes | str) -> None:
        """Feed a line of device output."""
        line = (
            message.decode("utf-8", errors="replace")
            if isinstance(message, bytes)
            else message
        )
        line_stripped = line.strip()

        if self._state == ProtocolState.WAITING_FOR_READY:
            if line_stripped == "READY":
                self._state = ProtocolState.READY
                logger.info("Device ready")
            return

        if self._state != ProtocolState.RUNNING:
            return

        # Track test names for sleep attribution
        match = _TEST_START_RE.search(line)
        if match:
            self._current_test_suite = match.group(1)
            self._current_test_name = match.group(2)

        # Check for sleep sentinel
        match = _SLEEP_RE.search(line_stripped)
        if match:
            self._sleep_duration_ms = int(match.group(1))
            self._sleeping_test_name = self._current_test_name
            self._state = ProtocolState.SLEEPING
            logger.info(
                "Sleep requested: %dms (test: %s)",
                self._sleep_duration_ms,
                self._sleeping_test_name,
            )
            return

        # Check for completion
        if line_stripped == "DONE":
            self._state = ProtocolState.FINISHED
            logger.info("Device reported DONE")

    def command_sent(self) -> None:
        """Signal that the host has sent a RUN command.

        Transitions from READY to RUNNING.
        """
        if self._state == ProtocolState.READY:
            self._state = ProtocolState.RUNNING

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
        """Current test suite name from >>> TEST START markers."""
        return self._current_test_suite

    @property
    def current_test_name(self) -> str:
        """Current test name from >>> TEST START markers."""
        return self._current_test_name

    @property
    def current_test_full(self) -> str:
        """Full test identifier (suite/name)."""
        if self._current_test_suite and self._current_test_name:
            return f"{self._current_test_suite}/{self._current_test_name}"
        return ""

    def reset(self) -> None:
        """Reset all state."""
        self._state = ProtocolState.WAITING_FOR_READY
        self._sleep_duration_ms = 0
        self._current_test_suite = ""
        self._current_test_name = ""
        self._sleeping_test_name = ""
