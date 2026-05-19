# zt-fundamental - Docker

## Image

Base: hermes-agent:latest

## Compose File

`templates/docker/docker-compose.zt-fundamental.yml`

## Volumes

| Host | Container | Purpose |
|---|---|---|
| /srv/zt-fundamental/data | /opt/data | Runtime state |
| /root/agent-room/skills | /opt/skills:ro | Shared skills (read-only) |

## Network

- Port 8641: Gateway/API (localhost only)
- Port 9118: Dashboard (localhost only)

## Resource Limits

- Memory: 512MB
- CPU: 0.5

## Restart Policy

unless-stopped