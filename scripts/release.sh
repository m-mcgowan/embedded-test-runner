#!/usr/bin/env bash
#
# Release one repo: version bump, CHANGELOG promotion, tag, push, GH release.
#
# Usage:
#   scripts/release.sh <version>              # e.g. scripts/release.sh 0.3.2
#   scripts/release.sh -n <version>           # dry run — print what would happen
#   scripts/release.sh --no-push <version>    # bump + commit + tag locally only
#   scripts/release.sh --repo ../embedded-bridge <version>
#
# Options:
#   -n, --dry-run       Print each step without changing anything.
#       --no-push       Do the local work (bump, commit, tag) but skip the push
#                       and the GitHub release. Prints the commands to finish.
#       --repo <dir>    Repo to release. Defaults to this script's own repo
#                       (pio-test-runner).
#
# Each repo carries its own version — they are NOT released in lockstep.
#
# pio-test-runner depends on embedded-bridge, so releasing pio-test-runner also
# checks that embedded-bridge has nothing unreleased. A bridge with no commits
# since its own last release tag is skipped silently — the common case, where
# all the changes were local to this repo. Unreleased bridge commits stop the
# release, because a pio-test-runner tag would then pin a bridge that no
# release describes: release embedded-bridge first
# (--repo ../embedded-bridge), then pio-test-runner.
#
# Prerequisites:
#   - Target repo clean, on main, in sync with origin/main
#   - CHANGELOG.md [Unreleased] section has content
#   - gh CLI authenticated (not needed with --no-push)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SELF_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
DRY_RUN=false
NO_PUSH=false
REPO_DIR=""
TODAY="$(date +%Y-%m-%d)"

# --- Helpers ----------------------------------------------------------------

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
step() { echo "  -> $*"; }

run() {
    if $DRY_RUN; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

usage() {
    sed -n '3,32p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-1}"
}

# --- Argument parsing -------------------------------------------------------

VERSION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--dry-run) DRY_RUN=true; shift ;;
        --no-push)    NO_PUSH=true; shift ;;
        --repo)       REPO_DIR="${2:-}"; [[ -n "$REPO_DIR" ]] || die "--repo needs a directory"; shift 2 ;;
        -h|--help)    usage 0 ;;
        -*)           die "Unknown option: $1" ;;
        *)            [[ -z "$VERSION" ]] || die "Unexpected argument: $1"; VERSION="$1"; shift ;;
    esac
done

[[ -n "$VERSION" ]] || usage
TAG="v${VERSION}"

REPO_DIR="${REPO_DIR:-$SELF_REPO}"
[[ -d "$REPO_DIR" ]] || die "No such directory: $REPO_DIR"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
REPO_NAME="$(basename "$REPO_DIR")"

# --- Preflight checks -------------------------------------------------------

info "Preflight checks — $REPO_NAME $TAG"

if ! $NO_PUSH; then
    command -v gh >/dev/null 2>&1 || die "gh CLI not found (use --no-push to release locally)"
    gh auth status >/dev/null 2>&1 || die "gh CLI not authenticated — run 'gh auth login'"
fi

[[ -d "$REPO_DIR/.git" ]] || die "$REPO_NAME: not a git repo"

BRANCH="$(git -C "$REPO_DIR" branch --show-current)"
[[ "$BRANCH" == "main" ]] || die "$REPO_NAME: on branch '$BRANCH', expected 'main'"

DIRTY="$(git -C "$REPO_DIR" diff --stat HEAD)"
[[ -z "$DIRTY" ]] || die "$REPO_NAME: uncommitted changes:
$DIRTY"

git -C "$REPO_DIR" fetch origin --quiet
BEHIND="$(git -C "$REPO_DIR" rev-list HEAD..origin/main --count)"
[[ "$BEHIND" == "0" ]] || die "$REPO_NAME: $BEHIND commits behind origin/main"

# Unpushed commits are only a problem if we are about to publish: --no-push
# leaves the release commit unpushed by design, so any commits already
# waiting to go out will ride along with it.
if ! $NO_PUSH; then
    AHEAD="$(git -C "$REPO_DIR" rev-list origin/main..HEAD --count)"
    [[ "$AHEAD" == "0" ]] || die "$REPO_NAME: $AHEAD unpushed commits"
fi

if git -C "$REPO_DIR" tag -l "$TAG" | grep -q "^${TAG}$"; then
    die "$REPO_NAME: tag $TAG already exists"
