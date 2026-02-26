"""Tests for EmbeddedTestRunner."""

from conftest import (
    MockProjectConfig,
    MockTestRunnerOptions,
    MockTestStatus,
    MockTestSuite,
)

from pio_test_runner.runner import EmbeddedTestRunner


def make_runner(**kwargs):
    """Create a runner with mock PIO objects."""
    suite = kwargs.pop("test_suite", None) or MockTestSuite()
    config = kwargs.pop("project_config", None) or MockProjectConfig()
    options = kwargs.pop("options", None) or MockTestRunnerOptions()
    runner = EmbeddedTestRunner(suite, config, options)
    return runner


class TestCrashHandling:
    def test_crash_adds_errored_case(self):
        runner = make_runner()

        runner.on_testing_line_output("Guru Meditation Error: Core 0 panic\n")
        # Feed enough lines to finalize crash
        for i in range(20):
            runner.on_testing_line_output(f"backtrace line {i}\n")

        assert runner.test_suite._finished
        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
        assert "Crash" in errored[0].message

    def test_crash_finishes_suite(self):
        runner = make_runner()
        runner.on_testing_line_output("Backtrace: 0x400d1234\n")
        for i in range(20):
            runner.on_testing_line_output(f"line {i}\n")
        assert runner.test_suite._finished

    def test_no_crash_does_not_finish(self):
        runner = make_runner()
        runner.on_testing_line_output("Normal output\n")
        assert not runner.test_suite._finished


class TestDisconnectSuppression:
    def test_output_suppressed_during_disconnect(self, capsys):
        runner = make_runner()
        runner.on_testing_line_output("PTR:DISCONNECT:5000\n")
        runner.on_testing_line_output("output during disconnect\n")
        runner.on_testing_line_output("more output\n")

        # These lines should have been suppressed (no echo)
        captured = capsys.readouterr()
        assert "output during disconnect" not in captured.out

    def test_output_resumes_after_reconnect(self, capsys):
        runner = make_runner()
        runner.on_testing_line_output("PTR:DISCONNECT:1000\n")
        runner.on_testing_line_output("suppressed\n")
        runner.on_testing_line_output("PTR:RECONNECT\n")
        runner.on_testing_line_output("visible again\n")

        captured = capsys.readouterr()
        assert "suppressed" not in captured.out
        assert "visible again" in captured.out


class TestResultReporting:
    def test_unity_pass_forwarded(self):
        runner = make_runner()
        runner.on_testing_line_output("test/main.c:10:test_hello:PASS\n")

        passed = [c for c in runner.test_suite.cases if c.status == MockTestStatus.PASSED]
        assert len(passed) == 1
        assert passed[0].name == "test_hello"

    def test_unity_fail_forwarded(self):
        runner = make_runner()
        runner.on_testing_line_output("test/main.c:10:test_math:FAIL: Expected 5 Was 3\n")

        failed = [c for c in runner.test_suite.cases if c.status == MockTestStatus.FAILED]
        assert len(failed) == 1
        assert failed[0].name == "test_math"
        assert "Expected 5 Was 3" in failed[0].message

    def test_completion_finishes_suite(self):
        runner = make_runner()
        runner.on_testing_line_output("test/main.c:10:test_one:PASS\n")
        runner.on_testing_line_output("1 Tests 0 Failures 0 Ignored\n")

        assert runner.test_suite._finished

    def test_doctest_summary_finishes_suite(self):
        runner = make_runner()
        runner.on_testing_line_output("[doctest] test cases:  1 |  1 passed | 0 failed |\n")

        assert runner.test_suite._finished


class TestLifecycle:
    def test_teardown_checks_timeout(self):
        runner = make_runner()
        # Simulate some output, then silence
        runner.crash_detector._last_feed_time = 0.0  # long ago
        runner.crash_detector._silent_timeout = 0.001

        runner.teardown()

        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
        assert "hang" in errored[0].name

    def test_teardown_no_hang_when_runner_finished(self):
        runner = make_runner()
        # Simulate normal completion via result receiver
        runner.on_testing_line_output("[doctest] test cases:  1 |  1 passed | 0 failed |\n")
        assert runner._finished_by_runner

        runner.crash_detector._last_feed_time = 0.0
        runner.crash_detector._silent_timeout = 0.001

        runner.teardown()
        # Should not add a hang case since runner already finished normally
        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 0

    def test_teardown_hang_when_pio_timed_out(self):
        runner = make_runner()
        # Simulate PIO's serial reader timing out — runner never finished
        runner.crash_detector._last_feed_time = 0.0
        runner.crash_detector._silent_timeout = 0.001
        # PIO calls on_finish() before teardown, but our flag is False
        runner.test_suite.on_finish()
        assert not runner._finished_by_runner

        runner.teardown()
        # Should detect the hang since runner didn't explicitly finish
        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
        assert "hang" in errored[0].name


class TestIntegration:
    def test_full_unity_session(self):
        runner = make_runner()

        lines = [
            "Booting...\n",
            "WiFi connected\n",
            "test/main.c:10:test_init:PASS\n",
            "test/main.c:20:test_read:PASS\n",
            "test/main.c:30:test_write:FAIL: timeout\n",
            "-----------------------\n",
            "3 Tests 1 Failures 0 Ignored\n",
        ]

        for line in lines:
            runner.on_testing_line_output(line)

        assert runner.test_suite._finished
        assert len(runner.test_suite.cases) == 3
        passed = [c for c in runner.test_suite.cases if c.status == MockTestStatus.PASSED]
        failed = [c for c in runner.test_suite.cases if c.status == MockTestStatus.FAILED]
        assert len(passed) == 2
        assert len(failed) == 1

    def test_disconnect_mid_test(self):
        runner = make_runner()

        lines = [
            "test/main.c:10:test_init:PASS\n",
            "PTR:DISCONNECT:5000\n",
            "garbage during disconnect\n",
            "PTR:RECONNECT\n",
            "test/main.c:20:test_after_sleep:PASS\n",
            "2 Tests 0 Failures 0 Ignored\n",
        ]

        for line in lines:
            runner.on_testing_line_output(line)

        assert runner.test_suite._finished
        passed = [c for c in runner.test_suite.cases if c.status == MockTestStatus.PASSED]
        assert len(passed) == 2

    def test_crash_during_test(self):
        runner = make_runner()

        runner.on_testing_line_output("test/main.c:10:test_init:PASS\n")
        runner.on_testing_line_output("Guru Meditation Error: Core 0 panic\n")
        for i in range(20):
            runner.on_testing_line_output(f"  0x{i:08x}\n")

        assert runner.test_suite._finished
        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
