# Env Guide

The local `.env` file stores Hetzner provisioning settings.

Do not commit it.

Required values:

```text
HCLOUD_TOKEN
SERVER_NAME
SERVER_TYPE
SERVER_IMAGE
SERVER_LOCATION
SSH_KEY_NAME
SSH_KEY_FILE
SSH_ALIAS
```

`SERVER_HOST` is filled after the server is created.

Create the token in Hetzner Cloud Console:

```text
Project -> Security -> API Tokens -> Generate API Token
```

Permission: Read & Write.

Never paste the token into chat.