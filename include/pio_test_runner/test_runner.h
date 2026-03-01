#pragma once
#include <Arduino.h>

/// @brief PlatformIO test runner protocol — firmware-side API.
///
/// This header provides the wire protocol between firmware and the
/// pio-test-runner Python host. Both live in this repo so they stay
/// in sync. Include only the modules you need.
///
/// Modules:
///   - Disconnect: planned serial disconnections (deep sleep, reset)
///   - ReadyRun: bidirectional test orchestration (READY/RUN/DONE)
///   - Sleep: deep sleep signalling (SLEEP:<ms>)
///   - Memory: per-test heap markers ([MEM] Before/After)
///   - TestStart: test name markers (>>> TEST START)
///
/// @code
/// #include <pio_test_runner/test_runner.h>
/// @endcode

namespace pio_test_runner {

// =====================================================================
// Disconnect protocol
// =====================================================================

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

// =====================================================================
// Ready/Run/Done protocol
// =====================================================================

/// Signal that the device is ready to receive test commands.
/// The host will respond with RUN_ALL or RUN:<filter>.
inline void signal_ready() {
    Serial.println("READY");
    Serial.flush();
}

/// Signal that all tests have completed.
inline void signal_done() {
    Serial.println("DONE");
    Serial.flush();
}

/// Wait for a test command from the host.
///
/// Blocks until a non-empty line is received or timeout expires.
/// Returns empty String on timeout (no runner present — backward compat).
///
/// @param timeout_ms  Maximum time to wait in milliseconds.
/// @return Command string: "RUN_ALL", "RUN: <filter>", or "" on timeout.
inline String wait_for_command(uint32_t timeout_ms = 5000) {
    uint32_t start = millis();
    String line;
    while (millis() - start < timeout_ms) {
        if (Serial.available()) {
            line = Serial.readStringUntil('\n');
            line.trim();
            if (line.length() > 0) return line;
        }
        delay(10);
    }
    return "";  // timeout — no runner present
}

// =====================================================================
// Sleep signalling
// =====================================================================

/// Signal that the device is entering deep sleep for @p duration_ms.
/// The host will wait this long plus padding before reconnecting.
///
/// After calling this, the device should enter deep sleep. The host
/// uses the sleeping test name to build a filter for the wake cycle.
inline void signal_sleep(uint32_t duration_ms) {
    Serial.printf("SLEEP: %lu\n", (unsigned long)duration_ms);
    Serial.flush();
}

// =====================================================================
// Memory markers
// =====================================================================

/// Print heap stats before a test (parsed by MemoryTracker receiver).
inline void print_mem_before(size_t free_heap, size_t min_heap) {
    Serial.printf("[MEM] Before: free=%zu, min=%zu\n", free_heap, min_heap);
}

/// Print heap stats after a test (parsed by MemoryTracker receiver).
inline void print_mem_after(size_t free_heap, int64_t delta, size_t min_heap) {
    Serial.printf("[MEM] After: free=%zu (delta=%+lld), min=%zu\n",
                  free_heap, (long long)delta, min_heap);
}

/// Print a memory leak warning.
inline void print_mem_warning(int64_t leaked_bytes) {
    Serial.printf("[MEM] WARNING: Test leaked ~%lld bytes!\n",
                  (long long)leaked_bytes);
}

// =====================================================================
// Test start markers
// =====================================================================

/// Print a test start marker (parsed by TestTimingTracker receiver).
inline void print_test_start(const char* suite, const char* name) {
    Serial.printf("\n>>> TEST START: %s/%s\n", suite, name);
}

/// Print a test start marker with timeout annotation.
inline void print_test_start(const char* suite, const char* name, float timeout_s) {
    Serial.printf("\n>>> TEST START [timeout=%.0fs]: %s/%s\n",
                  timeout_s, suite, name);
}

}  // namespace pio_test_runner
