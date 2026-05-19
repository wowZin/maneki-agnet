# Auth Guide

The setup skill installs tools but does not complete interactive auth.

After bootstrap, SSH into the VPS:

```bash
ssh <alias>
```

Then run:

```bash
claude /login
codex
hermes
```

These flows may open browser URLs or prompt for codes. Complete them from a real terminal.

Do not paste provider API keys into chat. Store secrets in the relevant tool's config or the agent container `.env`.