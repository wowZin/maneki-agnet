# Shared Commands

Common commands for operating a VPS-based Agent Control Room.

## Docker

```bash
docker ps
docker logs <container> --tail 100
docker logs -f <container>
docker exec -it <container> bash
docker compose -f /srv/<agent-name>/docker-compose.yml up -d
docker compose -f /srv/<agent-name>/docker-compose.yml restart
docker compose -f /srv/<agent-name>/docker-compose.yml pull
```

## Agent Control Room

```bash
cd /root/agent-control-room
git status
git pull --ff-only
find agents -maxdepth 2 -type f | sort
```

## Runtime Folders

```bash
ls -la /srv
ls -la /srv/<agent-name>/data
```

## Ports

```bash
ss -ltnp
```

## SSH

```bash
ssh <alias>
ssh -o ConnectTimeout=10 <alias> 'echo ok'
```
