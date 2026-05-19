# Troubleshooting

## `codex` or `claude` installed but command not found

Reload shell config:

```bash
source ~/.bashrc
```

Check npm prefix:

```bash
npm config get prefix
```

Ensure `<prefix>/bin` is on `PATH`.

## Hermes installer ends with wizard error

The installer may try to enter an interactive wizard. Run `hermes` manually in a real SSH terminal.

## Docker permission issue

For root-based VPS setup, Docker should work directly. For non-root users, add the user to the Docker group and re-login.

## Git pull fails in `/root/agent-room`

Local edits may prevent fast-forward pulls. Commit, stash, or manually merge local changes.