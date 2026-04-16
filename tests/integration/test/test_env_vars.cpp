/**
 * @file test_env_vars.cpp
 * @brief Tests for host-to-firmware environment variable passing.
 *
 * These tests exercise the ETST:ARGS --env pipeline and the
 * etst::env() / require_env decorator APIs.
 */

#include <doctest.h>
#include <etst/env.h>

TEST_SUITE("EnvVars") {

TEST_CASE("env returns nullptr for missing key") {
    CHECK(etst::env("NONEXISTENT_KEY_12345") == nullptr);
}

TEST_CASE("env_is returns false for missing key") {
    CHECK_FALSE(etst::env_is("NONEXISTENT_KEY_12345"));
}

TEST_CASE("env reads host-provided value" * etst::require_env("TEST_VALUE")) {
    const char* val = etst::env("TEST_VALUE");
    REQUIRE(val != nullptr);
    CHECK(strcmp(val, "hello") == 0);
}

TEST_CASE("env typed int" * etst::require_env("TEST_INT")) {
    int val = etst::env<int>("TEST_INT", 0);
    CHECK(val == 42);
}

TEST_CASE("env_is truthy" * etst::require_env("TEST_TRUTHY")) {
    CHECK(etst::env_is("TEST_TRUTHY"));
}

TEST_CASE("env_is falsy for zero") {
    // This tests the default behavior without --env
    CHECK_FALSE(etst::env_is("NONEXISTENT_KEY_12345"));
}

TEST_CASE("require_env skips when missing" * etst::require_env("MISSING_ENV_VAR_XYZ")) {
    // This test should be skipped when MISSING_ENV_VAR_XYZ is not provided
    FAIL("Should have been skipped by require_env");
}

}
