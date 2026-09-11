/**
 * @file test_doctest_internals.cpp
 * @brief Native tests verifying doctest internal assumptions.
 *
 * These tests run on the host (not on hardware) and verify:
 * - m_skip is writable on registered test cases
 * - modifying m_skip does not break std::set ordering
 * - glob_match works correctly
 * - tokenize_args handles quoting and whitespace
 * - RESUME_AFTER selects exactly the completed prefix, and does NOT drop tests
 *   after the resume point when skip-attributed tests precede it (the
 *   index-space defect); these exercise the real resume.h, not a copy
 *
 * Build and run (from tests/ directory). `-I../include` is required so the
 * resume tests can include the real etst/doctest/resume.h:
 *   c++ -std=c++17 -Iintegration/.pio/libdeps/esp32s3/doctest/doctest \
 *       -I../include test_doctest_internals.cpp -o test_doctest_internals
 *   ./test_doctest_internals
 */

// We need DOCTEST_CONFIG_IMPLEMENT to access getRegisteredTests()
#define DOCTEST_CONFIG_IMPLEMENT
#include <doctest.h>

// The REAL production resume selection, not a copy. resume.h is deliberately
// free of Arduino/ESP dependencies so this harness can include it; everything
// else in this file has to mirror runner.h by hand. Must come after the
// DOCTEST_CONFIG_IMPLEMENT include above, since it uses getRegisteredTests().
#include <etst/doctest/resume.h>

#include <utility>
#include <vector>

// Stub Arduino String class for host builds
#ifndef ARDUINO
#include <string>
class String {
    std::string s_;
public:
    String() = default;
    String(const char* c) : s_(c) {}
    String(const std::string& s) : s_(s) {}
    const char* c_str() const { return s_.c_str(); }
    size_t length() const { return s_.size(); }
    bool startsWith(const char* prefix) const {
        return s_.compare(0, strlen(prefix), prefix) == 0;
    }
    char operator[](size_t i) const { return s_[i]; }
    String substring(size_t from, size_t to) const {
        return String(s_.substr(from, to - from));
    }
    String substring(size_t from) const {
        return String(s_.substr(from));
    }
    void trim() {
        size_t start = s_.find_first_not_of(" \t\r\n");
        size_t end = s_.find_last_not_of(" \t\r\n");
        if (start == std::string::npos) { s_.clear(); return; }
        s_ = s_.substr(start, end - start + 1);
    }
    String& operator+=(char c) { s_ += c; return *this; }
    String& operator+=(const char* s) { s_ += s; return *this; }
    // Real Arduino String has these; command_args.h uses them.
    String& operator+=(const String& o) { s_ += o.s_; return *this; }
    int indexOf(const char* needle) const {
        size_t p = s_.find(needle);
        return p == std::string::npos ? -1 : (int)p;
    }
    bool operator==(const String& other) const { return s_ == other.s_; }
    friend bool operator==(const String& a, const char* b) { return a.s_ == b; }
};

// Stub Serial for host builds
struct SerialStub {
    template<typename... Args>
    void printf(const char*, Args...) {}
    void println(const char*) {}
};
static SerialStub Serial;
#endif

// The REAL production arg/command folding, not a copy — same reasoning as
// resume.h above. It only needs the String shim, which is defined by now.
#include <etst/doctest/command_args.h>

