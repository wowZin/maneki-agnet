# zt-trigger - Runbook

## Startup

```bash
cd /root/agent-room
docker compose -f templates/docker/docker-compose.zt-trigger.yml up -d
```

## Health Check

```bash
curl -s http://127.0.0.1:8642/health || echo "UNHEALTHY"
```

## Logs

```bash
docker logs zt-trigger --tail 100 -f
```

## Restart

```bash
docker restart zt-trigger
```

## Stop

```bash
docker stop zt-trigger
```

## Debug

1. Check container is running: `docker ps | grep zt-trigger`
2. Check logs for errors: `docker logs zt-trigger --tail 50`
3. Check env vars loaded: `docker exec zt-trigger env | grep -v KEY | grep -v TOKEN`
4. Check data dir mounted: `docker exec zt-trigger ls /opt/data`

## Recovery

If data is corrupted:

1. Stop the container
2. Restore from latest backup
3. Restart the container
4. Verify health check passes

## Scaling

- This agent is stateless per invocation
- Can run multiple instances behind a load balancer if throughput increases
