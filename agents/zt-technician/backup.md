# zt-technician - Backup

## What to Back Up

- /srv/zt-technician/data/memory/
- /srv/zt-technician/data/sessions/
- /srv/zt-technician/data/.env

## What NOT to Back Up

- Logs (regenerable)
- Cache files

## Schedule

- Daily at 02:00 via cron

## Method

```bash
tar czf /srv/backups/zt-technician-$(date +%Y%m%d).tar.gz -C /srv/zt-technician data/
```

## Retention

- Keep last 7 days
- Keep last 4 Sunday backups

## Restore

```bash
docker stop zt-technician
tar xzf /srv/backups/zt-technician-YYYYMMDD.tar.gz -C /srv/zt-technician/
docker start zt-technician
```