// Now include our header (needs String and Serial stubs above)
// We only include the functions we need, not the full runner
namespace etst::doctest {

// Copy glob_match and tokenize_args from doctest_runner.h
// (can't include the full header without Arduino.h)

inline bool glob_match(const char* str, const char* pattern) {
    const char* cp = nullptr;
    const char* mp = nullptr;
    while (*str && *pattern != '*') {
        if (*pattern != *str && *pattern != '?') return false;
        pattern++;
        str++;
    }
    while (*str) {
        if (*pattern == '*') {
            if (!*++pattern) return true;
            mp = pattern;
            cp = str + 1;
        } else if (*pattern == *str || *pattern == '?') {
            pattern++;
            str++;
        } else {
            pattern = mp;
            str = cp++;
        }
    }
    while (*pattern == '*') pattern++;
    return !*pattern;
}

inline std::vector<String> tokenize_args(const String& body) {
    std::vector<String> args;
    size_t i = 0;
    while (i < body.length()) {
        while (i < body.length() && body[i] == ' ') i++;
        if (i >= body.length()) break;
        String arg;
        if (body[i] == '"' || body[i] == '\'') {
            char quote = body[i++];
            while (i < body.length() && body[i] != quote) {
                arg += body[i++];
            }
            if (i < body.length()) i++;
        } else {
            while (i < body.length() && body[i] != ' ') {
                arg += body[i++];
            }
        }
        if (arg.length() > 0) {
            args.push_back(arg);
        }
    }
    return args;
}

inline int modify_skip(const char* pattern, bool match_suite, bool skip_value) {
    int count = 0;
    for (auto& tc : ::doctest::detail::getRegisteredTests()) {
        const char* name = match_suite ? tc.m_test_suite : tc.m_name;
        if (name && glob_match(name, pattern)) {
            const_cast<::doctest::detail::TestCase&>(tc).m_skip = skip_value;
            count++;
        }
    }
    return count;
}

}  // namespace etst::doctest

// =========================================================================
// Tests
// =========================================================================

TEST_SUITE("glob_match") {

TEST_CASE("exact match") {
    CHECK(etst::doctest::glob_match("hello", "hello"));
    CHECK_FALSE(etst::doctest::glob_match("hello", "world"));
}

TEST_CASE("star wildcard") {
    CHECK(etst::doctest::glob_match("hello world", "*world"));
    CHECK(etst::doctest::glob_match("hello world", "hello*"));
    CHECK(etst::doctest::glob_match("hello world", "*lo wo*"));
    CHECK(etst::doctest::glob_match("hello world", "*"));
    CHECK_FALSE(etst::doctest::glob_match("hello world", "*xyz*"));
}

TEST_CASE("question mark wildcard") {
    CHECK(etst::doctest::glob_match("cat", "c?t"));
    CHECK_FALSE(etst::doctest::glob_match("cart", "c?t"));
}

TEST_CASE("combined wildcards") {
    CHECK(etst::doctest::glob_match("Service/WDT", "*WDT*"));
    CHECK(etst::doctest::glob_match("Service/WDT", "Service/*"));
    CHECK(etst::doctest::glob_match("join feeds WDT during slow cleanup", "*WDT*slow*"));
}

TEST_CASE("empty strings") {
    CHECK(etst::doctest::glob_match("", ""));
    CHECK(etst::doctest::glob_match("", "*"));
    CHECK_FALSE(etst::doctest::glob_match("", "a"));
    CHECK_FALSE(etst::doctest::glob_match("a", ""));
}

}  // TEST_SUITE glob_match

TEST_SUITE("tokenize_args") {

TEST_CASE("simple flags") {
    auto args = etst::doctest::tokenize_args("--tc *foo* --ts *bar*");
    REQUIRE(args.size() == 4);
    CHECK(args[0] == "--tc");
    CHECK(args[1] == "*foo*");
    CHECK(args[2] == "--ts");
    CHECK(args[3] == "*bar*");
}

TEST_CASE("quoted values") {
    auto args = etst::doctest::tokenize_args("--tc \"hello world\"");
    REQUIRE(args.size() == 2);
    CHECK(args[0] == "--tc");
    CHECK(args[1] == "hello world");
}

TEST_CASE("single flag") {
    auto args = etst::doctest::tokenize_args("--no-skip");
    REQUIRE(args.size() == 1);
    CHECK(args[0] == "--no-skip");
}

TEST_CASE("empty string") {
    auto args = etst::doctest::tokenize_args("");
    CHECK(args.size() == 0);
}

TEST_CASE("extra whitespace") {
    auto args = etst::doctest::tokenize_args("  --tc   *foo*  ");
    REQUIRE(args.size() == 2);
    CHECK(args[0] == "--tc");
    CHECK(args[1] == "*foo*");
}

}  // TEST_SUITE tokenize_args

// =========================================================================
// build_doctest_argv — flag=value joining for applyCommandLine
// =========================================================================

