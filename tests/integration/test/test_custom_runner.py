"""PlatformIO custom test runner — bootstraps embedded-test-runner.

This file is the only one consuming projects need to copy. It finds the
library's Python source via PIO's libdeps directory (supports symlinks)
and delegates everything to EmbeddedTestRunner.

Customize test behavior on the firmware side via the etst::config struct
in any .cpp file (set fields before DOCTEST_SETUP() runs):
    etst::config.board_init = my_init;        // Print& log -> bool
    etst::config.after_cycle = my_cleanup;    // void()
    etst::config.platform_restart = my_reset; // void()
"""

import os
import sys
import glob

# Find embedded-test-runner and embedded-bridge Python sources in libdeps
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_test_dir, ".."))
for pattern in [
    os.path.join(_project_dir, ".pio", "libdeps", "*", "embedded-test-runner", "src"),
    os.path.join(_project_dir, ".pio", "libdeps", "*", "embedded-bridge", "python", "src"),
]:
    for p in glob.glob(pattern):
        if p not in sys.path:
            sys.path.insert(0, p)

from etst.runner import EmbeddedTestRunner  # noqa: E402


class CustomTestRunner(EmbeddedTestRunner):
    pass
