#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Missing .env"
  exit 1
fi

set -a
. ./.env
set +a

if [ -z "${HCLOUD_TOKEN:-}" ] || [ -z "${SERVER_NAME:-}" ]; then
  echo "Missing HCLOUD_TOKEN or SERVER_NAME"
  exit 1
fi

echo "This will delete Hetzner server: $SERVER_NAME"
read -r -p "Type DELETE to continue: " confirm

if [ "$confirm" != "DELETE" ]; then
  echo "Aborted"
  exit 1
fi

hcloud server delete "$SERVER_NAME"
