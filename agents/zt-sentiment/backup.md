# zt-sentiment - Backup

## What to Back Up

- /srv/zt-sentiment/data/memory/
- /srv/zt-sentiment/data/sessions/
- /srv/zt-sentiment/data/.env

## What NOT to Back Up

- Logs (regenerable)
- Cache files

## Schedule

- Daily at 02:00 via cron

## Method

```bash
tar czf /srv/backups/zt-sentiment-$(date +%Y%m%d).tar.gz -C /srv/zt-sentiment data/
```

## Retention

- Keep last 7 days
- Keep last 4 Sunday backups

## Restore

```bash
docker stop zt-sentiment
tar xzf /srv/backups/zt-sentiment-YYYYMMDD.tar.gz -C /srv/zt-sentiment/
docker start zt-sentiment
```
