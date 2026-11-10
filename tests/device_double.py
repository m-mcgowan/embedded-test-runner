"""A serial-port double that answers like a device running the doctest runner.

The host's command delivery can only be judged against a device that reacts to
what the host writes: a scripted stream cannot resend, deduplicate or lose a
line. ``DeviceDouble`` models the device's receive loop (``wait_for_command()``
in ``include/etst/doctest/runner.h``) closely enough for that, in two flavours:

- ``proto=1`` is the receive loop as released up to v0.3.4: a line that fails
  its CRC clears the accumulated ``ETST:ARGS`` and re-announces ``ETST:READY``
  at once, and every CRC-valid non-ARGS line is a command to run.
- ``proto=2`` is the transaction protocol: ``ETST:READY proto=2``,
  ``ETST:BEGIN``/``ETST:CMD`` framing, ``ETST:ACK``/``ETST:NAK`` replies and
  duplicate suppression by transaction id. The C++ receiver has its own native
  tests (``tests/test_doctest_internals.cpp``); this is only the host's
  counterpart in the conversation.

Everything the device ran is recorded in ``executions`` as
``(command, [args...])``, so a test can assert "ran exactly once, with every
argument".
"""

from __future__ import annotations

import time

from etst.protocol import compute_crc8, format_crc

READY_INTERVAL_S = 1.0

# Commands idle_loop() acts on directly rather than running tests.
IDLE_COMMANDS = ("SLEEP", "LIGHTSLEEP", "RESTART", "WAIT")


def _check_crc(line: bytes) -> str | None:
    """Return the content of a CRC-valid ``CONTENT *XX`` line, else None."""
    if len(line) < 5 or line[-4:-2] != b" *":
        return None
    try:
        received = int(line[-2:].decode("ascii"), 16)
        content = line[:-4].decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return None
    return content if compute_crc8(content) == received else None


