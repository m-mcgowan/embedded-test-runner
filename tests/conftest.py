"""Pytest hook: install the PlatformIO mocks before any test module imports.

The mocks themselves live in `pio_mocks.py`, not here. A `conftest.py` is
imported by pytest under the bare module name `conftest`, and this repo has
two of them — `tests/` and `tests/acceptance/` — so whichever loads first
claims the name for the whole session. Test modules that did
`from conftest import MockProjectConfig` got the acceptance one and failed to
import. Shared helpers therefore belong in a normally-importable module, and
this file keeps only the side effect that has to happen at conftest time.
"""

from pio_mocks import install_pio_mocks

# Must run before any test module imports etst.runner, which imports
# platformio at module scope.
install_pio_mocks()


def pytest_addoption(parser):
    """Declare the acceptance tests' hardware options.

    These belong to `tests/acceptance/`, but they have to be declared here.
    pytest only calls `pytest_addoption` on *initial* conftests — the rootdir
    one, and those whose directory is named on the command line — so an
    option declared in `tests/acceptance/conftest.py` simply does not exist
    during a whole-tree run, and every fixture reading it dies with
    `ValueError: no option named 'port'`. This file is always initial.

    Neither is `required=True`: pytest enforces a requirement across the whole
    session rather than the directory that asked for it, so a required --port
    would make every plain `pytest` run fail before collecting anything. The
    `port` fixture skips when it is absent instead.
    """
    parser.addoption("--port", help="Serial port for the device (acceptance tests)")
    parser.addoption("--baud", default=115200, type=int, help="Baud rate")