namespace etst::doctest {

inline std::vector<String> build_doctest_argv(const std::vector<String>& args) {
    std::vector<String> result;
    result.push_back("test");
    for (size_t i = 0; i < args.size(); i++) {
        if (args[i].startsWith("--") && i + 1 < args.size()
                && !args[i + 1].startsWith("--")) {
            String combined;
            combined += args[i].c_str();
            combined += "=";
            combined += args[i + 1].c_str();
            result.push_back(combined);
            i++;
        } else {
            result.push_back(args[i]);
        }
    }
    return result;
}

}  // namespace etst::doctest

TEST_SUITE("build_doctest_argv") {

TEST_CASE("flag and value joined with =") {
    auto args = etst::doctest::tokenize_args("--tc *foo*");
    auto argv = etst::doctest::build_doctest_argv(args);
    REQUIRE(argv.size() == 2);
    CHECK(argv[0] == "test");
    CHECK(argv[1] == "--tc=*foo*");
}

TEST_CASE("standalone flag preserved") {
    auto args = etst::doctest::tokenize_args("--no-skip");
    auto argv = etst::doctest::build_doctest_argv(args);
    REQUIRE(argv.size() == 2);
    CHECK(argv[0] == "test");
    CHECK(argv[1] == "--no-skip");
}

TEST_CASE("multiple flags joined independently") {
    auto args = etst::doctest::tokenize_args("--tc *a* --ts *b*");
    auto argv = etst::doctest::build_doctest_argv(args);
    REQUIRE(argv.size() == 3);
    CHECK(argv[0] == "test");
    CHECK(argv[1] == "--tc=*a*");
    CHECK(argv[2] == "--ts=*b*");
}

TEST_CASE("already-joined flag=value preserved") {
    auto args = etst::doctest::tokenize_args("--tc=*foo*");
    auto argv = etst::doctest::build_doctest_argv(args);
    REQUIRE(argv.size() == 2);
    CHECK(argv[0] == "test");
    CHECK(argv[1] == "--tc=*foo*");
}

TEST_CASE("mixed standalone and value flags") {
    auto args = etst::doctest::tokenize_args("--no-skip --tc *foo* --tse *slow*");
    auto argv = etst::doctest::build_doctest_argv(args);
    REQUIRE(argv.size() == 4);
    CHECK(argv[0] == "test");
    CHECK(argv[1] == "--no-skip");
    CHECK(argv[2] == "--tc=*foo*");
    CHECK(argv[3] == "--tse=*slow*");
}

TEST_CASE("empty args produces only program name") {
    std::vector<String> args;
    auto argv = etst::doctest::build_doctest_argv(args);
    REQUIRE(argv.size() == 1);
    CHECK(argv[0] == "test");
}

}  // TEST_SUITE build_doctest_argv

// Skip-decorated targets for modify_skip tests
TEST_CASE("_target_skip_A" * doctest::skip()) { FAIL("should not run"); }
TEST_CASE("_target_skip_B" * doctest::skip()) { FAIL("should not run"); }

TEST_SUITE("modify_skip") {

TEST_CASE("unskip clears m_skip") {
    // Find target_A and verify it starts skipped
    bool found = false;
    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_target_skip_A") == 0) {
            CHECK(tc.m_skip == true);
            found = true;
            break;
        }
    }
    REQUIRE(found);

    int count = etst::doctest::modify_skip("*_target_skip_A*", false, false);
    CHECK(count == 1);

    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_target_skip_A") == 0) {
            CHECK(tc.m_skip == false);
            break;
        }
    }

    // Restore
    etst::doctest::modify_skip("*_target_skip_A*", false, true);
}

TEST_CASE("pattern only affects matching tests") {
    etst::doctest::modify_skip("*_target_skip_A*", false, false);

    bool a_skip = true, b_skip = false;
    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_target_skip_A") == 0) a_skip = tc.m_skip;
        if (strcmp(tc.m_name, "_target_skip_B") == 0) b_skip = tc.m_skip;
    }
    CHECK_FALSE(a_skip);  // unskipped
    CHECK(b_skip);         // still skipped

    etst::doctest::modify_skip("*_target_skip_A*", false, true);
}

