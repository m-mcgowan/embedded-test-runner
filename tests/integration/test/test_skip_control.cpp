/**
 * @file test_skip_control.cpp
 * @brief Integration tests for runtime skip control.
 *
 * Tests the --unskip-tc, --skip-tc, --unskip-ts, --skip-ts flags
 * and their interaction with doctest's native filters.
 *
 * Target tests have intentionally varied names to exercise:
 * - Names with spaces
 * - Names with special characters (/)
 * - Suite-level matching
 */

#include <doctest.h>

// =========================================================================
// Skip-decorated targets — unskipped by --unskip-tc / --unskip-ts
// =========================================================================

TEST_SUITE("SkipControl") {

TEST_CASE("unskip target simple" * doctest::skip()) {
    // Unskip with: --unskip-tc *unskip*target*simple*
    CHECK(true);
    MESSAGE("unskip target simple: successfully unskipped");
}

TEST_CASE("unskip target with spaces in name" * doctest::skip()) {
    // Unskip with: --unskip-tc "*unskip target with spaces*"
    // Tests that quoted patterns with spaces work correctly.
    CHECK(true);
    MESSAGE("unskip target with spaces: successfully unskipped");
}

TEST_CASE("skip target active") {
    // NOT skip-decorated. Skip with: --skip-tc *skip*target*active*
    CHECK(true);
}

}  // TEST_SUITE SkipControl

TEST_SUITE("SkipControl/SubSuite") {

TEST_CASE("suite unskip target" * doctest::skip()) {
    // Unskip via suite: --unskip-ts *SubSuite*
    CHECK(true);
    MESSAGE("suite unskip target: successfully unskipped via suite match");
}

}  // TEST_SUITE SkipControl/SubSuite
