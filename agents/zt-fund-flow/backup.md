# zt-fund-flow - Backup

## What to Back Up

- /srv/zt-fund-flow/data/memory/
- /srv/zt-fund-flow/data/sessions/
- /srv/zt-fund-flow/data/.env

## What NOT to Back Up

- Logs (regenerable)
- Cache files

## Schedule

- Daily at 02:00 via cron

## Method

```bash
tar czf /srv/backups/zt-fund-flow-$(date +%Y%m%d).tar.gz -C /srv/zt-fund-flow data/
```

## Retention

- Keep last 7 days
- Keep last 4 Sunday backups

## Restore

```bash
docker stop zt-fund-flow
tar xzf /srv/backups/zt-fund-flow-YYYYMMDD.tar.gz -C /srv/zt-fund-flow/
docker start zt-fund-flow
```
