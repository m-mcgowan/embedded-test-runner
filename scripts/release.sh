#!/usr/bin/env bash
#
# Release both embedded-bridge and pio-test-runner.
#
# Usage:
#   scripts/release.sh <version>        # e.g. scripts/release.sh 0.2.0
#   scripts/release.sh -n <version>     # dry run — print what would happen
#
# Prerequisites:
#   - Both repos clean, on main, up to date with origin
#   - CHANGELOG.md [Unreleased] section has content in both repos
#   - gh CLI authenticated
#
# The script releases embedded-bridge first (pio-test-runner depends on it),
# then pio-test-runner.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PTR_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EB_DIR="$(cd "$PTR_DIR/../embedded-bridge" && pwd)"
DRY_RUN=false
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

# --- Argument parsing -------------------------------------------------------

if [[ "${1:-}" == "-n" ]]; then
    DRY_RUN=true
    shift
fi

VERSION="${1:-}"
[[ -n "$VERSION" ]] || die "Usage: scripts/release.sh [-n] <version>"
TAG="v${VERSION}"

# --- Preflight checks -------------------------------------------------------

info "Preflight checks"

# gh CLI
command -v gh >/dev/null 2>&1 || die "gh CLI not found"
gh auth status >/dev/null 2>&1 || die "gh CLI not authenticated — run 'gh auth login'"

check_repo() {
    local dir="$1" name="$2"
    step "Checking $name ($dir)"

    [[ -d "$dir/.git" ]] || die "$name: not a git repo"

    local branch
    branch="$(git -C "$dir" branch --show-current)"
    [[ "$branch" == "main" ]] || die "$name: on branch '$branch', expected 'main'"

    local status
    status="$(git -C "$dir" diff --stat HEAD)"
    [[ -z "$status" ]] || die "$name: uncommitted changes:\n$status"

    git -C "$dir" fetch origin --quiet
    local behind
    behind="$(git -C "$dir" rev-list HEAD..origin/main --count)"
    [[ "$behind" == "0" ]] || die "$name: $behind commits behind origin/main"

    local ahead
    ahead="$(git -C "$dir" rev-list origin/main..HEAD --count)"
    [[ "$ahead" == "0" ]] || die "$name: $ahead unpushed commits"

    # Tag must not already exist
    if git -C "$dir" tag -l "$TAG" | grep -q "$TAG"; then
        die "$name: tag $TAG already exists"
    fi

    # CHANGELOG.md must have content under [Unreleased]
    [[ -f "$dir/CHANGELOG.md" ]] || die "$name: CHANGELOG.md not found"
    local unreleased_content
    unreleased_content="$(sed -n '/^## \[Unreleased\]/,/^## \[/{/^## \[/d;p;}' "$dir/CHANGELOG.md" | grep -v '^$' || true)"
    [[ -n "$unreleased_content" ]] || die "$name: CHANGELOG.md [Unreleased] section is empty"

    # library.json must exist
    [[ -f "$dir/library.json" ]] || die "$name: library.json not found"
}

check_repo "$EB_DIR"  "embedded-bridge"
check_repo "$PTR_DIR" "pio-test-runner"

info "Preflight OK"

# --- Release a single repo --------------------------------------------------

release_repo() {
    local dir="$1" name="$2"

    info "Releasing $name $TAG"

    # 1. Update library.json version
    step "Updating library.json version to $VERSION"
    if ! $DRY_RUN; then
        # Use python for reliable JSON editing
        python3 -c "
import json, sys
path = '$dir/library.json'
with open(path) as f:
    data = json.load(f)
data['version'] = '$VERSION'
with open(path, 'w') as f:
    json.dump(data, f, indent=4)
    f.write('\n')
"
    fi

    # 2. Update CHANGELOG.md — replace [Unreleased] header with versioned one
    step "Updating CHANGELOG.md"
    if ! $DRY_RUN; then
        sed -i '' "s/^## \[Unreleased\]/## [Unreleased]\n\n## [$VERSION] — $TODAY/" "$dir/CHANGELOG.md"
    fi

    # 3. Extract release notes (content between version header and next ## heading)
    local notes_file
    notes_file="$(mktemp)"
    sed -n "/^## \[$VERSION\]/,/^## \[/{/^## \[/d;p;}" "$dir/CHANGELOG.md" \
        | sed '1{/^$/d;}' | sed '${/^$/d;}' > "$notes_file"

    # 4. Commit
    step "Committing version bump"
    run git -C "$dir" add CHANGELOG.md library.json
    if ! $DRY_RUN; then
        git -C "$dir" commit -m "release: $TAG"
    fi

    # 5. Tag
    step "Creating tag $TAG"
    run git -C "$dir" tag -a "$TAG" -m "$TAG"

    # 6. Push
    step "Pushing to origin"
    run git -C "$dir" push origin main
    run git -C "$dir" push origin "$TAG"

    # 7. GitHub release
    step "Creating GitHub release"
    run gh release create "$TAG" \
        --repo "$(git -C "$dir" remote get-url origin | sed 's/\.git$//')" \
        --title "$TAG" \
        --notes-file "$notes_file"

    rm -f "$notes_file"
}

# --- Execute ----------------------------------------------------------------

release_repo "$EB_DIR"  "embedded-bridge"
release_repo "$PTR_DIR" "pio-test-runner"

info "Done! Released $TAG for both repos."
echo ""
echo "  embedded-bridge:  https://github.com/m-mcgowan/embedded-bridge/releases/tag/$TAG"
echo "  pio-test-runner:  https://github.com/m-mcgowan/pio-test-runner/releases/tag/$TAG"
