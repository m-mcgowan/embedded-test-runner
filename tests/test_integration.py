"""Integration tests for pio-test-runner.

These tests simulate complete test sessions as produced by the C++ firmware
(doctest_runner.h + test_runner.h) and verify that the Python runner correctly
processes the full protocol flow: READY/RUN/DONE handshake, memory tracking,
timing tracking, crash detection, and sleep orchestration.

The output strings match exactly what the C++ headers emit, ensuring the
Python and firmware sides stay in sync.

Note: Most tests use a helper that calls ``protocol.command_sent()`` after
the READY line to simulate the orchestrator advancing the state machine.
In real usage, ``stage_testing()`` does this automatically.
"""

from conftest import (
    MockProjectConfig,
    MockTestRunnerOptions,
    MockTestStatus,
    MockTestSuite,
)

from pio_test_runner.ready_run_protocol import ProtocolState
from pio_test_runner.runner import EmbeddedTestRunner


def make_runner(**kwargs):
    """Create a runner with mock PIO objects."""
    suite = kwargs.pop("test_suite", None) or MockTestSuite()
    config = kwargs.pop("project_config", None) or MockProjectConfig()
    options = kwargs.pop("options", None) or MockTestRunnerOptions()
    return EmbeddedTestRunner(suite, config, options)


def feed_session(runner, lines):
    """Feed lines through the runner, calling command_sent() after READY.

    This simulates what stage_testing() does: when the protocol reaches
    READY, it sends a command and calls command_sent() to transition
    to RUNNING.
    """
    for line in lines:
        runner.on_testing_line_output(line + "\n")
        if runner.protocol.state == ProtocolState.READY:
            runner.protocol.command_sent()


# =====================================================================
# Simulate the exact output the C++ doctest_runner.h produces
# =====================================================================

# A typical doctest session with 2 passing tests and memory tracking
DOCTEST_SESSION_PASS = [
    "Board revision: 2",
    "Test storage initialized: /littlefs/test",
    "READY",
    # (runner sends RUN_ALL here — feed_session calls command_sent)
    "Runner: RUN_ALL (no additional filter)",
    "",
    ">>> TEST START: GPS/Navigation rate test",
    "[MEM] Before: free=200000, min=180000",
    "  CHECK( nav_rate == 5 ) is correct!",
    "[MEM] After: free=199500 (delta=-500), min=179000",
    "",
    ">>> TEST START: GPS/Satellite count",
    "[MEM] Before: free=199500, min=179000",
    "  CHECK( sat_count >= 4 ) is correct!",
    "[MEM] After: free=199000 (delta=-500), min=178500",
    "[doctest] test cases:  2 |  2 passed | 0 failed |",
    "DONE",
]

# Session with a large memory leak
DOCTEST_SESSION_LEAK = [
    "Board revision: 2",
    "READY",
    "Runner: RUN_ALL (no additional filter)",
    "",
    ">>> TEST START: Mem/leaky test",
    "[MEM] Before: free=200000, min=180000",
    "  CHECK( true ) is correct!",
    "[MEM] After: free=185000 (delta=-15000), min=175000",
    "[MEM] WARNING: Test leaked ~15000 bytes!",
    "[doctest] test cases:  1 |  1 passed | 0 failed |",
    "DONE",
]

# Session with a crash mid-test
DOCTEST_SESSION_CRASH = [
    "Board revision: 2",
    "READY",
    "Runner: RUN_ALL (no additional filter)",
    "",
    ">>> TEST START: IMU/FIFO read",
    "[MEM] Before: free=200000, min=180000",
    "Guru Meditation Error: Core  0 panic'ed (StoreProhibited). Exception was unhandled.",
    "Core  0 register dump:",
    "PC      : 0x400d1234  PS      : 0x00060030",
    "Backtrace: 0x400d1234:0x3ffb1234 0x400d5678:0x3ffb5678",
]

# Session where test announces deep sleep
DOCTEST_SESSION_SLEEP = [
    "Board revision: 2",
    "READY",
    "Runner: RUN_ALL (no additional filter)",
    "",
    ">>> TEST START: Orientation/alert across sleep",
    "[MEM] Before: free=200000, min=180000",
    "  CHECK( orientation == PORTRAIT ) is correct!",
    "SLEEP: 15000",
]