TEST_CASE("set ordering preserved after modification") {
    // Modify m_skip and verify the set is still iterable and consistent
    etst::doctest::modify_skip("*_target_skip_A*", false, false);
    etst::doctest::modify_skip("*_target_skip_A*", false, true);

    // Iterate the full set — if ordering is broken, this would crash
    // or produce duplicate/missing entries
    size_t count = 0;
    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        REQUIRE(tc.m_name != nullptr);
        count++;
    }
    CHECK(count > 5);  // we have at least our test cases + targets
}

TEST_CASE("force-skip sets m_skip on non-skipped test") {
    // Find a non-skipped test
    const char* target = nullptr;
    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (!tc.m_skip && strcmp(tc.m_name, "_target_skip_A") != 0
                       && strcmp(tc.m_name, "_target_skip_B") != 0) {
            target = tc.m_name;
            break;
        }
    }
    REQUIRE(target != nullptr);

    etst::doctest::modify_skip(target, false, true);
    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, target) == 0) {
            CHECK(tc.m_skip == true);
            break;
        }
    }

    // Restore
    etst::doctest::modify_skip(target, false, false);
}

}  // TEST_SUITE modify_skip

// =========================================================================
// extract_etst_flags — argument-order processing
// =========================================================================

// Replicate extract_etst_flags for native testing (uses our local String/Serial stubs)
namespace etst::doctest {

inline void extract_etst_flags(std::vector<String>& args) {
    struct { const char* flag; bool match_suite; bool skip_value; } etst_flags[] = {
        {"--unskip-tc", false, false},
        {"--unskip-ts", true,  false},
        {"--skip-tc",   false, true},
        {"--skip-ts",   true,  true},
    };

    for (size_t i = 0; i < args.size(); ) {
        bool matched = false;
        for (auto& pf : etst_flags) {
            if (args[i] == pf.flag && i + 1 < args.size()) {
                const char* pattern = args[i + 1].c_str();
                modify_skip(pattern, pf.match_suite, pf.skip_value);
                args.erase(args.begin() + i, args.begin() + i + 2);
                matched = true;
                break;
            }
        }
        if (!matched) i++;
    }
}

}  // namespace etst::doctest

// Non-skipped target for ordering tests
TEST_CASE("_target_ordering" * doctest::skip()) { FAIL("should not run"); }

TEST_SUITE("extract_etst_flags") {

TEST_CASE("unskip then skip: last flag wins") {
    // Start: _target_ordering is skipped (decorator)
    // Apply: --unskip-tc first, then --skip-tc
    // Expected: skipped (skip-tc is last)
    auto args = etst::doctest::tokenize_args("--unskip-tc *_target_ordering* --skip-tc *_target_ordering*");
    etst::doctest::extract_etst_flags(args);

    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_target_ordering") == 0) {
            CHECK(tc.m_skip == true);  // skip was last
            break;
        }
    }
    // Already in correct state (skipped), no restore needed
}

TEST_CASE("skip then unskip: last flag wins") {
    // Apply: --skip-tc first, then --unskip-tc
    // Expected: unskipped (unskip-tc is last)
    auto args = etst::doctest::tokenize_args("--skip-tc *_target_ordering* --unskip-tc *_target_ordering*");
    etst::doctest::extract_etst_flags(args);

    for (const auto& tc : doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_target_ordering") == 0) {
            CHECK(tc.m_skip == false);  // unskip was last
            break;
        }
    }
    // Restore
    etst::doctest::modify_skip("*_target_ordering*", false, true);
}

TEST_CASE("non-ptr flags are preserved in args") {
    auto args = etst::doctest::tokenize_args("--unskip-tc *_target_ordering* --tc *foo* --no-skip");
    etst::doctest::extract_etst_flags(args);

    // --unskip-tc + value removed, --tc *foo* and --no-skip remain
    REQUIRE(args.size() == 3);
    CHECK(args[0] == "--tc");
    CHECK(args[1] == "*foo*");
    CHECK(args[2] == "--no-skip");

    // Restore
    etst::doctest::modify_skip("*_target_ordering*", false, true);
}

