# zt-sentiment - Runbook

## Startup

```bash
cd /root/agent-room
docker compose -f templates/docker/docker-compose.zt-sentiment.yml up -d
```

## Health Check

```bash
curl -s http://127.0.0.1:8646/health || echo "UNHEALTHY"
```

## Logs

```bash
docker logs zt-sentiment --tail 100 -f
```

## Restart

```bash
docker restart zt-sentiment
```

## Stop

```bash
docker stop zt-sentiment
```

## Debug

1. Check container is running: `docker ps | grep zt-sentiment`
2. Check logs for errors: `docker logs zt-sentiment --tail 50`
3. Check env vars loaded: `docker exec zt-sentiment env | grep -v KEY | grep -v TOKEN`
4. Check data dir mounted: `docker exec zt-sentiment ls /opt/data`

## Recovery

If data is corrupted:

1. Stop the container
2. Restore from latest backup
3. Restart the container
4. Verify health check passes

## Scaling

- This agent is stateless per invocation
- Can run multiple instances behind a load balancer if throughput increases
