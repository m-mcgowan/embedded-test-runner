#pragma once

/**
 * @file filter_flags.h
 * @brief Coalesce repeated filter flags before doctest parses them.
 *
 * doctest resolves an option by scanning argv backwards: parseOptionImpl's own
 * comment reads "going from the end to the beginning and stopping on the first
 * occurrence from the end". So a repeated `--ts=` does not accumulate — the
 * last one wins and every earlier one is discarded without a word.
 *
 * That matters because a filter can be too long for one protocol line. The
 * device reads at most `MAX_LINE_LEN` (256) bytes per line, so a long `--ts`
 * has to arrive as several `ETST:ARGS` lines, and the host folds those back
 * into a single command — `RUN: --ts A,B --ts C`. Handed to doctest unchanged
 * that run would cover `C` alone, and look like it had worked.
 *
 * There is a second reason beyond the filter being wrong. `FilterState`
 * captures every `--ts` it sees while doctest honours only the last, so the
 * two would describe different sets of tests, `count_passing_filters()` would
 * disagree with what actually ran, and the run would trip the under-run
 * detection on top of silently filtering wrongly. Coalescing before either one
 * looks at argv keeps the count and the run talking about the same thing.
 *
 * Long and short spellings fold together because doctest routes them to one
 * filter slot: `--ts=` and `--test-suite=` are the same filter, and so are
 * `--tc=`/`--test-case=`, `--tse=`/`--test-suite-exclude=`, and
 * `--tce=`/`--test-case-exclude=`. Order is preserved: a coalesced flag stays
 * where the first of its kind appeared, and anything else is left untouched.
 *
 * Dependency-light like `resume.h`, `command_args.h` and `command_kind.h`: no
 * Arduino.h, no Serial, templated on the string type, so the native harness
 * exercises this function rather than a copy of it.
 *
 * Requires of @c Str: construction from `const char*`, `c_str()`, `length()`,
 * `startsWith(const char*)`, `substring(size_t)`, and `operator+=`.
 */

#include <vector>
#include <cstring>

namespace etst {
namespace doctest {

/// @brief The doctest filter slots. Long and short spellings share one slot.
struct FilterFlagAlias {
    const char* canonical;  ///< Spelling to emit for the coalesced flag.
    const char* alias;      ///< The other spelling doctest accepts.
};

/// @brief Fold repeated filter flags in @p argv into one flag per filter.
///
/// `{"test", "--ts=A,B", "--ts=C"}` becomes `{"test", "--ts=A,B,C"}`.
/// Non-filter entries, and filters that appear once, are left alone.
template <typename Str>
inline void coalesce_repeated_filter_flags(std::vector<Str>& argv) {
    static const FilterFlagAlias kFilters[] = {
        {"--ts=",  "--test-suite="},
        {"--tc=",  "--test-case="},
        {"--tse=", "--test-suite-exclude="},
        {"--tce=", "--test-case-exclude="},
    };

    for (const auto& filter : kFilters) {
        int first = -1;      // where the coalesced flag will live
        Str values;
        bool seen_any = false;
        bool seen_more_than_one = false;

        for (size_t i = 0; i < argv.size(); i++) {
            const char* prefix = nullptr;
            if (argv[i].startsWith(filter.canonical))  prefix = filter.canonical;
            else if (argv[i].startsWith(filter.alias)) prefix = filter.alias;
            if (!prefix) continue;

            Str value = argv[i].substring(std::strlen(prefix));
            if (value.length() == 0) continue;  // "--ts=" with nothing after it

            if (!seen_any) {
                first = static_cast<int>(i);
                values = value;
                seen_any = true;
            } else {
                values += ",";
                values += value;
                seen_more_than_one = true;
            }
        }

        if (!seen_more_than_one) continue;  // nothing to fold

        // Rebuild: the coalesced flag keeps the position of the first
        // occurrence, and the later ones are dropped.
        Str combined(filter.canonical);
        combined += values;

        std::vector<Str> rebuilt;
        rebuilt.reserve(argv.size());
        for (size_t i = 0; i < argv.size(); i++) {
            if (static_cast<int>(i) == first) {
                rebuilt.push_back(combined);
                continue;
            }
            if (argv[i].startsWith(filter.canonical)
                    || argv[i].startsWith(filter.alias)) {
                Str value = argv[i].substring(
                    argv[i].startsWith(filter.canonical)
                        ? std::strlen(filter.canonical)
                        : std::strlen(filter.alias));
                if (value.length() > 0) continue;  // folded into `combined`
            }
            rebuilt.push_back(argv[i]);
        }
        argv.swap(rebuilt);
    }
}

}  // namespace doctest
}  // namespace etst