fi

[[ -f "$REPO_DIR/CHANGELOG.md" ]] || die "$REPO_NAME: CHANGELOG.md not found"
UNRELEASED="$(sed -n '/^## \[Unreleased\]/,/^## \[/{/^## \[/d;p;}' "$REPO_DIR/CHANGELOG.md" | grep -v '^$' || true)"
[[ -n "$UNRELEASED" ]] || die "$REPO_NAME: CHANGELOG.md [Unreleased] section is empty"

[[ -f "$REPO_DIR/library.json" ]] || die "$REPO_NAME: library.json not found"

# pio-test-runner depends on embedded-bridge. If the bridge sitting alongside
# us has commits past its own last release tag, they would ship inside this
# release undescribed by any bridge release. Silence is the expected outcome:
# no bridge checkout, or a bridge already fully released, says nothing.
check_bridge_released() {
    local dir="$SELF_REPO/../embedded-bridge"
    [[ -d "$dir/.git" ]] || return 0
    dir="$(cd "$dir" && pwd)"

    git -C "$dir" fetch origin --quiet 2>/dev/null || return 0

    local last_tag
    last_tag="$(git -C "$dir" tag -l 'v*' --sort=-creatordate | head -n1)"
    [[ -n "$last_tag" ]] || return 0

    local unreleased
    unreleased="$(git -C "$dir" rev-list "${last_tag}..origin/main" --count)"
    [[ "$unreleased" != "0" ]] || return 0

    die "embedded-bridge: $unreleased commit(s) since $last_tag are unreleased.
     Release embedded-bridge first:
       scripts/release.sh --repo $dir <bridge-version>
     Then release this repo."
}

if [[ "$REPO_DIR" == "$SELF_REPO" ]]; then
    check_bridge_released
fi

info "Preflight OK"

# --- Release ----------------------------------------------------------------

info "Releasing $REPO_NAME $TAG"

step "Updating library.json version to $VERSION"
if ! $DRY_RUN; then
    # Use python for reliable JSON editing
    python3 -c "
import json
path = '$REPO_DIR/library.json'
with open(path) as f:
    data = json.load(f)
data['version'] = '$VERSION'
with open(path, 'w') as f:
    json.dump(data, f, indent=4)
    f.write('\n')
"
fi

step "Updating CHANGELOG.md"
if ! $DRY_RUN; then
    sed -i '' "s/^## \[Unreleased\]/## [Unreleased]\n\n## [$VERSION] — $TODAY/" "$REPO_DIR/CHANGELOG.md"
fi

# Release notes: content between the version header and the next ## heading.
NOTES_FILE="$(mktemp)"
trap 'rm -f "$NOTES_FILE"' EXIT
sed -n "/^## \[$VERSION\]/,/^## \[/{/^## \[/d;p;}" "$REPO_DIR/CHANGELOG.md" \
    | sed '1{/^$/d;}' | sed '${/^$/d;}' > "$NOTES_FILE"

step "Committing version bump"
run git -C "$REPO_DIR" add CHANGELOG.md library.json
if ! $DRY_RUN; then
    git -C "$REPO_DIR" commit -m "release: $TAG"
fi

step "Creating tag $TAG"
run git -C "$REPO_DIR" tag -a "$TAG" -m "$TAG"

REMOTE_URL="$(git -C "$REPO_DIR" remote get-url origin | sed 's/\.git$//')"

if $NO_PUSH; then
    info "Stopping before push (--no-push)"
    echo ""
    echo "  $REPO_NAME $TAG is committed and tagged locally. To publish:"
    echo ""
    echo "    git -C $REPO_DIR push origin main"
    echo "    git -C $REPO_DIR push origin $TAG"
    echo "    gh release create $TAG --repo $REMOTE_URL --title $TAG --notes-file <notes>"
    echo ""
    echo "  Release notes are in the CHANGELOG under [$VERSION]."
    exit 0
fi

step "Pushing to origin"
run git -C "$REPO_DIR" push origin main
run git -C "$REPO_DIR" push origin "$TAG"

step "Creating GitHub release"
run gh release create "$TAG" \
    --repo "$REMOTE_URL" \
    --title "$TAG" \
    --notes-file "$NOTES_FILE"

info "Done! Released $REPO_NAME $TAG"
echo ""
echo "  $REMOTE_URL/releases/tag/$TAG"