class DeviceDouble:
    """Fake serial port backed by a model of the device's command receiver."""

    def __init__(self, proto: int = 1, cases: tuple[str, ...] = ("t1",)):
        self.proto = proto
        self.cases = cases
        self.rx = bytearray()           # bytes waiting on the device's input
        self._out: list[bytes] = []     # lines the device has printed, unread
        self.printed: list[str] = []    # every line the device printed
        self.executions: list[tuple[str, list[str]]] = []
        self.idle_commands: list[str] = []  # SLEEP/RESTART/... the device acted on
        self.is_open = True
        self.mute_on_accept_s = 0.0     # proto 2: hold all output after a CMD
        self._muted_until = 0.0
        self._args: list[str] = []
        self._txn: tuple[str, int] | None = None
        self._last_id = ""
        self._next_ready = 0.0
        self._written: list[bytes] = []
        self._corrupt_next: bytes | None = None

    # ------------------------------------------------------------------
    # Fault injection
    # ------------------------------------------------------------------

    def inject(self, junk: bytes) -> None:
        """Put bytes on the device's input as if a third party wrote them."""
        self.rx += junk

    def corrupt_next_line_starting(self, prefix: bytes) -> None:
        """Garble the next host line that starts with @p prefix, in transit."""
        self._corrupt_next = prefix

    # ------------------------------------------------------------------
    # pyserial surface used by the runner
    # ------------------------------------------------------------------

    def write(self, data: bytes) -> None:
        self._written.append(data)
        if self._corrupt_next and data.startswith(self._corrupt_next):
            data = data[:-6] + b"#" + data[-5:]   # one byte hit: CRC fails
            self._corrupt_next = None
        self.rx += data

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False

    def reset_input_buffer(self) -> None:
        self._out.clear()

    @property
    def in_waiting(self) -> int:
        self._step()
        if time.monotonic() < self._muted_until:
            return 0
        return len(self._out[0]) if self._out else 0

    def read(self, size: int = 1) -> bytes:
        self._step()
        if not self._out or time.monotonic() < self._muted_until:
            time.sleep(0.01)
            return b""
        return self._out.pop(0)

    @property
    def written_strings(self) -> list[str]:
        return [d.decode(errors="replace") for d in self._written]

    def run_until_idle(self) -> None:
        """Let the device consume whatever is still on its input."""
        self._step()

    # ------------------------------------------------------------------
    # Device model
    # ------------------------------------------------------------------

    def _print(self, line: str) -> None:
        self.printed.append(line)
        self._out.append((line + "\n").encode())

    def _emit(self, content: str) -> None:
        self._print(format_crc(content))

    def _ready(self) -> None:
        if self.proto == 1 or self._txn is None:
            self._args.clear()
        self._emit("ETST:READY" if self.proto == 1 else f"ETST:READY proto={self.proto}")
        self._next_ready = time.monotonic() + READY_INTERVAL_S

    def _step(self) -> None:
        # One line per pass, READY check first: the order of the firmware's
        # loop, so a forced READY goes out before the next line is read.
        while True:
            if time.monotonic() >= self._next_ready:
                self._ready()
            if b"\n" not in self.rx:
                return
            idx = self.rx.index(b"\n")
            raw = bytes(self.rx[:idx]).strip()
            del self.rx[: idx + 1]
            if raw:
                self._line(raw)

    def _line(self, raw: bytes) -> None:
        # Leading noise that cannot start a command is dropped, as the
        # firmware does (commands start with an uppercase ASCII letter).
        start = 0
        while start < len(raw) and not (0x41 <= raw[start] <= 0x5A):
            start += 1
        if 0 < start < len(raw):
            raw = raw[start:]
        content = _check_crc(raw)
        noise = 0
        if content is None and self.proto >= 2:
            pos = raw.find(b"ETST:")
            if pos > 0:
                content = _check_crc(raw[pos:])
                noise = pos if content is not None else 0
        if content is None:
            hexed = " ".join(f"{b:02X}" for b in raw[:22])
            self._print(f"[ETST] CRC fail ({len(raw)} bytes): {hexed} ")
            self._args.clear()
            self._txn = None
            if self.proto == 1:
                self._next_ready = 0.0      # v0.3.x: re-announce READY at once
            else:
                self._emit("ETST:NAK reason=crc")
            return
        if noise:
            self._print(f"[ETST] discarded {noise} bytes of noise before a command line")
        if content.startswith("ETST:ARGS ") or content.startswith("ETST:ARG "):
            self._args.append(content.split(" ", 1)[1].strip())
            return
        if self.proto >= 2 and content.startswith("ETST:BEGIN "):
            fields = dict(t.split("=", 1) for t in content.split()[1:])
            self._txn = (fields["id"], int(fields["args"]))
            self._args.clear()
            return
        if self.proto >= 2 and content.startswith("ETST:CMD "):
            _, id_field, command = content.split(" ", 2)
            txn_id = id_field.split("=", 1)[1]
            if txn_id == self._last_id:
                self._emit(f"ETST:ACK id={txn_id} dup=1")
            elif self._txn != (txn_id, len(self._args)):
                want = self._txn[1] if self._txn and self._txn[0] == txn_id else 0
                self._emit(f"ETST:NAK reason=incomplete id={txn_id} got={len(self._args)} want={want}")
            else:
                self._last_id = txn_id
                if self.mute_on_accept_s:
                    self._muted_until = time.monotonic() + self.mute_on_accept_s
                    self.mute_on_accept_s = 0.0
                self._emit(f"ETST:ACK id={txn_id}")
                self._run(command)
            self._args.clear()
            self._txn = None
            return
        self._run(content)

    def _run(self, command: str) -> None:
        if command in IDLE_COMMANDS:
            # idle_loop() acts on these itself: no test cycle, no DONE.
            self.idle_commands.append(command)
            self._args.clear()
            self._txn = None
            if command == "WAIT":
                self._ready()
            return
        self.executions.append((command, list(self._args)))
        self._args.clear()
        self._txn = None
        self._emit(f"ETST:COUNTS total={len(self.cases)} skip=0 run={len(self.cases)}")
        for name in self.cases:
            self._emit(f'ETST:CASE:START suite="S" name="{name}"')
        self._print("[doctest] test cases: 1 | 1 passed | 0 failed")
        self._emit("ETST:DONE")
        # Back in wait_for_command(): it announces READY first thing.
        self._ready()


def hub_probe_frame() -> bytes:
    """The ESP32 ROM-bootloader SYNC frame a USB hub agent writes to a new port.

    SLIP-framed: ``C0``, an 8-byte request header (direction 0, command 0x08,
    length 36, checksum 0), the payload ``07 07 12 20`` + 32 x ``55``, ``C0``.
    No newline: on a running device it sits in the receive buffer and is
    glued to the front of the host's next line.
    """
    payload = b"\x07\x07\x12\x20" + 32 * b"\x55"
    header = bytes([0x00, 0x08, len(payload), 0x00, 0, 0, 0, 0])
    return b"\xc0" + header + payload + b"\xc0"
