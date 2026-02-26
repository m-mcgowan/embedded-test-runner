"""PlatformIO test runner plugin for embedded devices.

Extends PlatformIO's TestRunnerBase with crash detection, disconnect
handling, and framework-agnostic test result parsing via embedded-bridge
receivers.
"""

import logging

try:
    import click
except ImportError:
    click = None

from embedded_bridge.receivers import CrashDetector, Router

from .disconnect import DisconnectHandler
from .result_receiver import TestResultReceiver

logger = logging.getLogger(__name__)

# Import PIO classes — available at runtime when used as a PIO plugin.
# Tests mock these.
try:
    from platformio.test.result import TestCase, TestStatus
    from platformio.test.runners.base import TestRunnerBase
except ImportError:
    TestRunnerBase = object
    TestCase = None
    TestStatus = None


class EmbeddedTestRunner(TestRunnerBase):
    """PlatformIO test runner with crash detection and disconnect handling.

    Uses embedded-bridge receivers to monitor device output for crashes,
    manage disconnect/reconnect windows, and parse test results from any
    supported framework (doctest, Unity, auto-detect).

    Register in ``platformio.ini``::

        [env:esp32s3]
        test_framework = custom
        custom_test_runner = pio_test_runner.runner
    """

    NAME = "embedded"

    def __init__(self, test_suite, project_config, options=None):
        super().__init__(test_suite, project_config, options)

        self.crash_detector = CrashDetector()
        self.disconnect_handler = DisconnectHandler()
        self.result_receiver = TestResultReceiver(framework="auto")

        self.router = Router([
            (self.crash_detector, None),
            (self.disconnect_handler, None),
            (self.result_receiver, None),
        ])

    def on_testing_line_output(self, line):
        """Process a line of test output.

        Routes to all receivers, then handles state:
        - Crash detected → report error, finish suite
        - Disconnect active → suppress output
        - Results available → forward to PIO test suite
        - Completion detected → finish suite
        """
        if self.test_suite.is_finished():
            return

        self.router.feed(line)

        # Crash → immediate abort
        if self.crash_detector.triggered:
            crash = self.crash_detector.crash
            self.test_suite.add_case(TestCase(
                name=f"{self.test_suite.env_name}:crash",
                status=TestStatus.ERRORED,
                message=crash.reason,
                stdout="\n".join(crash.lines),
            ))
            self.test_suite.on_finish()
            return

        # Disconnect active → suppress output
        if self.disconnect_handler.active:
            return

        # Forward test results to PIO
        for result in self.result_receiver.drain_results():
            status = TestStatus.PASSED if result.passed else TestStatus.FAILED
            self.test_suite.add_case(TestCase(
                name=result.name,
                status=status,
                message=result.message,
            ))

        # Completion → finish suite
        if self.result_receiver.is_complete:
            self.test_suite.on_finish()
            return

        # Echo line for user visibility
        if click is not None:
            click.echo(line, nl=False)
        else:
            print(line, end="")

    def teardown(self):
        """Check for silent hang on teardown."""
        self.crash_detector.check_timeout()
        if self.crash_detector.triggered and not self.test_suite.is_finished():
            crash = self.crash_detector.crash
            self.test_suite.add_case(TestCase(
                name=f"{self.test_suite.env_name}:hang",
                status=TestStatus.ERRORED,
                message=crash.reason,
            ))
