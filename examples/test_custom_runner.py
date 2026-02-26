"""PlatformIO custom test runner shim.

Copy this file to ``test/test_custom_runner.py`` in your PlatformIO
project and set ``test_framework = custom`` in ``platformio.ini``.

PIO discovers runners by file path and class name — the class must be
called ``CustomTestRunner``. This shim delegates to the pip-installed
``pio_test_runner`` package.
"""

from pio_test_runner.runner import EmbeddedTestRunner


class CustomTestRunner(EmbeddedTestRunner):
    """Delegates to EmbeddedTestRunner from pio-test-runner.

    Override methods here for project-specific customization, e.g.:

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Custom crash patterns
            self.crash_detector._patterns.append(
                CrashPattern("my_error", "MY_FATAL_ERROR")
            )
            # Longer silent timeout
            self.crash_detector._silent_timeout = 120.0
    """

    pass
