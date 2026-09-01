/**
 * @file resume.h
 * @brief Resume-point selection over doctest's test registry.
 *
 * Deliberately dependency-light: doctest, `<algorithm>`, `<cstring>` and
 * `<vector>` only. No `<Arduino.h>`, no ESP headers, no `Serial`. That is the
 * whole point of the file — the selection logic here is the part that can be
 * wrong, and keeping it free of the Arduino surface is what lets the native
 * harness (`tests/test_doctest_internals.cpp`, built and run in CI) exercise
 * the real code rather than a copy of it.
 *
 * `runner.h` includes this and wraps `select_resume_after()` with the protocol
 * logging. Nothing here prints.
 *
 * Note the namespace: these live in `etst::doctest`, which shadows the global
 * `doctest`, so every reference to the library is spelled `::doctest::` — the
 * pattern the rest of the header set already uses.
 */

#pragma once

#include <doctest.h>

#include <algorithm>
#include <cstring>
#include <vector>

namespace etst::doctest {

/**
 * @brief Registered tests in doctest execution order (file, then line).
 *
 * Matches doctest's default `order_by="file"`, i.e. its `fileOrderComparator`,
 * so index N here is the same test the host sees at index N in `ETST:LIST`.
 */
inline std::vector<const ::doctest::detail::TestCase*> sorted_registry() {
    // Collect pointers to sort — same approach doctest uses internally
    std::vector<const ::doctest::detail::TestCase*> tests;
    for (const auto& tc : ::doctest::detail::getRegisteredTests()) {
        tests.push_back(&tc);
    }
    // Sort by file then line (matches doctest's fileOrderComparator)
    std::sort(tests.begin(), tests.end(),
        [](const ::doctest::detail::TestCase* a, const ::doctest::detail::TestCase* b) {
            const int res = a->m_file.compare(b->m_file);
            if (res != 0) return res < 0;
            return a->m_line < b->m_line;
        });
    return tests;
}

/**
 * @brief Mark every test up to and including `test_name` as already run.
 *
 * Force-skips the completed prefix by setting `m_skip`, in the same
 * (file, line) order the host sees via `ETST:LIST`. O(1) extra memory — no
 * exclude string, which could exhaust heap with 700+ test names.
 *
 * Uses `m_skip` rather than doctest's `first` option, because `first` is an
 * *index into the tests that pass filters* (doctest compares it against
 * `numTestCasesPassingFilters`), whereas a registry index counts every
 * registered test. Any skipped or filtered-out test before the resume point
 * made those two spaces diverge, so `first` was set too high and silently
 * dropped that many tests after the resume point — compounding across
 * sleep/wake cycles until whole suites never ran. Marking `m_skip` sidesteps
 * index arithmetic entirely and lets doctest's own filter chain do the
 * counting, so it also composes correctly with filters and env requirements
 * applied after this call.
 *
 * `m_skip` is not part of the registry's set ordering, so the `const_cast` is
 * safe — the same approach `modify_skip()` already uses.
 *
 * @param test_name  Exact name of the last completed test.
 * @return Number of tests marked skipped, or -1 if `test_name` was not found
 *         (in which case nothing is modified and every test should run).
 */
inline int select_resume_after(const char* test_name) {
    auto tests = sorted_registry();

    int resume_idx = -1;
    for (size_t i = 0; i < tests.size(); ++i) {
        if (std::strcmp(tests[i]->m_name, test_name) == 0) {
            resume_idx = static_cast<int>(i);
            break;
        }
    }
    if (resume_idx < 0) return -1;

    for (int i = 0; i <= resume_idx; ++i) {
        const_cast< ::doctest::detail::TestCase*>(tests[i])->m_skip = true;
    }
    return resume_idx + 1;
}

}  // namespace etst::doctest
