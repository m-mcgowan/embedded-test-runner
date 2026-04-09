/**
 * @file test_disconnect.cpp
 * @brief Tests the ETST:DISCONNECT/RECONNECT protocol markers.
 *
 * Emits disconnect/reconnect markers that the Python DisconnectHandler
 * parses. No actual serial disconnect — just protocol validation.
 * Output between DISCONNECT and RECONNECT should be suppressed by the
 * runner in line callback mode.
 */

#include <doctest.h>
#include <Arduino.h>
#include <etst/test_runner.h>

TEST_SUITE("Disconnect") {

TEST_CASE("disconnect/reconnect markers parsed") {
    CHECK(true);  // pre-disconnect assertion

    etst::request_disconnect(500);
    delay(100);
    Serial.println("this line should be suppressed by the runner");
    etst::signal_reconnect();

    CHECK(true);  // post-reconnect assertion
}

}
