"""Tests for RobustDoctestParser."""

from etst.robust_doctest_parser import RobustDoctestParser


class TestRobustDoctestParser:
    def test_valid_source_reference(self):
        result = RobustDoctestParser.parse_source("test/test_foo.cpp:42:")
        assert result is not None
        assert result[0] == "test/test_foo.cpp"
        assert result[1] == 42

    def test_non_source_colon_line(self):
        result = RobustDoctestParser.parse_source("1. Environment Configuration:")
        assert result is None

    def test_no_trailing_colon(self):
        result = RobustDoctestParser.parse_source("just a normal line")
        assert result is None

    def test_empty_string(self):
        result = RobustDoctestParser.parse_source("")
        assert result is None

    def test_colon_only(self):
        result = RobustDoctestParser.parse_source(":")
        assert result is None

    def test_non_numeric_line_number(self):
        result = RobustDoctestParser.parse_source("file.cpp:abc:")
        assert result is None

    def test_nested_colons_valid(self):
        result = RobustDoctestParser.parse_source("/long/path/to/file.cpp:123:")
        assert result is not None
        assert result[0] == "/long/path/to/file.cpp"
        assert result[1] == 123

    def test_windows_path(self):
        result = RobustDoctestParser.parse_source("C:\\src\\test.cpp:99:")
        assert result is not None
        assert result[1] == 99
