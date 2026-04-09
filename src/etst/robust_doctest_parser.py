"""Robust doctest parser that handles non-source lines ending with ':'.

PlatformIO's ``DoctestTestCaseParser.parse_source()`` crashes on lines
ending with ':' that aren't source references (e.g. '1. Environment
Configuration:'). This parser wraps the call with proper error handling.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from platformio.test.result import TestCaseSource
    from platformio.test.runners.doctest import DoctestTestCaseParser

    _HAS_PIO = isinstance(DoctestTestCaseParser, type)
except (ImportError, TypeError):
    _HAS_PIO = False
    DoctestTestCaseParser = None
    TestCaseSource = None


def _parse_source(line):
    """Parse a source reference from a line ending with ':'.

    Returns (filename, lineno) tuple or TestCaseSource, or None.
    """
    if not line.endswith(":"):
        return None
    try:
        filename, lineno = line[:-1].rsplit(":", 1)
        lineno_int = int(lineno)
        if _HAS_PIO and TestCaseSource is not None:
            return TestCaseSource(filename, lineno_int)
        return (filename, lineno_int)
    except (ValueError, TypeError):
        return None


if _HAS_PIO and DoctestTestCaseParser is not None:

    class RobustDoctestParser(DoctestTestCaseParser):
        """Fix PIO's parse_source which crashes on lines ending with ':'
        that aren't source references."""

        parse_source = staticmethod(_parse_source)

else:

    class RobustDoctestParser:  # type: ignore[no-redef]
        """Standalone parser for non-PIO environments."""

        parse_source = staticmethod(_parse_source)
