# zt-fundamental - Runbook

## Startup

```bash
cd /root/agent-room
docker compose -f templates/docker/docker-compose.zt-fundamental.yml up -d
```

## Health Check

```bash
curl -s http://127.0.0.1:8641/health || echo "UNHEALTHY"
```

## Logs

```bash
docker logs zt-fundamental --tail 100 -f
```

## Restart

```bash
docker restart zt-fundamental
```

## Stop

```bash
docker stop zt-fundamental
```

## Debug

1. Check container is running: `docker ps | grep zt-fundamental`
2. Check logs for errors: `docker logs zt-fundamental --tail 50`
3. Check env vars loaded: `docker exec zt-fundamental env | grep -v KEY | grep -v TOKEN`
4. Check data dir mounted: `docker exec zt-fundamental ls /opt/data`

## Recovery

If data is corrupted:

1. Stop the container
2. Restore from latest backup
3. Restart the container
4. Verify health check passes

## Scaling

- This agent is stateless per invocation
- Can run multiple instances behind a load balancer if throughput increases