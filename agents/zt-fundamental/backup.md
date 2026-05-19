# zt-fundamental - Backup

## What to Back Up

- /srv/zt-fundamental/data/memory/
- /srv/zt-fundamental/data/sessions/
- /srv/zt-fundamental/data/.env

## What NOT to Back Up

- Logs (regenerable)
- Cache files

## Schedule

- Daily at 02:00 via cron

## Method

```bash
tar czf /srv/backups/zt-fundamental-$(date +%Y%m%d).tar.gz -C /srv/zt-fundamental data/
```

## Retention

- Keep last 7 days
- Keep last 4 Sunday backups

## Restore

```bash
docker stop zt-fundamental
tar xzf /srv/backups/zt-fundamental-YYYYMMDD.tar.gz -C /srv/zt-fundamental/
docker start zt-fundamental
```