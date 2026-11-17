"""A filter too long for one protocol line is split, never truncated.

Reported from hardware: a focus run with 19 suite patterns produced a 330-byte
``ETST:ARGS --ts ...`` line. The device reads at most ``MAX_LINE_LEN`` (256)
bytes per line, so it saw a truncated line, failed its CRC
(``CRC fail (284 bytes)``) and answered ``ETST:NAK reason=crc``. The host
resent the same over-long line five times and ended the run ERRORED with zero
cases, about seven minutes after it could have known.

The host already detected the problem before sending a byte and only printed a
warning. These tests pin the two things that must be true instead: a long
filter is split at pattern boundaries so every line fits, and a payload that
cannot be split fails immediately rather than being sent in hope.

Splitting is only safe because the device coalesces repeated filter flags
(``include/etst/doctest/filter_flags.h``). doctest itself takes the LAST
``--ts`` and discards the rest, so an uncoalesced split would silently narrow
the run.
"""

import pytest

from etst.runner import split_args_payload, ArgsLineTooLong
from etst.protocol import format_crc


# The exact filter from the field report: 18 patterns, which frames to a
# 334-byte line against a 256-byte limit.
FIELD_SUITES = (
    "*IMU*Subsystem*Factory*,NullIMUSubsystem,*IMU*Guard*Elimination*,"
    "BoardDetection*,BoardSleepPorts,SleepBasic,SleepDevice,I2cSleepState,"
    "PowerSubsystem,BatteryMonitorService,CalibratedVoltageReading,"
    "NotecardVoltageSource,*USB*PHY*,*USB*wake*cycles*,GpsPowerLifecycle,"
    "RfidReadState,OrientationAwake,*Live*mode*ATTN*pin*"
)
BUDGET = 256


def _framed_len(payload):
    """Length of the wire line the device will read, including its newline."""
    return len(format_crc(f"ETST:ARGS {payload}")) + 1


def test_a_payload_that_already_fits_is_returned_unchanged():
    assert split_args_payload("--env BENCH_POSE=right_side", BUDGET) == [
        "--env BENCH_POSE=right_side"
    ]


def test_the_field_filter_is_split_into_lines_that_each_fit():
    # Guard the fixture: if this ever fits on its own, the test below stops
    # exercising the split and silently proves nothing.
    assert _framed_len(f"--ts {FIELD_SUITES}") > BUDGET

    parts = split_args_payload(f"--ts {FIELD_SUITES}", BUDGET)
    assert len(parts) > 1, "a 330-byte payload must be split"
    for payload in parts:
        assert _framed_len(payload) <= BUDGET, (
            f"{_framed_len(payload)} bytes still exceeds {BUDGET}: {payload}"
        )


def test_splitting_preserves_every_pattern_in_order():
    parts = split_args_payload(f"--ts {FIELD_SUITES}", BUDGET)
    recovered = []
    for payload in parts:
        flag, _, values = payload.partition(" ")
        assert flag == "--ts"
        recovered.extend(values.split(","))
    assert recovered == FIELD_SUITES.split(",")
    assert len(recovered) == 18


def test_a_payload_with_no_split_points_fails_immediately():
    # A single --env value longer than a line can never be split.
    with pytest.raises(ArgsLineTooLong) as excinfo:
        split_args_payload("--env HUGE=" + ("x" * 400), BUDGET)
    message = str(excinfo.value)
    assert "256" in message, message


def test_one_pattern_longer_than_a_line_fails_rather_than_truncating():
    with pytest.raises(ArgsLineTooLong):
        split_args_payload("--ts " + ("a" * 400) + ",short", BUDGET)


class TestSplittingIsGatedOnDeviceSupport:
    """Never split for a device that cannot put the pieces back together.

    Splitting relies on the device coalescing repeated filter flags. doctest
    keeps only the LAST ``--ts``, so a device without that step would run a
    narrower set than asked for and report success — and the host would have
    turned a loud CRC failure into a silent wrong answer. That is a worse
    trade, so the host only splits for a device that announces it can cope.
    """

    def test_a_device_without_coalescing_is_not_sent_a_split_filter(self):
        from etst.runner import split_args_payload_for_device

        with pytest.raises(ArgsLineTooLong) as excinfo:
            split_args_payload_for_device(
                f"--ts {FIELD_SUITES}", BUDGET, device_proto=2
            )
        message = str(excinfo.value)
        assert "proto" in message.lower() or "device" in message.lower(), message

    def test_a_device_with_coalescing_gets_the_split(self):
        from etst.runner import split_args_payload_for_device

        parts = split_args_payload_for_device(
            f"--ts {FIELD_SUITES}", BUDGET, device_proto=3
        )
        assert len(parts) > 1
        for payload in parts:
            assert _framed_len(payload) <= BUDGET

    def test_a_payload_that_fits_is_unaffected_by_device_version(self):
        from etst.runner import split_args_payload_for_device

        for proto in (1, 2, 3):
            assert split_args_payload_for_device(
                "--env A=b", BUDGET, device_proto=proto
            ) == ["--env A=b"]
