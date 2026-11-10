"""A command from the host is acted on exactly once, with all of its arguments.

Seen on ESP32-S3 hardware after every deep-sleep wake: a USB hub agent probed
the re-enumerated port with an ESP32 ROM-bootloader SYNC frame (no newline).
The frame sat in the device's receive buffer and was glued to the front of the
host's first ``ETST:ARGS`` line, so the device logged
``CRC fail (69 bytes): 55 55 55 ...``, dropped that argument, re-announced
``ETST:READY`` and ran the command anyway on the rest of the arguments. The
host took the second READY to mean "command lost" and sent everything again,
and the device ran the same post-wake case a second time, which failed.

These tests drive the real runner against ``DeviceDouble``.
"""

import threading

from device_double import DeviceDouble, hub_probe_frame
from pio_mocks import MockProjectConfig, MockTestRunnerOptions, MockTestSuite

from etst.protocol import format_crc
from etst.runner import EmbeddedTestRunner

ARGS = ["--env BENCH_MAG_UT=250", "--env BENCH_POSE=right_side", "--env BENCH_RFID=none"]
WAKE_CMD = 'RUN: --wake --tc "a post-wake phase that must run exactly once"'


def _runner_on(device):
    runner = EmbeddedTestRunner(MockTestSuite(), MockProjectConfig(), MockTestRunnerOptions())
    runner._args_lines = list(ARGS)
    runner._ser = device
    runner._open_serial = lambda reset=True: None
    runner._close_serial = lambda: None
    return runner


def _run_cycle(runner, command=WAKE_CMD, timeout=15, skip_post_test=True):
    error = []

    def target():
        try:
            runner._run_test_cycle(command=command, reset=False,
                                   skip_post_test=skip_post_test)
        except Exception as exc:  # pragma: no cover - reported below
            error.append(exc)

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), "the cycle never finished"
    assert not error, f"the cycle raised: {error[0]!r}"


class TestDeviceDoubleReproducesTheField:
    def test_probe_glued_to_the_first_args_line_is_the_69_bytes_the_device_logged(self):
        """The double reproduces the field log byte for byte.

        The SYNC frame is 46 bytes; the device strips the 13 leading bytes that
        cannot start a command (C0, the header, 07 07 12 20), which leaves 32 x
        0x55 and the closing C0, then the 36-byte first ARGS line.
        """
        device = DeviceDouble(proto=1)
        device.inject(hub_probe_frame())
        device.write((format_crc(f"ETST:ARGS {ARGS[0]}") + "\n").encode())
        device.run_until_idle()
        fails = [p for p in device.printed if "CRC fail" in p]
        assert fails == [
            "[ETST] CRC fail (69 bytes): " + " ".join(["55"] * 22) + " "
        ]


class TestLegacyDevice:
    """A device on v0.3.x: no ACK, a CRC failure re-announces READY."""

    def test_noise_before_the_configuration_runs_the_command_once_with_every_arg(self):
        device = DeviceDouble(proto=1)
        device.inject(hub_probe_frame())
        runner = _runner_on(device)

        _run_cycle(runner)
        device.run_until_idle()  # the device keeps reading after the host leaves

        assert len(device.executions) == 1, device.executions
        assert device.executions[0] == (WAKE_CMD, ARGS)

    def test_a_command_that_really_was_lost_is_sent_again(self):
        device = DeviceDouble(proto=1)
        device.corrupt_next_line_starting(b"RUN:")
        runner = _runner_on(device)

        _run_cycle(runner)
        device.run_until_idle()

        assert len(device.executions) == 1, device.executions
        assert device.executions[0] == (WAKE_CMD, ARGS)


