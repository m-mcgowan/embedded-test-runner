"""Tests for host-side env var collection and ARGS line building."""

import os
from unittest.mock import patch

from conftest import MockProjectConfig, MockTestRunnerOptions, MockTestSuite
from etst.runner import EmbeddedTestRunner


def make_runner(**kwargs):
    suite = kwargs.pop("test_suite", None) or MockTestSuite()
    config = kwargs.pop("project_config", None) or MockProjectConfig()
    options = kwargs.pop("options", None) or MockTestRunnerOptions()
    return EmbeddedTestRunner(suite, config, options)


class TestCollectEnvVars:
    def test_etst_env_collected(self):
        runner = make_runner()
        with patch.dict(os.environ, {
            "ETST_ENV_DEVICE_REV": "1.10",
            "ETST_ENV_HAS_GPS": "1",
            "ETST_CASE": "*foo*",
            "HOME": "/home/test",
        }, clear=True):
            env_vars = runner._collect_env_vars()
        assert env_vars == {"DEVICE_REV": "1.10", "HAS_GPS": "1"}

    def test_program_args_env_overrides_host_env(self):
        options = MockTestRunnerOptions()
        options.program_args = ["--env", "DEVICE_REV=2.0", "--tc", "*foo*"]
        runner = make_runner(options=options)
        with patch.dict(os.environ, {
            "ETST_ENV_DEVICE_REV": "1.10",
            "ETST_ENV_HAS_GPS": "1",
        }, clear=True):
            env_vars = runner._collect_env_vars()
        assert env_vars["DEVICE_REV"] == "2.0"
        assert env_vars["HAS_GPS"] == "1"

    def test_empty_when_no_env_vars(self):
        runner = make_runner()
        with patch.dict(os.environ, {}, clear=True):
            env_vars = runner._collect_env_vars()
        assert env_vars == {}


class TestBuildArgsAndRun:
    def test_env_vars_produce_args_lines(self):
        runner = make_runner()
        with patch.dict(os.environ, {
            "ETST_ENV_DEVICE_REV": "1.10",
        }, clear=True):
            args_lines, run_cmd = runner._build_args_and_run()
        assert any("--env DEVICE_REV=1.10" in line for line in args_lines)
        assert run_cmd == "RUN"

    def test_filters_produce_args_lines(self):
        runner = make_runner()
        with patch.dict(os.environ, {
            "ETST_CASE": "*foo*",
        }, clear=True):
            args_lines, run_cmd = runner._build_args_and_run()
        assert any("--tc *foo*" in line for line in args_lines)
        assert run_cmd == "RUN"

    def test_no_filters_no_env_produces_run_all(self):
        runner = make_runner()
        with patch.dict(os.environ, {}, clear=True):
            args_lines, run_cmd = runner._build_args_and_run()
        assert args_lines == []
        assert run_cmd == "RUN_ALL"

    def test_resume_after_still_works(self):
        runner = make_runner()
        with patch.dict(os.environ, {
            "ETST_RESUME_AFTER": "my_test",
            "ETST_CASE": "*foo*",
        }, clear=True):
            args_lines, run_cmd = runner._build_args_and_run()
        assert "RESUME_AFTER:" in run_cmd
