#pragma once

/**
 * @file command_receiver.h
 * @brief Turn the host's input lines into commands, each acted on exactly once.
 *
 * `wait_for_command()` (runner.h) reads lines from the serial port and hands
 * each one to a CommandReceiver, which says what the line was: a configuration
 * argument, the start of a transaction, a command to run, a duplicate of a
 * command already run, or something to refuse (NAK).
 *
 * Two host dialects are accepted on the same port:
 *
 * - **Legacy** (every host up to v0.3.x): zero or more `ETST:ARGS <payload>`
 *   lines, then a bare command (`RUN`, `RUN: ...`, `RESUME_AFTER: ...`, ...).
 *   There is no way to tell a resend from a new command, so none is attempted.
 *
 * - **Transactions** (`proto=2`, offered by signal_ready() in test_runner.h):
 *
 *       ETST:BEGIN id=<id> args=<n>
 *       ETST:ARGS <payload>            (n of these)
 *       ETST:CMD id=<id> <command>
 *
 *   The command runs only if the BEGIN with the same id was seen and exactly
 *   n arguments arrived after it; otherwise it is refused, and the host
 *   resends the whole transaction. An id that already ran is reported as a
 *   duplicate and not run again, so a resend can never run a command twice.
 *
 * Input noise. Bytes a third party writes to the port (a hub agent probing a
 * re-enumerated port with a bootloader SYNC frame, say) carry no newline, so
 * they are glued to the front of the host's next line. Leading bytes that
 * cannot start a command are dropped, as before, and a line that still fails
 * its CRC is tried once more from its first `ETST:`, provided the noise in
 * front of it contains no `ETST:` of its own: noise is discarded, but the
 * truncated remains of a protocol line are not, since that line's loss has to
 * be reported rather than hidden.
 *
 * Dependency-light, like command_args.h and resume.h: no Arduino.h, no Serial,
 * templated on the string type, so tests/test_doctest_internals.cpp covers the
 * real code. Works on (pointer, length) throughout: the noise can hold NULs.
 *
 * Requires of @c Str: construction from `const char*`.
 */

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <vector>

#include "etst/protocol.h"

namespace etst {
namespace doctest {

/// Longest transaction id accepted, in characters.
static constexpr size_t MAX_TXN_ID_LEN = 16;

enum class LineKind {
    Empty,      ///< nothing but whitespace
    Args,       ///< an ETST:ARGS payload, accumulated
    Begin,      ///< a transaction opened
    Command,    ///< a command to run now (with its args)
    Duplicate,  ///< a transaction that already ran: acknowledge, do not run
    Nak,        ///< refused: see LineResult::reason
};

enum class NakReason {
    None,
    Crc,         ///< the line failed its CRC (noise, or a damaged line)
    Incomplete,  ///< ETST:CMD without its BEGIN, or with arguments missing
    Malformed,   ///< ETST:BEGIN/ETST:CMD that could not be parsed
};

inline const char* nak_reason_name(NakReason r) {
    switch (r) {
    case NakReason::Crc:        return "crc";
    case NakReason::Incomplete: return "incomplete";
    case NakReason::Malformed:  return "malformed";
    case NakReason::None:       break;
    }
    return "none";
}

template <typename Str>
struct LineResult {
    LineKind kind = LineKind::Empty;
    NakReason reason = NakReason::None;
    Str command;              ///< Command: the command text (no CRC, no framing)
    std::vector<Str> args;    ///< Command: the accumulated ETST:ARGS payloads
    Str id;                   ///< Command/Duplicate/Nak: transaction id ("" if none)
    size_t noise_bytes = 0;   ///< bytes of noise discarded in front of the line
    unsigned got = 0;         ///< Nak Incomplete: arguments received
    unsigned want = 0;        ///< Nak Incomplete: arguments announced (0 if no BEGIN)
};

template <typename Str>
class CommandReceiver {
public:
    /// The device has just announced READY. Loose (legacy) arguments are
    /// dropped, as they always were, so a legacy host's resend starts clean;
    /// an open transaction keeps its own, since its BEGIN resets them.
    void on_ready() {
        if (!txn_open_) args_.clear();
    }

