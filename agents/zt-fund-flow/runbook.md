# zt-fund-flow - Runbook

## Startup

```bash
cd /root/agent-room
docker compose -f templates/docker/docker-compose.zt-fund-flow.yml up -d
```

## Health Check

```bash
curl -s http://127.0.0.1:8645/health || echo "UNHEALTHY"
```

## Logs

```bash
docker logs zt-fund-flow --tail 100 -f
```

## Restart

```bash
docker restart zt-fund-flow
```

## Stop

```bash
docker stop zt-fund-flow
```

## Debug

1. Check container is running: `docker ps | grep zt-fund-flow`
2. Check logs for errors: `docker logs zt-fund-flow --tail 50`
3. Check env vars loaded: `docker exec zt-fund-flow env | grep -v KEY | grep -v TOKEN`
4. Check data dir mounted: `docker exec zt-fund-flow ls /opt/data`

## Recovery

If data is corrupted:

1. Stop the container
2. Restore from latest backup
3. Restart the container
4. Verify health check passes

## Scaling

- This agent is stateless per invocation
- Can run multiple instances behind a load balancer if throughput increases
