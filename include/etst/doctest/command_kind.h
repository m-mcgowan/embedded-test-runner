#pragma once

/**
 * @file command_kind.h
 * @brief Classify a host command, so an unrecognised one never starts a run.
 *
 * `apply_runner_command()` used to end with "unknown runner command — using
 * compiled-in filters" and run the whole suite. That is the most destructive
 * possible reading of a command the device does not understand, and it bit us:
 * a case called `esp_restart()`, the port never dropped (USB-Serial-JTAG stays
 * enumerated across a software reset), and the host's end-of-run `WAIT`
 * arrived as the rebooted device's FIRST command. `WAIT` was known only to the
 * idle loop, so it fell through and the device ran every test unfiltered
 * instead of idling. The run then lost most of its tests.
 *
 * The host no longer sends that command, but a device should not depend on
 * what a host sends it, so the two halves are fixed separately.
 *
 * @c Absent is kept distinct from @c Unknown on purpose. No command at all
 * means no host is attached and the device runs its compiled-in filters, which
 * is how a board runs standalone. Collapsing the two would break that.
 *
 * Note @c "RUN" among the run commands: it had no branch of its own and
 * reached the test run *through* the unknown fall-through, so tightening that
 * fall-through without naming it here would have stopped runs altogether.
 *
 * Dependency-light in the same way as `resume.h` and `command_args.h`: no
 * Arduino.h, no Serial, no protocol, and templated on the string type rather
 * than naming Arduino's `String` — `runner.h` includes it near the top, before
 * `String` exists, and the native harness instantiates it with its own shim so
 * `tests/test_doctest_internals.cpp` exercises THIS code rather than a copy.
 *
 * Requires of @c Str: `length()`, `startsWith(const char*)`, and
 * `operator==(const char*)`.
 */

namespace etst {
namespace doctest {

/// @brief What a host command asks the device to do.
enum class CommandKind {
    Absent,   ///< No command: no host attached, run the compiled-in filters.
    Run,      ///< RUN, RUN_ALL, "RUN: <filters>", "RESUME_AFTER: <name>".
    List,     ///< LIST: answered without running anything.
    Idle,     ///< WAIT, SLEEP, LIGHTSLEEP, RESTART: the idle loop owns these.
    Unknown,  ///< Anything else. Never a reason to run tests.
};

/// @brief Classify @p command. See @ref CommandKind.
template <typename Str>
inline CommandKind classify_command(const Str& command) {
    if (command.length() == 0) return CommandKind::Absent;

    if (command == "RUN" || command == "RUN_ALL"
        || command.startsWith("RUN:") || command.startsWith("RESUME_AFTER:")) {
        return CommandKind::Run;
    }
    if (command == "LIST") return CommandKind::List;
    if (command == "WAIT" || command == "SLEEP"
        || command == "LIGHTSLEEP" || command == "RESTART") {
        return CommandKind::Idle;
    }
    return CommandKind::Unknown;
}

/// @brief Whether a command of this kind should start a test run.
inline bool kind_starts_a_run(CommandKind kind) {
    return kind == CommandKind::Absent || kind == CommandKind::Run;
}

/// @brief Whether @p command should start a test run.
template <typename Str>
inline bool command_starts_a_run(const Str& command) {
    return kind_starts_a_run(classify_command(command));
}

}  // namespace doctest
}  // namespace etst
