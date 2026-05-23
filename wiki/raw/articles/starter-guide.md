# Starter Guide

This template is Control Room first.

Recommended order:

```text
1. Create a VPS or choose an existing one.
2. Bootstrap the Agent Control Room.
3. Register one Hermes agent.
4. Add direct specialist agents when roles become clear.
5. Add an orchestrator when you want one front door.
6. Automate only after the manual workflow works.
```

## Step 1: Create Or Choose A VPS

Use any Ubuntu/Debian server you can SSH into.

Recommended starting point:

- Ubuntu 24.04 LTS
- 2 vCPU / 4GB RAM minimum
- 4 vCPU / 8GB RAM if running several agents, browser automation, or heavier crons
- SSH key access

If you are provisioning on Hetzner, use the bundled `create-vps` skill to create the VPS, SSH key, and local SSH alias before this template is installed.

## Step 2: Bootstrap The Control Room

On the VPS, clone this repo:

```bash
git clone https://github.com/shannhk/hermes-agent-control-room.git /root/agent-control-room
```

Then install the tools you want on the VPS:

- Node.js
- Claude Code
- Codex CLI
- Docker
- Hermes Agent

The bundled `setup-control-room` skill describes an automated bootstrap flow for this.

If you are starting from nothing, the paired flow is:

```text
create-vps
  -> creates the server and SSH alias

setup-control-room
  -> installs tooling and clones this template
```

## Step 3: Register One Agent

Copy the agent template:

```bash
mkdir -p /root/agent-control-room/agents/hermes-life
cp /root/agent-control-room/templates/agent/*.md /root/agent-control-room/agents/hermes-life/
```

Edit the five docs:

```text
inventory.md
docker.md
env-map.md
runbook.md
backup.md
```

Do not put raw secrets in these files.

## Step 4: Add Direct Specialists

Once one agent works, add specialists only when the role is clear.

Examples:

```text
hermes-seo
hermes-dev
hermes-cmo
hermes-ops
```

Each specialist should have its own Docker container, data dir, memory, skills, credentials, and docs folder.

## Step 5: Add An Orchestrator

Add an orchestrator only when it is annoying to remember which specialist to ask.

The orchestrator should follow the Control Room. It should not become a giant agent with every credential.

## Step 6: Automate Later

Do not start with automation.

First prove the manual workflow:

```text
You -> specialist
You -> orchestrator -> specialist
```

Then add recurring workflows, security audits, backup checks, and task routing.