# Session with timeout annotation on test
DOCTEST_SESSION_TIMEOUT = [
    "Board revision: 2",
    "READY",
    "Runner: RUN_ALL (no additional filter)",
    "",
    ">>> TEST START [timeout=30s]: GPS/Cold start fix",
    "[MEM] Before: free=200000, min=180000",
    "  CHECK( fix_acquired ) is correct!",
    "[MEM] After: free=199800 (delta=-200), min=179500",
    "[doctest] test cases:  1 |  1 passed | 0 failed |",
    "DONE",
]

# Session with disconnect protocol (PTR:DISCONNECT/RECONNECT)
DOCTEST_SESSION_DISCONNECT = [
    "Board revision: 2",
    "READY",
    "Runner: RUN_ALL (no additional filter)",
    "",
    ">>> TEST START: Sleep/deep sleep wake",
    "[MEM] Before: free=200000, min=180000",
    "PTR:DISCONNECT:5000",
    "garbage during deep sleep",
    "PTR:RECONNECT",
    "  CHECK( woke_correctly ) is correct!",
    "[MEM] After: free=198000 (delta=-2000), min=178000",
    "[doctest] test cases:  1 |  1 passed | 0 failed |",
    "DONE",
]


class TestFullDoctestSession:
    """Simulate full doctest sessions through the line callback path."""

    def test_passing_session_with_memory(self):
        """Two passing tests with memory markers — no leaks reported."""
        runner = make_runner()
        feed_session(runner, DOCTEST_SESSION_PASS)

        assert runner.test_suite._finished
        # Note: doctest summary line finishes the suite before DONE is
        # processed, so protocol stays at RUNNING. This is correct —
        # in orchestrated mode, stage_testing() would see DONE too.
        assert runner.protocol.current_test_full == "GPS/Satellite count"
        assert len(runner.memory_tracker.leaks) == 0

    def test_memory_leak_detected(self):
        """Session with a 15KB leak should be reported."""
        runner = make_runner()
        feed_session(runner, DOCTEST_SESSION_LEAK)

        assert runner.test_suite._finished

        leaks = runner.memory_tracker.leaks
        assert "Mem/leaky test" in leaks
        assert leaks["Mem/leaky test"].delta == -15000

        report = runner.memory_tracker.report()
        assert "leaky test" in report

    def test_crash_detected_and_reported(self):
        """Crash mid-test should add an ERRORED case and finish the suite."""
        runner = make_runner()
        feed_session(runner, DOCTEST_SESSION_CRASH)
        # CrashDetector needs enough post-crash lines to finalize
        for i in range(20):
            runner.on_testing_line_output(f"  register dump line {i}\n")

        assert runner.test_suite._finished

        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
        # The crash case should reference the test that was running
        assert "IMU/FIFO read" in errored[0].name

    def test_sleep_sentinel_sets_sleeping_state(self):
        """SLEEP: sentinel should transition protocol to SLEEPING."""
        runner = make_runner()
        feed_session(runner, DOCTEST_SESSION_SLEEP)

        assert runner.protocol.state == ProtocolState.SLEEPING
        assert runner.protocol.sleep_duration_ms == 15000
        assert runner.protocol.sleeping_test_name == "alert across sleep"

    def test_timeout_annotation_parsed(self):
        """Test start with timeout annotation should still track correctly."""
        runner = make_runner()
        feed_session(runner, DOCTEST_SESSION_TIMEOUT)

        assert runner.test_suite._finished
        assert runner.protocol.current_test_full == "GPS/Cold start fix"

    def test_disconnect_suppresses_output(self, capsys):
        """PTR:DISCONNECT should suppress output until PTR:RECONNECT."""
        runner = make_runner()
        feed_session(runner, DOCTEST_SESSION_DISCONNECT)

        assert runner.test_suite._finished
        captured = capsys.readouterr()
        assert "garbage during deep sleep" not in captured.out


