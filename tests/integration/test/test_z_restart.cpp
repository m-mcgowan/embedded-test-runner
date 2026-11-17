/**
 * @file test_z_restart.cpp
 * @brief Tests the RESTART protocol with an actual ESP32-S3 software reset.
 *
 * Deep sleep and a software restart are not the same event, and the
 * difference is the whole reason this file exists alongside
 * test_z_deep_sleep.cpp. Deep sleep drops the USB-CDC port; a software CPU
 * reset leaves USB-Serial-JTAG enumerated, so the port never disappears and
 * the rebooted device is already back in wait_for_command() by the time the
 * host notices anything.
 *
 * That asymmetry hid a regression in 0.4.0: the runner treated ETST:RESTART as
 * the end of the cycle and sent the end-of-run command (ETST_ON_DONE, default
 * WAIT) to a device that was waiting for its FIRST command. The device read
 * WAIT as a run with no filter and started the suite again from the top, the
 * resume for the restarted case arrived at a busy device and was ignored, and
 * the run ended with most of its tests never run. Nothing in this project's
 * own integration suite could see it, because nothing here restarted.
 *
 * Two-phase, the same shape as the sleep tests. Note that neither phase needs
 * RTC memory: is_test_wake() is driven by the host, which appends --wake to
 * the filter it builds for the resume cycle, so the fact of the wake arrives
 * from outside rather than surviving the reset.
 *
 * "runs after the restart test" is the one that fails loudly if a resume goes
 * wrong — a rerun from the top or a skipped case shows up as this never
 * running, or as the run reporting fewer tests than it has.
 */

#include <doctest.h>
#include <Arduino.h>
#include <esp_system.h>
#include <etst/test_runner.h>

TEST_SUITE("Restart") {

TEST_CASE("survives a software restart" * doctest::timeout(45)) {
    if (etst::is_test_wake()) {
        // Phase 2: the host resumed us after the reboot.
        auto reason = esp_reset_reason();
        Serial.printf("Restart: Phase 2 — reset reason=%d\n", (int)reason);
        CHECK(reason == ESP_RST_SW);
    } else {
        // Phase 1: announce, then reset. The port stays enumerated across
        // this, which is exactly the condition the 0.4.0 bug needed.
        Serial.println("Restart: Phase 1 — restarting");
        CHECK(true);

        etst::signal_restart();
        Serial.flush();
        delay(100);

        esp_restart();
        // never reached
    }
}

TEST_CASE("runs after the restart test" * doctest::timeout(10)) {
    // If the resume after a restart is wrong, this never runs: either the
    // device restarted the whole suite (and this is reached only on a cycle
    // that then fails), or the resume skipped past it. Either way the run
    // cannot account for its own tests.
    Serial.println("Post-restart test: running after the restart test");
    CHECK(true);
}

}
