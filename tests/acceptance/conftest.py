"""Acceptance test fixtures for on-device filter validation."""

import subprocess
import time

import pytest


def pytest_addoption(parser):
    parser.addoption("--port", required=True, help="Serial port for the device")
    parser.addoption("--baud", default=115200, type=int, help="Baud rate")


@pytest.fixture(scope="session")
def port(request):
    return request.config.getoption("--port")


@pytest.fixture(scope="session")
def baud(request):
    return request.config.getoption("--baud")


@pytest.fixture(scope="session", autouse=True)
def ensure_device_awake(port):
    """Ensure device is awake at the start of the test session.

    After pio test runs, the device enters deep sleep (SLEEP command).
    This fixture tries to open the port and, if the device is sleeping,
    resets it via usb-device.
    """
    import serial as pyserial

    try:
        ser = pyserial.Serial(port, 115200, timeout=2)
        line = ser.readline().decode("utf-8", errors="replace")
        ser.close()
        if "PTR:READY" in line:
            return  # Already awake
    except Exception:
        pass

    # Device likely sleeping or port gone — try reset
    print(f"[accept] Device not responding on {port}, attempting reset...")
    subprocess.run(["usb-device", "reset", port], capture_output=True, timeout=10)
    time.sleep(5)
