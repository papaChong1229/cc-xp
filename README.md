# cc-xp — 把 Claude Code 變成 RPG 的 statusline

把你在 Claude Code 的**終生 token 消耗**變成經驗值，顯示等級 `Lv.`、日本中二風稱號、XP 進度條，
再加一層 **靈力 RPG buff 事件** 與 **外觀商店**。

```
[✻ Opus 4.8 (1M) - high] ⬩  my-project |  main
[🌌️ 夜天ノ裁定者] Lv. 168 ⬩ 4.9B | ctx 7% | 5hr 0% | weekly 0%
[████████░░░░░░░░░░░] 41.25% (180,394,788 / 437,325,491) ⬩ 靈 1,234 霊格:参  🌀 霊脈活性 1.2x 22m
```

## 核心理念：誠實守恆

- **XP = 你的真實 claude-only 終生 token 數**（透過 [`ccusage`](https://github.com/ryoppippi/ccusage) 重算），等級/稱號永遠誠實、改不了。
- RPG 事件只動一條**獨立貨幣「靈力」**，絕不污染 token 真相 — 看數字不會被誤導成「我用了多少」。

## 需求

- `python3`
- [`ccusage`](https://github.com/ryoppippi/ccusage)（可 `bunx ccusage` 免安裝，或 `npm i -g ccusage`）
- **Nerd Font** + 支援 emoji 的終端（icon 用）

## 安裝

```bash
# 1) 加入 marketplace
/plugin marketplace add papaChong1229/cc-xp
# 2) 安裝 plugin（含 UserPromptSubmit hook，自動啟用）
/plugin install cc-xp@cc-xp
```

### 啟用 statusline（一次性手動步驟）

> Claude Code 的 `statusLine` 只能由使用者自己設定，plugin 無法代設。

在你的 `~/.claude/settings.json` 加：

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/xp-statusline.py\"",
    "padding": 0
  }
}
```

> 若你的環境 `${CLAUDE_PLUGIN_ROOT}` 在 statusLine 不展開，改用實際路徑
> `~/.claude/plugins/cache/cc-xp/.../scripts/xp-statusline.py`，或把 `scripts/xp-statusline.py`
> 複製到固定位置（如 `~/.claude/scripts/`）後指向它。

## 用法（shop / buy / equip）

建議在你的 shell 設一個別名：

```bash
cc-xp() { python3 "<plugin>/scripts/xp-statusline.py" "$@"; }
```

```bash
cc-xp shop                # 看商店 + 靈力餘額
cc-xp buy bar_purple      # 花靈力解鎖外觀
cc-xp equip bar_purple    # 裝備
cc-xp unequip bar_theme   # 卸下
cc-xp events off          # 關閉整套 RPG 事件（statusline 退回純資訊型）
```

## 運作機制

- **靈力**：每送一則訊息（`UserPromptSubmit` hook）按 token 增量累積；buff 生效時加速。
- **反刷**：新事件擲骰需「距上次 ≥ 90 分」**且**「≥ 8 則訊息」，時間戳存全域 state，狂開 session 無效。
- **Buff 事件**（v1）：霊脈活性 1.2x / 凪 1.1x / 冥月 1.5x / 狂乱 2.0x（多數擲骰為無事件）。
- **商店 + 霊格**：靈力花在外觀（稱號異名 / icon 變體 / bar 配色 / 特效），總獲得量自動晉「霊格」階級。
- **資料**：state 存在 `~/.claude/statusline/.cc-xp.dat`（base64 + HMAC 簽章；手改會被重置）。全部 local，不上傳。

## 自訂

打開 `scripts/xp-statusline.py` 最上方常數區：`TITLES`（稱號 + 異名）、`BUFFS`（事件池）、`SHOP`（商店）、
`REI_RATE`（靈力速率）、`BAR_THEMES`、`C_*`（顏色）、`LINE_SPACING`、升級曲線 `F/A/R`。

## Roadmap

- 轉蛋、靈力當事件燃料、Quest 型挑戰事件（「Y 分內消耗 X token」）。

## License

MIT