class TestProtocolHandshake:
    """Test the READY/RUN/DONE handshake through the runner."""

    def test_ready_detected_from_boot_output(self):
        """READY line among boot output is correctly detected."""
        runner = make_runner()

        boot_lines = [
            "ESP-ROM:esp32s3-20210327",
            "rst:0x1 (POWERON),boot:0x2b (SPI_FAST_FLASH_BOOT)",
            "Board revision: 2",
            "Test storage initialized: /littlefs/test",
            "READY",
        ]
        for line in boot_lines:
            runner.on_testing_line_output(line + "\n")

        assert runner.protocol.state == ProtocolState.READY

    def test_done_after_run_without_doctest_summary(self):
        """DONE without doctest summary completes the protocol.

        When doctest summary arrives first, it finishes the suite and
        DONE is never fed to the protocol. Test DONE detection by
        omitting the doctest summary line.
        """
        runner = make_runner()

        feed_session(runner, [
            "READY",
            "  CHECK( true ) is correct!",
            "DONE",
        ])

        assert runner.protocol.state == ProtocolState.FINISHED

    def test_boot_output_before_ready_ignored(self):
        """Lines before READY don't affect protocol state."""
        runner = make_runner()

        pre_ready = [
            "ESP-ROM:esp32s3-20210327",
            "configsip: 0, SPIWP:0xee",
            "DONE",  # stale DONE from previous run — should be ignored
            "SLEEP: 5000",  # stale — should be ignored
        ]
        for line in pre_ready:
            runner.on_testing_line_output(line + "\n")

        assert runner.protocol.state == ProtocolState.WAITING_FOR_READY


class TestTimingIntegration:
    """Test timing tracking through the runner pipeline."""

    def test_timing_tracked_for_doctest_tests(self):
        """Test start markers feed into timing tracker via router."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Suite/fast",
            "  CHECK( true ) is correct!",
            ">>> TEST START: Suite/second",
            "  CHECK( true ) is correct!",
            "[doctest] test cases:  2 |  2 passed | 0 failed |",
            "DONE",
        ])

        runner.timing_tracker.finalize()
        assert "Suite/fast" in runner.timing_tracker.durations
        assert "Suite/second" in runner.timing_tracker.durations


class TestMemoryIntegration:
    """Test memory tracking through the runner pipeline."""

    def test_memory_markers_tracked(self):
        """[MEM] markers feed into memory tracker via router."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Suite/test",
            "[MEM] Before: free=200000, min=180000",
            "[MEM] After: free=199000 (delta=-1000), min=179000",
            "[doctest] test cases:  1 |  1 passed | 0 failed |",
            "DONE",
        ])

        # Test name should have been synced from protocol to memory tracker
        assert len(runner.memory_tracker.all_tests) > 0

    def test_multiple_tests_memory_independent(self):
        """Each test gets its own memory tracking."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Suite/clean",
            "[MEM] Before: free=200000, min=180000",
            "[MEM] After: free=199800 (delta=-200), min=179800",
            ">>> TEST START: Suite/leaky",
            "[MEM] Before: free=199800, min=179800",
            "[MEM] After: free=187000 (delta=-12800), min=177000",
            "[MEM] WARNING: Test leaked ~12800 bytes!",
            "[doctest] test cases:  2 |  2 passed | 0 failed |",
            "DONE",
        ])

        leaks = runner.memory_tracker.leaks
        assert "Suite/clean" not in leaks
        assert "Suite/leaky" in leaks

    def test_leak_report_includes_delta(self):
        """Leak report shows the byte count."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Suite/big_leak",
            "[MEM] Before: free=200000, min=180000",
            "[MEM] After: free=180000 (delta=-20000), min=170000",
            "[doctest] test cases:  1 |  1 passed | 0 failed |",
            "DONE",
        ])

        report = runner.memory_tracker.report()
        assert "big_leak" in report
        assert "-20000" in report or "20000" in report