class TestTransactionDevice:
    """A device that speaks ``proto=2``: BEGIN/CMD framing, ACK/NAK replies."""

    def test_uses_transaction_framing_when_the_device_offers_it(self):
        device = DeviceDouble(proto=2)
        runner = _runner_on(device)

        _run_cycle(runner)

        sent = [s for s in device.written_strings if s.strip()]
        assert sent[0].startswith("ETST:BEGIN id=")
        txn_id = sent[0].split()[1].split("=", 1)[1]
        assert f" args={len(ARGS)} " in sent[0]
        assert sent[-1].startswith(f"ETST:CMD id={txn_id} {WAKE_CMD} *")
        assert device.executions == [(WAKE_CMD, ARGS)]

    def test_noise_before_the_configuration_runs_the_command_once(self):
        device = DeviceDouble(proto=2)
        device.inject(hub_probe_frame())
        runner = _runner_on(device)

        _run_cycle(runner)
        device.run_until_idle()

        assert device.executions == [(WAKE_CMD, ARGS)]

    def test_noise_glued_to_a_line_is_recovered_without_a_resend(self):
        device = DeviceDouble(proto=2)
        runner = _runner_on(device)
        # The probe lands after the host's line terminator, on the BEGIN line.
        real_write = device.write

        def write(data, _first=[True]):
            if data.startswith(b"ETST:BEGIN") and _first[0]:
                _first[0] = False
                device.inject(hub_probe_frame())
            real_write(data)

        device.write = write
        _run_cycle(runner)
        device.run_until_idle()

        assert device.executions == [(WAKE_CMD, ARGS)]
        begins = [s for s in device.written_strings if s.startswith("ETST:BEGIN")]
        assert len(begins) == 1, "a recovered line must not cost a resend"

    def test_a_lost_argument_is_refused_and_the_transaction_resent(self):
        device = DeviceDouble(proto=2)
        device.corrupt_next_line_starting(b"ETST:ARGS --env BENCH_POSE")
        runner = _runner_on(device)

        _run_cycle(runner)
        device.run_until_idle()

        # Never run on two of the three arguments; run once on all three.
        assert device.executions == [(WAKE_CMD, ARGS)]

    def test_a_resend_after_a_late_ack_is_not_run_twice(self):
        device = DeviceDouble(proto=2)
        # The device accepts and runs the command, but nothing it prints
        # reaches the host until the host has given up waiting and resent.
        device.mute_on_accept_s = 0.8
        runner = _runner_on(device)
        runner.protocol.ACK_TIMEOUT_S = 0.3

        _run_cycle(runner)
        device.run_until_idle()

        cmds = [s for s in device.written_strings if s.startswith("ETST:CMD")]
        assert len(cmds) >= 2, "the host should have resent after the ACK timeout"
        assert len({c.split()[1] for c in cmds}) == 1, "a resend keeps its id"
        assert device.executions == [(WAKE_CMD, ARGS)]
        assert any("dup=1" in p for p in device.printed)


class TestEndOfRunCommand:
    """``ETST_ON_DONE`` reaches the device and is acted on once.

    The end-of-run command (SLEEP, LIGHTSLEEP, RESTART, WAIT) used to be
    written without a CRC. Every device checks the CRC on every line, so it
    refused the command: ``ETST_ON_DONE=sleep`` never put a device to sleep.
    """

    def _finish(self, device, monkeypatch, on_done):
        monkeypatch.setenv("ETST_ON_DONE", on_done)
        runner = _runner_on(device)
        runner._args_lines = []
        _run_cycle(runner, command="RUN", skip_post_test=False)
        device.run_until_idle()
        return runner

    def test_a_legacy_device_acts_on_sleep(self, monkeypatch):
        device = DeviceDouble(proto=1)
        self._finish(device, monkeypatch, "sleep")
        assert device.idle_commands == ["SLEEP"]
        assert not any("CRC fail" in p for p in device.printed)

    def test_the_default_wait_is_accepted_too(self, monkeypatch):
        monkeypatch.delenv("PTR_POST_TEST", raising=False)
        device = DeviceDouble(proto=1)
        monkeypatch.delenv("ETST_ON_DONE", raising=False)
        runner = _runner_on(device)
        runner._args_lines = []
        _run_cycle(runner, command="RUN", skip_post_test=False)
        device.run_until_idle()
        assert device.idle_commands == ["WAIT"]

    def test_a_transaction_device_acknowledges_restart(self, monkeypatch):
        device = DeviceDouble(proto=2)
        self._finish(device, monkeypatch, "restart")
        assert device.idle_commands == ["RESTART"]
        cmds = [s for s in device.written_strings if s.startswith("ETST:CMD")]
        assert cmds[-1].split()[2] == "RESTART"
        assert any(p.startswith("ETST:ACK id=" + cmds[-1].split()[1][3:])
                   for p in device.printed)

    def test_an_unacknowledged_end_command_is_resent_but_acted_on_once(self, monkeypatch):
        device = DeviceDouble(proto=2)
        monkeypatch.setenv("ETST_ON_DONE", "lightsleep")
        runner = _runner_on(device)
        runner._args_lines = []
        runner.protocol.ACK_TIMEOUT_S = 0.3
        real_write = device.write

        def write(data):
            # The first copy of the end command reaches the device, but the
            # host hears nothing back until it has resent.
            if data.startswith(b"ETST:CMD") and b"LIGHTSLEEP" in data \
                    and not device.idle_commands:
                device.mute_on_accept_s = 0.8
            real_write(data)

        device.write = write
        _run_cycle(runner, command="RUN", skip_post_test=False)
        device.run_until_idle()
        sent = [s for s in device.written_strings
                if s.startswith("ETST:CMD") and "LIGHTSLEEP" in s]
        assert len(sent) >= 2
        assert device.idle_commands == ["LIGHTSLEEP"]
