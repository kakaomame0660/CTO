#!/usr/bin/env bash
#
# update-agency-agents.sh -- Install / update The Agency subagents
# (https://github.com/msitarzewski/agency-agents) for Claude Code.
#
# Usage:
#   ./scripts/update-agency-agents.sh                 # all agents -> .claude/agents/ (this repo)
#   ./scripts/update-agency-agents.sh --global        # all agents -> ~/.claude/agents/ (every project)
#   ./scripts/update-agency-agents.sh --division engineering,security
#   ./scripts/update-agency-agents.sh --agent frontend-developer,code-reviewer
#   ./scripts/update-agency-agents.sh --ref <commit|tag|branch>
#
# Any other option (--division, --agent, --agents-file, --dry-run, ...) is
# passed through to upstream's scripts/install.sh.
#
# Files installed by a previous run are listed in
# .claude/agency-agents/MANIFEST and replaced on each run, so agents that
# upstream renamed or removed don't linger. Your own agents in the same
# directory are never touched.

set -euo pipefail

REPO_URL="https://github.com/msitarzewski/agency-agents.git"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
META_DIR="$REPO_ROOT/.claude/agency-agents"
DEST="$REPO_ROOT/.claude/agents"
REF=""
PASSTHROUGH=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --global) DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents"; META_DIR="$DEST/.agency-agents"; shift ;;
    --ref)    REF="${2:?--ref needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)        PASSTHROUGH+=("$1"); shift ;;
  esac
done

DRY_RUN=false
for a in "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}"; do [[ "$a" == "--dry-run" ]] && DRY_RUN=true; done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Fetching $REPO_URL ${REF:+($REF)}"
if [[ -n "$REF" ]]; then
  git clone --quiet "$REPO_URL" "$WORK/src"
  git -C "$WORK/src" checkout --quiet "$REF"
else
  git clone --quiet --depth 1 "$REPO_URL" "$WORK/src"
fi
COMMIT="$(git -C "$WORK/src" rev-parse HEAD)"

# Install into a staging dir first so a failed run leaves the current agents intact.
STAGE="$WORK/stage"
mkdir -p "$STAGE"
bash "$WORK/src/scripts/install.sh" --tool claude-code --path "$STAGE" \
  --no-interactive --no-convert "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}"

$DRY_RUN && exit 0

shopt -s nullglob
staged=("$STAGE"/*.md)
[[ ${#staged[@]} -gt 0 ]] || { echo "error: no agents were installed" >&2; exit 1; }

mkdir -p "$DEST" "$META_DIR"

# Remove what the previous run installed.
if [[ -f "$META_DIR/MANIFEST" ]]; then
  while IFS= read -r f; do
    [[ -n "$f" && "$f" != */* ]] && rm -f "$DEST/$f"
  done < "$META_DIR/MANIFEST"
fi

: > "$META_DIR/MANIFEST"
for f in "${staged[@]}"; do
  cp "$f" "$DEST/"
  basename "$f" >> "$META_DIR/MANIFEST"
done
sort -o "$META_DIR/MANIFEST" "$META_DIR/MANIFEST"

cp "$WORK/src/LICENSE" "$META_DIR/LICENSE"
cat > "$META_DIR/UPSTREAM" <<EOF
repo:   $REPO_URL
commit: $COMMIT
date:   $(git -C "$WORK/src" log -1 --format=%cs)
agents: ${#staged[@]}
EOF

echo "==> ${#staged[@]} agents installed to $DEST (upstream $COMMIT)"
