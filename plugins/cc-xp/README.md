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

Non-destructive (v0.1.1): cc-xp appends two lines (title + XP bar), plus a third line when a buff event is active. Running
`cc-xp install` records your previous `statusLine` and stacks it on top at render time,
so your own statusline is never clobbered. XP numbers in parens auto-format to K/M/B.

Requirements: `python3`, `ccusage` (or `bunx ccusage`), a Nerd Font + emoji-capable terminal.
