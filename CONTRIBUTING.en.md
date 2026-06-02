# Contributing to cc-xp

[繁體中文](./CONTRIBUTING.md) ｜ English

Contributions welcome! This project uses a **fork + Pull Request** flow — nobody pushes directly to this repo.

## Branch model

| Branch | Purpose | Rule |
|---|---|---|
| `main` | **release / stable**. The one-line installer (`install.sh` / `install.ps1`) and the plugin marketplace both pull from here | Protected; only accepts release PRs from `develop`; no direct development |
| `develop` | **integration / in-progress**. All features and fixes land here first | Protected; PR-only |
| `feature/*`, `fix/*` | your working branches inside your fork | free |

Releasing: `develop` → open a PR into `main` → tag on `main` (e.g. `v0.2.0`).

## Workflow

1. **Fork** this repo to your account.
2. Branch off `develop`: `git checkout develop && git checkout -b feature/my-thing`.
3. Make changes and verify locally (below).
4. Push to your fork and open a PR against **this repo's `develop`** (not `main`).
5. Merge after review.

## Local verification

After editing `plugins/cc-xp/scripts/xp-statusline.py`, at minimum run:

```bash
python3 -m py_compile plugins/cc-xp/scripts/xp-statusline.py     # syntax
echo '{"model":{"display_name":"Opus"}}' | python3 plugins/cc-xp/scripts/xp-statusline.py   # render doesn't crash
python3 plugins/cc-xp/scripts/xp-statusline.py help              # command help
```

For changes to event / 靈力 / shop logic, include an isolated test (point state paths at a temp dir; never touch the real `~/.claude`).

## Principles

- **Honesty is preserved**: level / title / token are always equal to the real token count; events may only move the separate 靈力 currency. PRs that break this will not be accepted.
- Do not add anything that uploads user data (this tool is fully local).
- Keep numeric / copy / cosmetic tweaks in the constants block at the top of the script.
