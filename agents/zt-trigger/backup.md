# zt-trigger - Backup

## What to Back Up

- /srv/zt-trigger/data/memory/
- /srv/zt-trigger/data/sessions/
- /srv/zt-trigger/data/.env

## What NOT to Back Up

- Logs (regenerable)
- Cache files

## Schedule

- Daily at 02:00 via cron

## Method

```bash
tar czf /srv/backups/zt-trigger-$(date +%Y%m%d).tar.gz -C /srv/zt-trigger data/
```

## Retention

- Keep last 7 days
- Keep last 4 Sunday backups

## Restore

```bash
docker stop zt-trigger
tar xzf /srv/backups/zt-trigger-YYYYMMDD.tar.gz -C /srv/zt-trigger/
docker start zt-trigger
```
