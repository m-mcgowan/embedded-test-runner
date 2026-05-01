"""Tests for receiver plugin discovery via setuptools entry points."""

from conftest import (
    FakeEntryPoint,
    MockProjectConfig,
    MockTestRunnerOptions,
    MockTestSuite,
    fake_entry_points,
)

from etst.runner import EmbeddedTestRunner


class _RecordingReceiver:
    """Minimal plugin receiver that just records what it sees."""

    def __init__(self, runner):
        self.runner = runner
        self.messages = []
        self.partition_started = 0
        self.partition_completed = 0

    def feed(self, message):
        self.messages.append(message)


def make_runner_with_plugins(plugins):
    """Build a runner with fake entry-point plugins active."""
    eps = [FakeEntryPoint(name, cls) for name, cls in plugins.items()]
    with fake_entry_points({"embedded_test_runner.receivers": eps}):
        return EmbeddedTestRunner(
            MockTestSuite(), MockProjectConfig(), MockTestRunnerOptions()
        )


def test_plugin_is_discovered_and_instantiated():
    runner = make_runner_with_plugins({"recording": _RecordingReceiver})

    # Plugin instances are tracked separately so lifecycle hooks can find them.
    assert len(runner._plugin_receivers) == 1
    plugin = runner._plugin_receivers[0]
    assert isinstance(plugin, _RecordingReceiver)
    assert plugin.runner is runner


def test_plugin_receives_messages_through_router():
    runner = make_runner_with_plugins({"recording": _RecordingReceiver})
    plugin = runner._plugin_receivers[0]

    runner.router.feed("hello")
    runner.router.feed("world")

    assert plugin.messages == ["hello", "world"]
