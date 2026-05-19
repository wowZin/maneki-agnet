# zt-fund-flow - Docker

## Image

Base: hermes-agent:latest

## Compose File

`templates/docker/docker-compose.zt-fund-flow.yml`

## Volumes

| Host | Container | Purpose |
|---|---|---|
| /srv/zt-fund-flow/data | /opt/data | Runtime state |
| /root/agent-room/skills | /opt/skills:ro | Shared skills (read-only) |

## Network

- Port 8645: Gateway/API (localhost only)
- Port 9122: Dashboard (localhost only)

## Resource Limits

- Memory: 512MB
- CPU: 0.5

## Restart Policy

unless-stopped
