/// Test entry point — provides setup()/loop() and doctest implementation.

#define DOCTEST_CONFIG_IMPLEMENT
#include <doctest.h>
#include <etst/doctest/runner.h>

// board_init.cpp provides board_init() as a strong symbol.
extern bool board_init(Print& log);

void setup() {
    etst::config.board_init = board_init;
    etst::doctest::run_tests();
}

void loop() {
    etst::doctest::idle_loop();
}