    /// Classify one input line (without its newline). @p len counts every
    /// byte, NULs included.
    LineResult<Str> accept(const char* line, size_t len) {
        LineResult<Str> res;

        // Trim whitespace at both ends.
        size_t begin = 0, end = len;
        while (begin < end && is_space(line[begin])) ++begin;
        while (end > begin && is_space(line[end - 1])) --end;
        if (begin == end) return res;

        // Leading bytes that cannot start a command (commands start with an
        // uppercase ASCII letter): serial-open noise, a SLIP frame's header.
        size_t start = begin;
        while (start < end && !is_upper(line[start])) ++start;
        if (start == end) start = begin;

        size_t content_len = 0;
        bool ok = check_crc(line + start, end - start, &content_len);
        if (!ok) {
            const size_t etst = find_etst(line, start, end);
            if (etst != NOT_FOUND && etst > start &&
                check_crc(line + etst, end - etst, &content_len)) {
                start = etst;
                ok = true;
            }
        }
        if (!ok) {
            reset();
            res.kind = LineKind::Nak;
            res.reason = NakReason::Crc;
            return res;
        }
        res.noise_bytes = start - begin;

        const char* c = line + start;
        const size_t n = content_len;

        if (starts_with(c, n, "ETST:ARGS ") || starts_with(c, n, "ETST:ARG ")) {
            const size_t skip = c[8] == 'S' ? 10 : 9;
            args_.push_back(make_str(c + skip, n - skip, /*trim=*/true));
            res.kind = LineKind::Args;
            return res;
        }

        if (starts_with(c, n, "ETST:BEGIN ")) {
            char id[MAX_TXN_ID_LEN + 1];
            unsigned want = 0;
            if (!field(c, n, "id=", id, sizeof(id)) || !parse_count(c, n, &want)) {
                reset();
                return nak(res, NakReason::Malformed);
            }
            args_.clear();
            txn_open_ = true;
            txn_want_ = want;
            memcpy(txn_id_, id, sizeof(id));
            res.kind = LineKind::Begin;
            return res;
        }

        if (starts_with(c, n, "ETST:CMD ")) {
            char id[MAX_TXN_ID_LEN + 1];
            const size_t id_at = 9;
            if (!starts_with(c + id_at, n - id_at, "id=")) {
                reset();
                return nak(res, NakReason::Malformed);
            }
            size_t id_end = id_at + 3;
            while (id_end < n && c[id_end] != ' ') ++id_end;
            const size_t id_len = id_end - (id_at + 3);
            size_t cmd_at = id_end;
            while (cmd_at < n && c[cmd_at] == ' ') ++cmd_at;
            if (id_len == 0 || id_len > MAX_TXN_ID_LEN ||
                !valid_id(c + id_at + 3, id_len) || cmd_at >= n) {
                reset();
                return nak(res, NakReason::Malformed);
            }
            memcpy(id, c + id_at + 3, id_len);
            id[id_len] = '\0';
            res.id = Str(id);

            if (strcmp(id, last_id_) == 0) {
                reset();
                res.kind = LineKind::Duplicate;
                return res;
            }
            const bool same_txn = txn_open_ && strcmp(id, txn_id_) == 0;
            if (!same_txn || args_.size() != txn_want_) {
                res.got = static_cast<unsigned>(args_.size());
                res.want = same_txn ? txn_want_ : 0;
                reset();
                return nak(res, NakReason::Incomplete);
            }
            memcpy(last_id_, id, id_len + 1);
            res.kind = LineKind::Command;
            res.command = make_str(c + cmd_at, n - cmd_at, /*trim=*/true);
            res.args.swap(args_);
            reset();
            return res;
        }

        // Anything else CRC-valid is a legacy command.
        res.kind = LineKind::Command;
        res.command = make_str(c, n, /*trim=*/false);
        res.args.swap(args_);
        reset();
        return res;
    }

private:
    static constexpr size_t NOT_FOUND = static_cast<size_t>(-1);

