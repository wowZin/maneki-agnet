# zt-team-leader - Backup

## What to Back Up

- /srv/zt-team-leader/data/memory/
- /srv/zt-team-leader/data/sessions/
- /srv/zt-team-leader/data/.env

## What NOT to Back Up

- Logs (regenerable)
- Cache files

## Schedule

- Daily at 02:00 via cron

## Method

```bash
tar czf /srv/backups/zt-team-leader-$(date +%Y%m%d).tar.gz -C /srv/zt-team-leader data/
```

## Retention

- Keep last 7 days
- Keep last 4 Sunday backups

## Restore

```bash
docker stop zt-team-leader
tar xzf /srv/backups/zt-team-leader-YYYYMMDD.tar.gz -C /srv/zt-team-leader/
docker start zt-team-leader
```
