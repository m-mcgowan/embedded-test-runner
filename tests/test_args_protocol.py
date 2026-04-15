"""Tests for ETST:ARGS and ETST:ERROR protocol handling."""

from etst.protocol import format_crc, msg_args, msg_error, msg_warn
from etst.ready_run_protocol import ProtocolState, ReadyRunProtocol


class TestArgsAccumulation:
    """ETST:ARGS lines accumulate while in READY state."""

    def test_args_not_parsed_before_ready(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:ARGS --env FOO=bar"))
        assert p.accumulated_args == []

    def test_args_accumulated_in_ready_state(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        assert p.state == ProtocolState.READY
        p.feed(format_crc("ETST:ARGS --env FOO=bar"))
        p.feed(format_crc("ETST:ARGS --tc *GPS*"))
        assert p.accumulated_args == ["--env FOO=bar", "--tc *GPS*"]

    def test_args_cleared_on_ready(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        p.feed(format_crc("ETST:ARGS --env FOO=bar"))
        p.reset()
        p.feed(format_crc("ETST:READY"))
        assert p.accumulated_args == []

    def test_args_frozen_after_command_sent(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        p.feed(format_crc("ETST:ARGS --env FOO=bar"))
        p.command_sent()
        assert p.state == ProtocolState.RUNNING
        # ARGS in RUNNING state should be ignored (not READY anymore)
        p.feed(format_crc("ETST:ARGS --env LATE=true"))
        assert len(p.accumulated_args) == 1

    def test_arg_synonym_accumulated(self):
        """ETST:ARG is accepted as a synonym for ETST:ARGS."""
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        p.feed(format_crc("ETST:ARG --env FOO=bar"))
        p.feed(format_crc("ETST:ARGS --tc *GPS*"))
        assert p.accumulated_args == ["--env FOO=bar", "--tc *GPS*"]


class TestErrorHandling:
    def test_error_during_running(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        p.command_sent()
        p.feed(msg_error("config", "malformed --env arg"))
        assert p.state == ProtocolState.ERROR
        assert p.error_code == "config"
        assert "malformed" in p.error_message

    def test_error_during_ready(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        p.feed(msg_error("hardware", "GPS init failed"))
        assert p.state == ProtocolState.ERROR


class TestWarnHandling:
    def test_warn_during_running(self):
        p = ReadyRunProtocol()
        p.feed(format_crc("ETST:READY"))
        p.command_sent()
        p.feed(msg_warn("something unusual"))
        assert p.state == ProtocolState.RUNNING
