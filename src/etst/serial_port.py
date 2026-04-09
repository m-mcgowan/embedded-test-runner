"""Safe serial port management for ESP32 USB-CDC devices.

Mirrors PlatformIO device monitor's serial setup: ``do_not_open=True``,
only set DTR/RTS if explicitly requested (reset=True), then ``open()``.
When reset=False (reconnect after restart/sleep), DTR/RTS are left as
None — pyserial sends no SET_CONTROL_LINE_STATE USB control transfer,
avoiding USB_UART_CHIP_RESET on ESP32-S3.

Usage::

    from etst.serial_port import open_serial

    ser = open_serial("/dev/cu.usbmodem1424101")
    # Device is NOT reset — DTR/RTS not touched
    line = ser.readline()

To intentionally reset the device (e.g. after upload)::

    ser = open_serial("/dev/cu.usbmodem1424101", reset=True)
"""

import time

try:
    import serial as pyserial
except ImportError:
    pyserial = None


def open_serial(port, baudrate=115200, timeout=1, reset=False, retries=5):
    """Open a serial port without triggering a device reset.

    Mirrors PlatformIO device monitor: ``serial_for_url(do_not_open=True)``
    then ``open()`` without touching DTR/RTS. This avoids sending a
    SET_CONTROL_LINE_STATE USB control transfer that could trigger
    USB_UART_CHIP_RESET on ESP32-S3.

    Args:
        port: Serial port path (e.g. /dev/cu.usbmodem1424101)
        baudrate: Baud rate (default 115200)
        timeout: Read timeout in seconds (default 1)
        reset: If True, assert DTR/RTS to trigger device reset after open
        retries: Number of retry attempts if port not ready (USB re-enum)

    Returns:
        An open serial.Serial instance

    Raises:
        serial.SerialException: If port cannot be opened after retries
    """
    if pyserial is None:
        raise RuntimeError("pyserial not installed: pip install pyserial")

    for attempt in range(retries):
        try:
            ser = pyserial.serial_for_url(port, do_not_open=True)
            ser.baudrate = baudrate
            ser.timeout = timeout

            # When reset=False, leave DTR/RTS as None (pyserial default).
            # This means pyserial sends NO SET_CONTROL_LINE_STATE during
            # open(), matching PIO device monitor behavior. Explicitly
            # setting dtr=False would send a USB control transfer that
            # can trigger USB_UART_CHIP_RESET on some ESP32-S3 boards.

            ser.open()

            if reset:
                # DTR/RTS toggle to trigger reset
                ser.flushInput()
                ser.setDTR(False)
                ser.setRTS(False)
                time.sleep(0.1)
                ser.setDTR(True)
                ser.setRTS(True)
                time.sleep(0.1)

            ser.reset_input_buffer()
            return ser

        except (OSError, pyserial.SerialException):
            if attempt < retries - 1:
                time.sleep(1)
            else:
                raise
