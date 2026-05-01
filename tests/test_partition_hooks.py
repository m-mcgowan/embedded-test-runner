"""Tests for partition lifecycle hooks (on_partition_start / on_partition_complete)."""

from conftest import (
    FakeEntryPoint,
    MockProjectConfig,
    MockTestRunnerOptions,
    MockTestSuite,
    fake_entry_points,
)

from etst.runner import EmbeddedTestRunner


class _LifecycleRecorder:
    def __init__(self, runner):
        self.runner = runner
        self.events = []

    def feed(self, message):
        pass

    def on_partition_start(self):
        self.events.append("start")

    def on_partition_complete(self):
        self.events.append("complete")


def make_runner_with_plugin(plugin_cls):
    eps = [FakeEntryPoint("recorder", plugin_cls)]
    with fake_entry_points({"embedded_test_runner.receivers": eps}):
        return EmbeddedTestRunner(
            MockTestSuite(), MockProjectConfig(), MockTestRunnerOptions()
        )


def test_default_hooks_are_no_op_with_no_plugins():
    runner = EmbeddedTestRunner(
        MockTestSuite(), MockProjectConfig(), MockTestRunnerOptions()
    )

    # Should not raise.
    runner.on_partition_start()
    runner.on_partition_complete()


def test_setup_invokes_on_partition_start_on_plugins():
    runner = make_runner_with_plugin(_LifecycleRecorder)
    plugin = runner._plugin_receivers[0]

    runner.setup()

    assert plugin.events == ["start"]


def test_teardown_invokes_on_partition_complete_on_plugins():
    runner = make_runner_with_plugin(_LifecycleRecorder)
    plugin = runner._plugin_receivers[0]

    runner.teardown()

    assert plugin.events == ["complete"]


def test_full_lifecycle_order():
    runner = make_runner_with_plugin(_LifecycleRecorder)
    plugin = runner._plugin_receivers[0]

    runner.setup()
    # ... stage_testing would happen here in a real run ...
    runner.teardown()

    assert plugin.events == ["start", "complete"]


class _BrokenStartReceiver:
    def __init__(self, runner):
        self.completed = False

    def feed(self, message):
        pass

    def on_partition_start(self):
        raise RuntimeError("start blew up")

    def on_partition_complete(self):
        self.completed = True


def test_hook_exception_in_one_plugin_does_not_block_others(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="etst.runner")

    eps = [
        FakeEntryPoint("broken", _BrokenStartReceiver),
        FakeEntryPoint("recorder", _LifecycleRecorder),
    ]
    with fake_entry_points({"embedded_test_runner.receivers": eps}):
        runner = EmbeddedTestRunner(
            MockTestSuite(), MockProjectConfig(), MockTestRunnerOptions()
        )

    runner.on_partition_start()

    # Recorder still got "start" despite the broken plugin raising.
    recorder = next(p for p in runner._plugin_receivers
                    if isinstance(p, _LifecycleRecorder))
    assert recorder.events == ["start"]
    assert any("broken" in rec.message.lower() or "start blew up" in rec.message
               for rec in caplog.records)


def test_complete_runs_even_after_failed_start():
    eps = [FakeEntryPoint("broken", _BrokenStartReceiver)]
    with fake_entry_points({"embedded_test_runner.receivers": eps}):
        runner = EmbeddedTestRunner(
            MockTestSuite(), MockProjectConfig(), MockTestRunnerOptions()
        )

    runner.on_partition_start()  # raises internally, swallowed
    runner.on_partition_complete()

    plugin = runner._plugin_receivers[0]
    assert plugin.completed is True
