#pragma once
#include <Arduino.h>

/// @brief PlatformIO test runner protocol for planned disconnections.
///
/// Firmware uses these functions to tell the host test runner about
/// planned serial disconnections (deep sleep, reset, peripheral reflash).
/// The host pauses monitoring during the disconnect window and resumes
/// when the device signals reconnect.
///
/// @code
/// #include <pio_test_runner/test_runner.h>
///
/// void test_sleep_cycle() {
///     pio_test_runner::request_disconnect(5000);
///     Serial.flush();
///     Serial.end();
///     esp_deep_sleep(5000000);  // 5 seconds
/// }
///
/// void setup() {
///     Serial.begin(115200);
///     pio_test_runner::signal_reconnect();
///     // ... continue testing
/// }
/// @endcode
namespace pio_test_runner {

/// Tell the host we're going away for @p duration_ms milliseconds.
/// Call this BEFORE Serial.end() / deep sleep / reset.
inline void request_disconnect(uint32_t duration_ms) {
    Serial.printf("PTR:DISCONNECT:%lu\n", (unsigned long)duration_ms);
    Serial.flush();
}

/// Tell the host we're back. Call this AFTER Serial.begin().
inline void signal_reconnect() {
    Serial.println("PTR:RECONNECT");
    Serial.flush();
}

}  // namespace pio_test_runner