TEST_CASE("mixed skip and doctest flags preserve order") {
    auto args = etst::doctest::tokenize_args("--ts *Suite* --unskip-tc *_target_ordering* --tce *exclude*");
    etst::doctest::extract_etst_flags(args);

    // Only --unskip-tc removed, doctest flags preserved in order
    REQUIRE(args.size() == 4);
    CHECK(args[0] == "--ts");
    CHECK(args[1] == "*Suite*");
    CHECK(args[2] == "--tce");
    CHECK(args[3] == "*exclude*");

    // Restore
    etst::doctest::modify_skip("*_target_ordering*", false, true);
}

}  // TEST_SUITE extract_etst_flags

// ─────────────────────────────────────────────────────────────────────────────
// RESUME_AFTER selection
//
// Unlike everything above, these exercise the REAL production code: resume.h is
// dependency-light on purpose (doctest + <algorithm>/<cstring>/<vector>, no
// Arduino, no ESP, no Serial), so it is included rather than copied. The rest of
// this file mirrors runner.h by hand, which is a drift risk these tests avoid.
//
// What is under test is the SELECTION — which tests a resume excludes. That is
// exactly where the defect lived: apply_resume_after() used to compute an index
// over ALL registered tests and hand it to doctest's "first" option, which is an
// index over tests that PASS FILTERS (compared against
// numTestCasesPassingFilters). Every skip-attributed or filtered-out test before
// the resume point made those two spaces diverge, pushing "first" too high and
// silently dropping that many tests AFTER the resume point — compounding across
// sleep/wake cycles until whole suites never ran, while the run reported PASSED.
// ─────────────────────────────────────────────────────────────────────────────

// Fixture cases, in declaration order == (file, line) order == registry order.
// The two skip-attributed cases sit BEFORE the resume point deliberately: that
// is the precise condition under which the two index spaces diverge. Without
// them these tests would pass against the old buggy implementation too.
TEST_CASE("_resume_before")                        { /* fixture */ }
TEST_CASE("_resume_skipped_a" * doctest::skip())   { FAIL("should not run"); }
TEST_CASE("_resume_skipped_b" * doctest::skip())   { FAIL("should not run"); }
TEST_CASE("_resume_point")                         { /* fixture */ }
TEST_CASE("_resume_after_1")                       { /* fixture */ }
TEST_CASE("_resume_after_2")                       { /* fixture */ }

TEST_SUITE("resume_after") {

// select_resume_after() mutates m_skip on the live registry, which would
// otherwise change which of THIS harness's own tests run afterwards. Snapshot
// and restore around every call.
using SkipSnapshot = std::vector<std::pair<const ::doctest::detail::TestCase*, bool>>;

static SkipSnapshot snapshot_skips() {
    SkipSnapshot s;
    for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
        s.emplace_back(&tc, tc.m_skip);
    }
    return s;
}

static void restore_skips(const SkipSnapshot& s) {
    for (const auto& entry : s) {
        const_cast< ::doctest::detail::TestCase*>(entry.first)->m_skip = entry.second;
    }
}

static int index_of(const char* name) {
    auto tests = etst::doctest::sorted_registry();
    for (size_t i = 0; i < tests.size(); ++i) {
        if (strcmp(tests[i]->m_name, name) == 0) return static_cast<int>(i);
    }
    return -1;
}

TEST_CASE("the fixture actually reproduces the index-space divergence") {
    // A guard on the tests below, not a property of the production code. If a
    // future edit moves or unskips the fixture cases, the regression tests would
    // silently stop testing the thing that broke — this fails loudly instead.
    const int before  = index_of("_resume_before");
    const int skipped = index_of("_resume_skipped_a");
    const int point   = index_of("_resume_point");
    REQUIRE(before >= 0);
    REQUIRE(skipped > before);
    REQUIRE(point > skipped);

    // Count how many tests up to and including the resume point doctest would
    // count toward numTestCasesPassingFilters (i.e. are not skip-attributed).
    auto tests = etst::doctest::sorted_registry();
    int runnable_prefix = 0;
    for (int i = 0; i <= point; ++i) {
        if (!tests[i]->m_skip) runnable_prefix++;
    }

    // The two spaces MUST disagree here, by exactly the number of
    // skip-attributed cases in the prefix. This difference is what the old
    // `first`-based implementation added to the boundary, dropping that many
    // tests after the resume point.
    const int registry_prefix = point + 1;
    CHECK(runnable_prefix < registry_prefix);
    CHECK(registry_prefix - runnable_prefix >= 2);
}

