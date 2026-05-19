#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

AGENT_ROOM_PATH="${AGENT_ROOM_PATH:-/root/agent-room}"
AGENT_ROOM_REPO="${AGENT_ROOM_REPO:-https://github.com/shannhk/maneki-agent.git}"

log() {
  printf '\n==> %s\n' "$*"
}

log "Installing base packages"
apt-get update -qq
apt-get install -y --no-install-recommends curl ca-certificates git tmux htop

log "Installing Node.js 22 if needed"
NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -v | sed 's/^v\([0-9][0-9]*\).*/\1/')"
fi

if [ "$NODE_MAJOR" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

log "Installing Claude Code if needed"
if ! command -v claude >/dev/null 2>&1; then
  npm install -g @anthropic-ai/claude-code
fi

log "Installing Codex CLI if needed"
if ! command -v codex >/dev/null 2>&1; then
  npm install -g @openai/codex
fi

log "Ensuring npm global bin is on PATH"
NPM_BIN="$(npm config get prefix)/bin"
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$NPM_BIN"; then
  if ! grep -Fq "$NPM_BIN" "$HOME/.bashrc" 2>/dev/null; then
    printf '\nexport PATH=%s:$PATH\n' "$NPM_BIN" >> "$HOME/.bashrc"
  fi
  export PATH="$NPM_BIN:$PATH"
fi

log "Installing Docker if needed"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

log "Installing Hermes Agent best-effort if needed"
if ! command -v hermes >/dev/null 2>&1 && [ ! -d /usr/local/lib/hermes-agent ] && [ ! -d "$HOME/.hermes/hermes-agent" ]; then
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash || true
fi

log "Cloning or updating Agent Room"
if [ ! -d "$AGENT_ROOM_PATH/.git" ]; then
  git clone "$AGENT_ROOM_REPO" "$AGENT_ROOM_PATH"
else
  git -C "$AGENT_ROOM_PATH" pull --ff-only
fi

log "Linking bundled skills into Claude skills directory"
mkdir -p "$HOME/.claude/skills"
for skill_dir in "$AGENT_ROOM_PATH"/skills/*/; do
  [ -d "$skill_dir" ] || continue
  skill_name="$(basename "$skill_dir")"
  target="$HOME/.claude/skills/$skill_name"
  [ -e "$target" ] || ln -s "$skill_dir" "$target"
done

log "Installed versions"
printf 'node:   %s\n' "$(node --version 2>&1 || true)"
printf 'npm:    %s\n' "$(npm --version 2>&1 || true)"
printf 'claude: %s\n' "$(claude --version 2>&1 || echo 'installed; auth may still be needed')"
printf 'codex:  %s\n' "$(codex --version 2>&1 || echo 'installed; auth may still be needed')"
printf 'docker: %s\n' "$(docker --version 2>&1 || true)"
printf 'hermes: %s\n' "$(command -v hermes >/dev/null 2>&1 && hermes --version 2>&1 || echo 'install may need interactive completion')"
printf 'repo:   %s\n' "$(git -C "$AGENT_ROOM_PATH" remote get-url origin 2>&1 || true)"
printf 'skills: %s linked\n' "$(find "$HOME/.claude/skills" -maxdepth 1 -mindepth 1 -type l | wc -l)"

log "Next steps"
cat <<'EOF'
Open a real SSH terminal and finish auth:

  claude /login
  codex
  hermes

Then:

  cd /root/agent-room
  cat README.md
EOF