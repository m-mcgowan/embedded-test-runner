#pragma once

/**
 * @file command_args.h
 * @brief Combine accumulated ETST:ARGS payloads with a host command.
 *
 * The host sends zero or more `ETST:ARGS <payload>` lines during the configure
 * phase, then one command: `RUN`, `RUN: <inline args>`, `RUN_ALL`, or
 * `RESUME_AFTER: <test name>`. Those payloads carry the run's filters (`--ts`,
 * `--tc`) and its environment (`--env KEY=VALUE`), so dropping them silently
 * changes what a cycle does.
 *
 * Deliberately dependency-light, the same way `resume.h` is: no Arduino.h, no
 * Serial, no protocol. Templated on the string type rather than naming
 * Arduino's `String`, so it can be included before Arduino.h is — `runner.h`
 * includes it near the top, where `String` does not exist yet — and so the
 * native harness can instantiate it with its own shim. That lets
 * `tests/test_doctest_internals.cpp` exercise THIS function rather than a
 * hand-mirrored copy, which matters: this logic had no native coverage
 * precisely because it was tangled with Arduino dependencies, and a copy
 * written into the test would have matched whatever the original did, bug
 * included.
 *
 * Requires of @c Str: construction from `const char*`, `length()`,
 * `startsWith(const char*)`, `substring(size_t)`, `trim()`, `operator+=` for
 * both `const char*` and `Str`, and `operator==(const char*)`.
 *
 * Output must satisfy `apply_runner_command()`, which parses
 * `RESUME_AFTER: <test_name> [--tc ... --ts ...]` by splitting at the first
 * " --". Args therefore go AFTER the test name, never before it.
 */

#include <vector>

namespace etst {
namespace doctest {

/**
 * @brief Fold accumulated ETST:ARGS into the command the cycle will apply.
 *
 * @param command  The host command, verbatim.
 * @param args     Accumulated ETST:ARGS payloads, in arrival order.
 * @return The command with @p args folded in, or @p command unchanged when
 *         there is nothing to fold or the command takes no args.
 */
template <typename Str>
inline Str combine_command_args(const Str& command,
                                const std::vector<Str>& args) {
    if (args.empty()) return command;

    Str combined_body;
    for (const auto& arg : args) {
        if (combined_body.length() > 0) combined_body += " ";
        combined_body += arg;
    }

    if (command.startsWith("RUN:")) {
        Str inline_args = command.substring(4);
        inline_args.trim();
        if (inline_args.length() > 0) {
            combined_body += " ";
            combined_body += inline_args;
        }
        Str out("RUN: ");
        out += combined_body;
        return out;
    }

    if (command == "RUN" || command == "RUN_ALL") {
        Str out("RUN: ");
        out += combined_body;
        return out;
    }

    // RESUME_AFTER runs tests too, so it needs the args just as much — this is
    // the case that used to fall through to the passthrough below and silently
    // drop them. Args go AFTER the test name: apply_runner_command() splits
    // "RESUME_AFTER: <name> [--flags]" at the first " --", so a leading arg
    // would be parsed as the name and the real name as flags.
    if (command.startsWith("RESUME_AFTER:")) {
        Str name = command.substring(13);
        name.trim();
        if (name.length() == 0) return command;  // nothing to resume after
        Str out("RESUME_AFTER: ");
        out += name;
        out += " ";
        out += combined_body;
        return out;
    }

    // Anything else takes no args (WAIT, SLEEP acknowledgements, and whatever
    // the protocol grows next). Passing it through unchanged is deliberate: a
    // command that does not run tests has nothing to filter.
    return command;
}

}  // namespace doctest
}  // namespace etst
