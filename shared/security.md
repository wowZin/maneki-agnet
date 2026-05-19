# Shared Security Checklist

Use this checklist for the VPS and all agents.

## VPS

- [ ] SSH key auth works.
- [ ] Password SSH is disabled or intentionally allowed.
- [ ] Firewall is enabled.
- [ ] Public dashboard/API ports are intentionally exposed, or bound to localhost.
- [ ] Docker is installed and running.
- [ ] Automatic updates are considered.

## Agent Containers

- [ ] One container per long-running agent.
- [ ] Each agent has its own `/srv/<agent-name>/data`.
- [ ] No two gateway processes use the same data dir.
- [ ] Host ports are unique.
- [ ] Runtime `.env` files are not committed.
- [ ] Backups exclude secrets.

## Control Room

- [ ] No raw secrets in `agents/`, `docs/`, `shared/`, `templates/`, or `examples/`.
- [ ] Every agent has `inventory.md`, `docker.md`, `env-map.md`, `runbook.md`, and `backup.md`.
- [ ] `env-map.md` records secret locations and scopes only.
- [ ] Runbooks explain restart, upgrade, restore, and key rotation.

## Key Rotation

Rotate any key that was:

- pasted into chat
- committed by mistake
- shared too broadly
- scoped too broadly
- used by an agent that no longer needs it
