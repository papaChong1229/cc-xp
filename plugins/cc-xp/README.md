# cc-xp (plugin)

Gamified Claude Code statusline. See the [repo README](../../README.md) for full docs.

This plugin ships:

- `scripts/xp-statusline.py` — the statusline renderer + RPG engine (`tick` / `shop` / `buy` / `equip` / `events` subcommands).
- `hooks/hooks.json` — a `UserPromptSubmit` hook running `xp-statusline.py tick` each message (drives 靈力 accrual + events).

**StatusLine is user-settings-only** — after installing, add to your `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/xp-statusline.py\"",
    "padding": 0
  }
}
```

Requirements: `python3`, `ccusage` (or `bunx ccusage`), a Nerd Font + emoji-capable terminal.
