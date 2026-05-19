# API Keys SOP

Use this SOP when adding, rotating, or documenting credentials for an agent.

## Rules

- Never commit raw secrets.
- Never paste API keys into Control Room docs.
- Prefer one named key per agent per provider.
- Prefer least privilege.
- Record where a key lives, not the value.
- Treat any key pasted into chat as needing rotation.

## Naming

Use names like:

```text
<agent-name>:<purpose>
```

Examples:

```text
hermes-seo:github
hermes-dev:deploy
hermes-ops:monitoring
```

## Add Or Rotate A Key

1. Create the new key in the provider dashboard.
2. Store it in the correct runtime secret store, usually:

```text
/srv/<agent-name>/data/.env
```

3. Restart the agent if required.
4. Verify the integration works.
5. Revoke the old key.
6. Update:

```text
agents/<agent-name>/env-map.md
```

## What To Record In `env-map.md`

Safe:

- env var name
- provider
- purpose
- scope
- storage location
- rotation date

Unsafe:

- API key value
- OAuth refresh token
- password
- private key
- raw `.env` content