TEST_CASE("resume skips exactly the completed prefix") {
    auto saved = snapshot_skips();
    const int point = index_of("_resume_point");
    REQUIRE(point >= 0);

    const int skipped = etst::doctest::select_resume_after("_resume_point");
    CHECK(skipped == point + 1);

    auto tests = etst::doctest::sorted_registry();
    bool prefix_all_skipped = true;
    for (int i = 0; i <= point; ++i) {
        if (!tests[i]->m_skip) prefix_all_skipped = false;
    }
    CHECK(prefix_all_skipped);

    restore_skips(saved);
}

TEST_CASE("tests after the resume point still run despite skipped tests before it") {
    // THE REGRESSION. Under the old `first`-based selection the boundary landed
    // two positions too far (one per skip-attributed fixture case above), so
    // these two would have been excluded and never reported.
    auto saved = snapshot_skips();

    const bool before_1 = [] {
        for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
            if (strcmp(tc.m_name, "_resume_after_1") == 0) return (bool)tc.m_skip;
        }
        return true;
    }();
    REQUIRE_FALSE(before_1);   // fixture sanity: it is runnable to begin with

    etst::doctest::select_resume_after("_resume_point");

    bool after_1_skipped = true, after_2_skipped = true;
    for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_resume_after_1") == 0) after_1_skipped = tc.m_skip;
        if (strcmp(tc.m_name, "_resume_after_2") == 0) after_2_skipped = tc.m_skip;
    }
    CHECK_FALSE(after_1_skipped);
    CHECK_FALSE(after_2_skipped);

    restore_skips(saved);
}

TEST_CASE("resume leaves already-skipped tests after the point alone") {
    // Resuming must not resurrect a doctest::skip()-attributed test that
    // happens to sit after the resume point — it only marks the prefix.
    auto saved = snapshot_skips();

    etst::doctest::select_resume_after("_resume_before");

    bool a_skipped = false, b_skipped = false;
    for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
        if (strcmp(tc.m_name, "_resume_skipped_a") == 0) a_skipped = tc.m_skip;
        if (strcmp(tc.m_name, "_resume_skipped_b") == 0) b_skipped = tc.m_skip;
    }
    CHECK(a_skipped);
    CHECK(b_skipped);

    restore_skips(saved);
}

TEST_CASE("an unknown resume point changes nothing and reports -1") {
    // The host must be able to tell "resume point vanished" from "resumed at 0",
    // and a not-found name must not skip anything — the device runs everything.
    auto saved = snapshot_skips();

    size_t skipped_before = 0;
    for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
        if (tc.m_skip) skipped_before++;
    }

    CHECK(etst::doctest::select_resume_after("_no_such_test_name") == -1);

    size_t skipped_after = 0;
    for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
        if (tc.m_skip) skipped_after++;
    }
    CHECK(skipped_after == skipped_before);

    restore_skips(saved);
}

TEST_CASE("sorted_registry is in (file, line) order and stable") {
    // The host addresses tests by index via ETST:LIST, so this ordering is a
    // wire contract, not an implementation detail.
    auto a = etst::doctest::sorted_registry();
    auto b = etst::doctest::sorted_registry();
    REQUIRE(a.size() == b.size());

    bool identical = true;
    for (size_t i = 0; i < a.size(); ++i) {
        if (a[i] != b[i]) identical = false;
    }
    CHECK(identical);

    bool ordered = true;
    for (size_t i = 1; i < a.size(); ++i) {
        const int cmp = a[i - 1]->m_file.compare(a[i]->m_file);
        if (cmp > 0) ordered = false;
        else if (cmp == 0 && a[i - 1]->m_line > a[i]->m_line) ordered = false;
    }
    CHECK(ordered);
}

}  // TEST_SUITE resume_after

