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

required_vars="HCLOUD_TOKEN SERVER_NAME SERVER_TYPE SERVER_IMAGE SERVER_LOCATION SSH_KEY_NAME SSH_KEY_FILE SSH_ALIAS"
for var in $required_vars; do
  if [ -z "${!var:-}" ]; then
    echo "Missing $var in .env"
    exit 1
  fi
done

mkdir -p "$(dirname "$SSH_KEY_FILE")"

if [ ! -f "$SSH_KEY_FILE" ]; then
  ssh-keygen -t ed25519 -f "$SSH_KEY_FILE" -N "" -C "$SSH_KEY_NAME"
fi

if ! hcloud ssh-key describe "$SSH_KEY_NAME" >/dev/null 2>&1; then
  hcloud ssh-key create --name "$SSH_KEY_NAME" --public-key-from-file "$SSH_KEY_FILE.pub"
fi

if ! hcloud server describe "$SERVER_NAME" >/dev/null 2>&1; then
  hcloud server create \
    --name "$SERVER_NAME" \
    --type "$SERVER_TYPE" \
    --image "$SERVER_IMAGE" \
    --location "$SERVER_LOCATION" \
    --ssh-key "$SSH_KEY_NAME"
fi

SERVER_HOST="$(hcloud server ip "$SERVER_NAME")"

if grep -q '^SERVER_HOST=' .env; then
  sed -i.bak "s|^SERVER_HOST=.*|SERVER_HOST=$SERVER_HOST|" .env
else
  printf '\nSERVER_HOST=%s\n' "$SERVER_HOST" >> .env
fi
rm -f .env.bak

mkdir -p "$HOME/.ssh"
touch "$HOME/.ssh/config"
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/config"

TMP_CONFIG="$(mktemp)"
awk -v alias="$SSH_ALIAS" '
  BEGIN { skip=0 }
  /^Host / {
    if ($2 == alias) { skip=1; next }
    skip=0
  }
  skip == 0 { print }
' "$HOME/.ssh/config" > "$TMP_CONFIG"

cat >> "$TMP_CONFIG" <<EOF

Host $SSH_ALIAS
    HostName $SERVER_HOST
    User root
    IdentityFile $SSH_KEY_FILE
    Port 22
EOF

mv "$TMP_CONFIG" "$HOME/.ssh/config"
chmod 600 "$HOME/.ssh/config"

echo "Done. Connect with: ssh $SSH_ALIAS"
