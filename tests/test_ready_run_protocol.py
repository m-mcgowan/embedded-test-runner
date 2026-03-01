"""Tests for ReadyRunProtocol."""

from pio_test_runner.ready_run_protocol import ProtocolState, ReadyRunProtocol


class TestReadyRunProtocol:
    def test_initial_state(self):
        p = ReadyRunProtocol()
        assert p.state == ProtocolState.WAITING_FOR_READY

    def test_ready_transition(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        assert p.state == ProtocolState.READY

    def test_ready_ignores_non_ready_lines(self):
        p = ReadyRunProtocol()
        p.feed("Board revision: 2")
        p.feed("some boot message")
        assert p.state == ProtocolState.WAITING_FOR_READY

    def test_ready_with_whitespace(self):
        p = ReadyRunProtocol()
        p.feed("  READY  \n")
        assert p.state == ProtocolState.READY

    def test_command_sent_transitions_to_running(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        assert p.state == ProtocolState.RUNNING

    def test_done_transitions_to_finished(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed("DONE")
        assert p.state == ProtocolState.FINISHED

    def test_sleep_transitions_to_sleeping(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed("SLEEP: 15000")
        assert p.state == ProtocolState.SLEEPING
        assert p.sleep_duration_ms == 15000

    def test_sleep_no_space(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed("SLEEP:5000")
        assert p.state == ProtocolState.SLEEPING
        assert p.sleep_duration_ms == 5000

    def test_sleeping_test_name_tracked(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed(">>> TEST START: OrientationSleep/Orientation alert across sleep")
        p.feed("SLEEP: 15000")
        assert p.sleeping_test_name == "Orientation alert across sleep"

    def test_test_start_tracking(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed(">>> TEST START: GPS/Navigation rate test")
        assert p.current_test_suite == "GPS"
        assert p.current_test_name == "Navigation rate test"
        assert p.current_test_full == "GPS/Navigation rate test"

    def test_test_start_with_timeout(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed(">>> TEST START [timeout=30s]: GPS/Navigation rate test")
        assert p.current_test_suite == "GPS"
        assert p.current_test_name == "Navigation rate test"

    def test_reset_for_wake(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed("SLEEP: 15000")
        assert p.state == ProtocolState.SLEEPING
        p.reset_for_wake()
        assert p.state == ProtocolState.WAITING_FOR_READY

    def test_full_sleep_wake_cycle(self):
        p = ReadyRunProtocol()
        # Cold boot
        p.feed("READY")
        p.command_sent()
        p.feed(">>> TEST START: Suite/sleep test")
        p.feed("SLEEP: 5000")
        assert p.state == ProtocolState.SLEEPING

        # Wake cycle
        p.reset_for_wake()
        p.feed("READY")
        assert p.state == ProtocolState.READY
        p.command_sent()
        p.feed("DONE")
        assert p.state == ProtocolState.FINISHED

    def test_lines_ignored_when_not_running(self):
        p = ReadyRunProtocol()
        p.feed("DONE")  # Should be ignored in WAITING_FOR_READY
        assert p.state == ProtocolState.WAITING_FOR_READY
        p.feed("SLEEP: 1000")  # Ignored too
        assert p.state == ProtocolState.WAITING_FOR_READY

    def test_bytes_input(self):
        p = ReadyRunProtocol()
        p.feed(b"READY")
        assert p.state == ProtocolState.READY

    def test_reset_clears_all(self):
        p = ReadyRunProtocol()
        p.feed("READY")
        p.command_sent()
        p.feed(">>> TEST START: Suite/test")
        p.feed("SLEEP: 5000")
        p.reset()
        assert p.state == ProtocolState.WAITING_FOR_READY
        assert p.sleep_duration_ms == 0
        assert p.current_test_full == ""
        assert p.sleeping_test_name == ""

    def test_current_test_full_empty_before_any_test(self):
        p = ReadyRunProtocol()
        assert p.current_test_full == ""