    std::vector<Str> args_;
    bool txn_open_ = false;
    unsigned txn_want_ = 0;
    char txn_id_[MAX_TXN_ID_LEN + 1] = {0};
    char last_id_[MAX_TXN_ID_LEN + 1] = {0};

    void reset() {
        args_.clear();
        txn_open_ = false;
        txn_id_[0] = '\0';
    }

    static LineResult<Str>& nak(LineResult<Str>& res, NakReason why) {
        res.kind = LineKind::Nak;
        res.reason = why;
        return res;
    }

    static bool is_space(char ch) {
        return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n';
    }
    static bool is_upper(char ch) { return ch >= 'A' && ch <= 'Z'; }

    static bool valid_id(const char* s, size_t n) {
        for (size_t i = 0; i < n; ++i) {
            const char ch = s[i];
            const bool ok = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') ||
                            (ch >= 'A' && ch <= 'Z') || ch == '-' || ch == '_';
            if (!ok) return false;
        }
        return true;
    }

    static bool starts_with(const char* s, size_t n, const char* prefix) {
        const size_t p = strlen(prefix);
        return n >= p && memcmp(s, prefix, p) == 0;
    }

    /// First "ETST:" in line[from, to), or NOT_FOUND. memcmp, not strstr:
    /// the noise in front can hold NULs.
    static size_t find_etst(const char* line, size_t from, size_t to) {
        for (size_t i = from; i + 5 <= to; ++i) {
            if (memcmp(line + i, "ETST:", 5) == 0) return i;
        }
        return NOT_FOUND;
    }

    /// `CONTENT *XX` with a matching CRC-8 of CONTENT.
    static bool check_crc(const char* s, size_t n, size_t* content_len) {
        if (n < 5 || s[n - 4] != ' ' || s[n - 3] != '*') return false;
        int received = 0;
        for (size_t i = n - 2; i < n; ++i) {
            const char ch = s[i];
            int v;
            if (ch >= '0' && ch <= '9') v = ch - '0';
            else if (ch >= 'A' && ch <= 'F') v = ch - 'A' + 10;
            else if (ch >= 'a' && ch <= 'f') v = ch - 'a' + 10;
            else return false;
            received = received * 16 + v;
        }
        *content_len = n - 4;
        return etst::crc8(reinterpret_cast<const uint8_t*>(s), n - 4) ==
               static_cast<uint8_t>(received);
    }

    /// The value of `key` (e.g. "id=") among space-separated tokens.
    static bool field(const char* s, size_t n, const char* key, char* out, size_t out_size) {
        const size_t k = strlen(key);
        size_t i = 0;
        while (i < n) {
            while (i < n && s[i] == ' ') ++i;
            size_t j = i;
            while (j < n && s[j] != ' ') ++j;
            if (j - i > k && memcmp(s + i, key, k) == 0) {
                const size_t len = j - i - k;
                if (len >= out_size || !valid_id(s + i + k, len)) return false;
                memcpy(out, s + i + k, len);
                out[len] = '\0';
                return true;
            }
            i = j;
        }
        return false;
    }

    static bool parse_count(const char* s, size_t n, unsigned* out) {
        char digits[8];
        if (!field(s, n, "args=", digits, sizeof(digits))) return false;
        unsigned v = 0;
        for (const char* p = digits; *p; ++p) {
            if (*p < '0' || *p > '9') return false;
            v = v * 10 + static_cast<unsigned>(*p - '0');
        }
        *out = v;
        return true;
    }

    static Str make_str(const char* s, size_t n, bool trim) {
        if (trim) {
            while (n > 0 && is_space(*s)) { ++s; --n; }
            while (n > 0 && is_space(s[n - 1])) --n;
        }
        char buf[etst::MAX_LINE_LEN + 1];
        if (n > etst::MAX_LINE_LEN) n = etst::MAX_LINE_LEN;
        memcpy(buf, s, n);
        buf[n] = '\0';
        return Str(buf);
    }
};

}  // namespace doctest
}  // namespace etst
