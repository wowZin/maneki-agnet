# zt-technician - Docker

## Image

Base: hermes-agent:latest

## Compose File

`templates/docker/docker-compose.zt-technician.yml`

## Volumes

| Host | Container | Purpose |
|---|---|---|
| /srv/zt-technician/data | /opt/data | Runtime state |
| /root/agent-room/skills | /opt/skills:ro | Shared skills (read-only) |

## Network

- Port 8643: Gateway/API (localhost only)
- Port 9120: Dashboard (localhost only)

## Resource Limits

- Memory: 512MB
- CPU: 0.5

## Restart Policy

unless-stopped
