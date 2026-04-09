/**
 * @file doctest_default_main.cpp
 * @brief Default Arduino entry points for doctest test runner.
 *
 * Provides weak setup()/loop() so consuming projects don't need a
 * main.cpp for simple cases. For customization, define your own
 * setup() (strong symbol) and set etst::config / etst::doctest::config
 * before calling etst::doctest::run_tests().
 *
 * Example — test/main.cpp:
 * @code
 *   #define DOCTEST_CONFIG_IMPLEMENT
 *   #include <doctest.h>
 *   #include <etst/doctest/runner.h>
 *
 *   static bool my_board_init(Print& log) {
 *       log.println("My board init");
 *       return true;
 *   }
 *
 *   void setup() {
 *       etst::config.board_init = my_board_init;
 *       etst::doctest::run_tests();
 *   }
 *   void loop() { etst::doctest::idle_loop(); }
 * @endcode
 */

#define DOCTEST_CONFIG_IMPLEMENT
#include <doctest.h>
#include <etst/doctest/runner.h>

// =========================================================================
// Default Arduino entry points (weak — existing main.cpp overrides these)
// =========================================================================

__attribute__((weak)) void setup() {
    etst::doctest::run_tests();
}

__attribute__((weak)) void loop() {
    etst::doctest::idle_loop();
}
