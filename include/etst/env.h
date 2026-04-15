#pragma once

/// @file env.h
/// @brief Environment variable store for embedded test runner.
///
/// Provides a simple key-value store that test firmware can read to
/// customise behaviour at runtime (e.g. iteration counts, addresses,
/// thresholds injected by the host before each test run).
///
/// ## Storage
/// Variables are held in `etst::detail::env_store` (a vector of pairs).
/// Use `etst::detail::env_set()` / `etst::detail::env_clear()` to
/// populate the store from the firmware side (or from the protocol
/// layer in a later task).
///
/// ## Tier 1 — raw string access
/// @code
///   const char* host = etst::env("SERVER_HOST");   // nullptr if missing
///   if (etst::env_is("USE_TLS")) { … }              // falsy → false
/// @endcode
///
/// ## Tier 2 — typed access with defaults
/// @code
///   int  port    = etst::env<int>("PORT", 1883);
///   bool verbose = etst::env<bool>("VERBOSE", false);
/// @endcode
///
/// ## Guard macros
/// @code
///   ETST_REQUIRE_ENV("SERVER_HOST");           // early-return if not truthy
///   ETST_REQUIRE_ENV_EQ("MODE", "production"); // early-return if not equal
/// @endcode

#include <cstdlib>
#include <cstring>
#include <vector>
#include <utility>

#ifdef ARDUINO
#include <Arduino.h>
#else
#include <string>
using String = std::string;
#endif

namespace etst {
namespace detail {

/// The backing store: ordered list of (key, value) pairs.
/// Keys are case-sensitive. Last write wins (env_set scans linearly).
inline std::vector<std::pair<String, String>>& env_store() {
    static std::vector<std::pair<String, String>> store;
    return store;
}

/// Remove all variables from the store.
inline void env_clear() {
    env_store().clear();
}

/// Set @p key to @p value, overwriting any existing entry.
inline void env_set(const char* key, const char* value) {
    auto& store = env_store();
    for (auto& kv : store) {
        if (kv.first == key) {
            kv.second = value;
            return;
        }
    }
    store.emplace_back(key, value);
}

}  // namespace detail

// =====================================================================
// Tier 1 — raw string lookups
// =====================================================================

/// Look up @p key in the env store.
/// @return Pointer to the value string, or nullptr if not found.
inline const char* env(const char* key) {
    for (const auto& kv : detail::env_store()) {
        if (kv.first == key) {
            return kv.second.c_str();
        }
    }
    return nullptr;
}

/// Return true if @p key is set to a truthy value.
///
/// Returns false when:
///   - the key is missing
///   - the value is empty
///   - the value is "0"
///   - the value is "false" (case-insensitive)
///
/// Everything else is truthy.
inline bool env_is(const char* key) {
    const char* val = env(key);
    if (val == nullptr)   return false;
    if (val[0] == '\0')   return false;
    if (strcmp(val, "0") == 0) return false;
    if (strcasecmp(val, "false") == 0) return false;
    return true;
}

// =====================================================================
// Tier 2 — typed lookups with defaults
// =====================================================================

/// Generic template — only specialisations below are valid.
template <typename T>
T env(const char* key, T default_value);

/// int specialisation: parsed with strtol (base 10).
template <>
inline int env<int>(const char* key, int default_value) {
    const char* val = env(key);
    if (val == nullptr || val[0] == '\0') return default_value;
    char* end = nullptr;
    long result = strtol(val, &end, 10);
    if (end == val || *end != '\0') return default_value;
    return static_cast<int>(result);
}

/// long specialisation: parsed with strtol (base 10).
template <>
inline long env<long>(const char* key, long default_value) {
    const char* val = env(key);
    if (val == nullptr || val[0] == '\0') return default_value;
    char* end = nullptr;
    long result = strtol(val, &end, 10);
    if (end == val || *end != '\0') return default_value;
    return result;
}

/// float specialisation: parsed with strtof.
template <>
inline float env<float>(const char* key, float default_value) {
    const char* val = env(key);
    if (val == nullptr || val[0] == '\0') return default_value;
    char* end = nullptr;
    float result = strtof(val, &end);
    if (end == val || *end != '\0') return default_value;
    return result;
}

/// double specialisation: parsed with strtod.
template <>
inline double env<double>(const char* key, double default_value) {
    const char* val = env(key);
    if (val == nullptr || val[0] == '\0') return default_value;
    char* end = nullptr;
    double result = strtod(val, &end);
    if (end == val || *end != '\0') return default_value;
    return result;
}

/// bool specialisation: truthy check via env_is().
template <>
inline bool env<bool>(const char* key, bool default_value) {
    const char* val = env(key);
    if (val == nullptr) return default_value;
    return env_is(key);
}

/// const char* specialisation: raw string, nullptr if missing.
template <>
inline const char* env<const char*>(const char* key, const char* default_value) {
    const char* val = env(key);
    return (val != nullptr) ? val : default_value;
}

}  // namespace etst

// =====================================================================
// Guard macros
// =====================================================================

/// Early-return from the current test if @p key is not truthy.
/// Framework-agnostic — works with any test framework, not just doctest.
#define ETST_REQUIRE_ENV(key) \
    do { if (!etst::env_is(key)) { return; } } while (0)

/// Early-return from the current test if @p key does not equal @p expected.
/// Framework-agnostic — works with any test framework, not just doctest.
#define ETST_REQUIRE_ENV_EQ(key, expected) \
    do { \
        const char* _etst_val = etst::env(key); \
        if (!_etst_val || strcmp(_etst_val, (expected)) != 0) { return; } \
    } while (0)