int main(int argc, char** argv) {
    doctest::Context context;
    context.setOption("no-skip", false);  // don't run skip targets
    context.applyCommandLine(argc, argv);
    return context.run();
}

// ─────────────────────────────────────────────────────────────────────────────
// ETST:ARGS folding — accumulated args must reach EVERY command that runs tests
//
// Regression cover for a silent coverage defect measured on ESP32-S3 hardware:
// args were folded into RUN/RUN_ALL/RUN: but NOT into RESUME_AFTER:. Every
// deep-sleep test forces a resume cycle, so the first cycle honoured the run's
// filters and environment and every later one ran without them. The suite
// still exited green, because a test that skips counts as a test that passed.
// ─────────────────────────────────────────────────────────────────────────────

TEST_SUITE("command args folding") {

using etst::doctest::combine_command_args;

TEST_CASE("no args leaves the command untouched") {
    CHECK(combine_command_args(String("RUN"), {}) == "RUN");
    CHECK(combine_command_args(String("RESUME_AFTER: some test"), {}) ==
          "RESUME_AFTER: some test");
}

TEST_CASE("bare RUN becomes RUN: with the args") {
    std::vector<String> args{String("--env BENCH_POSE=right_side")};
    CHECK(combine_command_args(String("RUN"), args) ==
          "RUN: --env BENCH_POSE=right_side");
}

TEST_CASE("RUN_ALL becomes RUN: with the args") {
    std::vector<String> args{String("--ts *Orientation*")};
    CHECK(combine_command_args(String("RUN_ALL"), args) ==
          "RUN: --ts *Orientation*");
}

TEST_CASE("RUN: keeps its inline args as well as the accumulated ones") {
    std::vector<String> args{String("--env BENCH_POSE=right_side")};
    String out = combine_command_args(String("RUN: --tc *foo*"), args);
    CHECK(out.indexOf("--env BENCH_POSE=right_side") >= 0);
    CHECK(out.indexOf("--tc *foo*") >= 0);
}

TEST_CASE("multiple accumulated args are space-joined in arrival order") {
    std::vector<String> args{String("--env BENCH_POSE=right_side"),
                             String("--ts *Orientation*")};
    CHECK(combine_command_args(String("RUN"), args) ==
          "RUN: --env BENCH_POSE=right_side --ts *Orientation*");
}

// The defect. Each of these failed before the fix.
TEST_CASE("RESUME_AFTER receives the accumulated args") {
    std::vector<String> args{String("--env BENCH_POSE=right_side")};
    String out = combine_command_args(String("RESUME_AFTER: ULP boot_counter survives deep sleep"), args);
    CHECK_MESSAGE(out.indexOf("--env BENCH_POSE=right_side") >= 0,
        "args dropped on the resume path: every cycle after the first deep "
        "sleep would run without the run's environment");
}

TEST_CASE("RESUME_AFTER keeps the test name, and keeps it ahead of the args") {
    // apply_runner_command() splits "RESUME_AFTER: <name> [--flags]" at the
    // FIRST " --", so the name has to come first or it is parsed as flags.
    std::vector<String> args{String("--env BENCH_POSE=right_side")};
    String out = combine_command_args(String("RESUME_AFTER: ULP boot_counter survives deep sleep"), args);
    CHECK(out.startsWith("RESUME_AFTER: ULP boot_counter survives deep sleep"));
    int name_pos = out.indexOf("ULP boot_counter survives deep sleep");
    int flag_pos = out.indexOf(" --");
    CHECK(name_pos >= 0);
    CHECK(flag_pos > name_pos);
}

TEST_CASE("RESUME_AFTER receives filters too, not just env") {
    std::vector<String> args{String("--ts *Orientation*")};
    String out = combine_command_args(String("RESUME_AFTER: a test"), args);
    CHECK_MESSAGE(out.indexOf("--ts *Orientation*") >= 0,
        "filters dropped on the resume path: resumed segments would run "
        "unfiltered, reporting far more cases than were requested");
}

TEST_CASE("an unrecognised command is passed through unchanged") {
    std::vector<String> args{String("--env X=1")};
    CHECK(combine_command_args(String("WAIT"), args) == "WAIT");
}

}  // TEST_SUITE