class TestSleepOrchestration:
    """Test sleep detection through the runner pipeline."""

    def test_sleep_detected_with_test_name(self):
        """SLEEP: sentinel captures duration and sleeping test name."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Orientation/sleep wake test",
            "[MEM] Before: free=200000, min=180000",
            "  CHECK( orientation == PORTRAIT ) is correct!",
            "SLEEP: 15000",
        ])

        assert runner.protocol.state == ProtocolState.SLEEPING
        assert runner.protocol.sleep_duration_ms == 15000
        assert runner.protocol.sleeping_test_name == "sleep wake test"

    def test_sleep_wake_resume_protocol(self):
        """Simulate full sleep - wake - resume - done cycle."""
        runner = make_runner()

        # First cycle: boot → ready → test → sleep
        feed_session(runner, [
            "READY",
            ">>> TEST START: Orientation/sleep wake test",
            "  CHECK( orientation == PORTRAIT ) is correct!",
            "SLEEP: 5000",
        ])

        assert runner.protocol.state == ProtocolState.SLEEPING

        # Simulate wake: reset protocol, feed wake cycle
        runner.protocol.reset_for_wake()
        assert runner.protocol.state == ProtocolState.WAITING_FOR_READY

        feed_session(runner, [
            "READY",
            "Runner filter applied: *sleep wake test*",
            ">>> TEST START: Orientation/sleep wake test",
            "  CHECK( wake_orientation == LANDSCAPE ) is correct!",
            "DONE",
        ])

        assert runner.protocol.state == ProtocolState.FINISHED


class TestCrashIntegration:
    """Test crash detection through the full pipeline."""

    def test_crash_captures_test_context(self):
        """Crash report includes the test name from protocol tracking."""
        runner = make_runner()

        lines = [
            "READY",
            ">>> TEST START: IMU/FIFO watermark interrupt",
            "[MEM] Before: free=200000, min=180000",
            "Guru Meditation Error: Core  0 panic'ed (LoadProhibited).",
        ]
        feed_session(runner, lines)
        # Feed enough post-crash lines to trigger finalization
        for i in range(20):
            runner.on_testing_line_output(f"  crash context line {i}\n")

        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
        # The crash case should reference the test that was running
        assert "IMU/FIFO watermark interrupt" in errored[0].name

    def test_wdt_crash_detected(self):
        """Task watchdog crash is detected."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Hang/infinite loop",
            "Task watchdog got triggered.",
        ])
        for i in range(20):
            runner.on_testing_line_output(f"  stack {i}\n")

        assert runner.test_suite._finished
        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1

    def test_backtrace_crash_detected(self):
        """Backtrace crash is detected."""
        runner = make_runner()

        runner.on_testing_line_output("Backtrace: 0x400d1234\n")
        for i in range(20):
            runner.on_testing_line_output(f"  0x{i:08x}\n")

        assert runner.test_suite._finished

    def test_crash_before_any_test(self):
        """Crash during boot (before any test starts) still detected."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            "Guru Meditation Error: Core  0 panic'ed (LoadProhibited).",
        ])
        for i in range(20):
            runner.on_testing_line_output(f"  reg {i}\n")

        assert runner.test_suite._finished
        errored = [c for c in runner.test_suite.cases if c.status == MockTestStatus.ERRORED]
        assert len(errored) == 1
        # No test was running, so crash name should use env fallback
        assert "crash" in errored[0].name


class TestSummaryReporting:
    """Test the summary output at end of test run."""

    def test_summary_reports_leaks(self, capsys):
        """Memory leaks appear in the summary."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Suite/leaky",
            "[MEM] Before: free=200000, min=180000",
            "[MEM] After: free=185000 (delta=-15000), min=175000",
            "[MEM] WARNING: Test leaked ~15000 bytes!",
            "[doctest] test cases:  1 |  1 passed | 0 failed |",
            "DONE",
        ])

        runner._print_summary()
        captured = capsys.readouterr()
        assert "leaky" in captured.out

    def test_summary_empty_when_no_issues(self, capsys):
        """No summary output when all tests are clean."""
        runner = make_runner()

        feed_session(runner, [
            "READY",
            ">>> TEST START: Suite/clean",
            "[MEM] Before: free=200000, min=180000",
            "[MEM] After: free=199800 (delta=-200), min=179800",
            "[doctest] test cases:  1 |  1 passed | 0 failed |",
            "DONE",
        ])

        runner._print_summary()
        captured = capsys.readouterr()
        # No memory leaks, no slow tests
        assert "leak" not in captured.out.lower()
