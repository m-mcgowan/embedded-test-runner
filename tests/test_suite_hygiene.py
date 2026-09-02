"""Guards that the test suite is collectable by a plain `pytest` run.

The suite is normally run through CI's explicit selection
(`pytest tests/ --ignore=tests/integration --ignore=tests/acceptance`).
That selection hid two defects that only a bare run exposes:

  * `tests/acceptance/conftest.py` and `tests/conftest.py` both claim the
    top-level module name `conftest`, so `from conftest import ...` in a
    unit test resolved to whichever loaded first (acceptance, alphabetically).
  * The acceptance conftest declared `--port` itself. `pytest_addoption` is
    only honoured in an *initial* conftest — the rootdir one, or one whose
    directory is named on the command line — so a bare run never declared
    the option at all, and every acceptance fixture died on
    `ValueError: no option named 'port'`. Declaring it `required=True` was
    the other half: pytest applies a requirement to the whole session, not
    just the directory whose conftest asked for it.

Collection is the cheapest thing that catches both, and it needs no
hardware: `--collect-only` imports every test module without running it.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _collect(*args):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def test_bare_run_collects_every_test_module():
    """`pytest tests/` must import every module — no ignore flags needed."""
    result = _collect("tests/")
    assert result.returncode == 0, (
        "bare collection failed:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_acceptance_directory_collects_without_hardware_options():
    """Acceptance tests declare hardware options; collecting must not need them."""
    result = _collect("tests/acceptance")
    assert result.returncode == 0, (
        "acceptance collection demanded options it should only need at run time:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_acceptance_fixtures_skip_rather_than_error_without_a_port():
    """A whole-tree run must skip the hardware tests, not error in setup.

    Invoked as `tests/` rather than `tests/acceptance` on purpose: that is
    what makes the acceptance conftest a non-initial one, which is the
    condition under which its options went undeclared. `-k` keeps this to a
    single test — and keeps this module from re-entering itself.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/", "-k", "test_start_markers_present"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0 and "error" not in result.stdout.lower(), (
        "acceptance fixtures errored instead of skipping:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "1 skipped" in result.stdout, (
        f"expected the hardware test to skip, got:\n{result.stdout}"
    )
