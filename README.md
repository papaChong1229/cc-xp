# cc-xp — 把 Claude Code 用量變成 RPG 的 statusline

<div align="center">

[繁體中文] ｜ [English](./README.en.md)

</div>

---

把你在 Claude Code 的**終生 token 消耗**變成經驗值，顯示等級 `Lv.`、日式中二稱號、XP 進度條，
再加一層 **靈力 RPG buff 事件** 與 **外觀商店**。

![cc-xp statusline](./docs/screenshot.png)

<sub>（純文字版示意）</sub>
```
[✻ Opus 4.8 (1M) - high] ⬩  my-project |  main
[🌌️ 夜天ノ裁定者] Lv. 168 ⬩ 4.9B | ctx 7% | 5hr 0% | weekly 0%
[████████░░░░░░░░░░░] 41.25% (180,394,788 / 437,325,491) ⬩ 靈 1,234 霊格:参  🌀 霊脈活性 1.2x 22m
```

## 核心功能

- **XP = 你的真實 claude-only 終生 token 數**（透過 [`ccusage`](https://github.com/ryoppippi/ccusage) 重算）。
- RPG 事件只動一條**獨立貨幣「靈力」**，不會動到 token 的 XP 顯示。

## 需求

- `python3`
- [`ccusage`](https://github.com/ryoppippi/ccusage)（可 `bunx ccusage` 免安裝，或 `npm i -g ccusage`）
- **Nerd Font** + 支援 emoji 的終端（icon 用）

## 安裝（一行搞定）

**macOS / Linux**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/papaChong1229/cc-xp/main/install.sh)
```

**Windows（PowerShell）**
```powershell
irm https://raw.githubusercontent.com/papaChong1229/cc-xp/main/install.ps1 | iex
```

兩者都會自動完成三步：

1. **下載腳本** 到 `~/.claude/cc-xp/`
2. **寫入設定** — 在 `~/.claude/settings.json` 設好 `statusLine` 與 `UserPromptSubmit` hook
   （會先備份成 `settings.json.cc-xp.bak`，保留你既有設定）
3. **設好 `cc-xp` 指令** — mac/Linux 加 shell 別名；Windows 建 `cc-xp.cmd` + PowerShell `$PROFILE` 函式

裝完：**重開終端** + **重啟 Claude Code**。
**更新**：重跑同一行即可（抓最新版、冪等）。

<details>
<summary>替代：用 Claude Code Plugin 安裝</summary>

```bash
/plugin marketplace add papaChong1229/cc-xp
/plugin install cc-xp@cc-xp
```

plugin 會提供 `UserPromptSubmit` hook。但 **`statusLine` 無法由 plugin 代設**，仍需執行一次安裝指令來寫 statusLine + 別名（hook 已由 plugin 提供，故用 `--no-hook`）：

```bash
python3 "$(ls ~/.claude/plugins/cache/cc-xp*/plugins/cc-xp/scripts/xp-statusline.py | head -1)" install --no-hook
```
</details>

## 用法

```bash
cc-xp help                # 看所有指令 + 說明
cc-xp list                # 看自己擁有 / 已裝備 / 未擁有的外觀
cc-xp shop                # 靈力商店 + 餘額
cc-xp buy bar_purple      # 花靈力解鎖外觀
cc-xp equip bar_purple    # 裝備
cc-xp unequip bar_theme   # 卸下
cc-xp events off          # 關閉整套 RPG 事件（statusline 退回純資訊型）
```

## 運作機制

- **靈力**：每送一則訊息（`UserPromptSubmit` hook）按 token 增量累積；buff 生效時加速。
- **反刷**：新事件擲骰需「距上次 ≥ 90 分」**且**「≥ 8 則訊息」，時間戳存全域 state ── 避免有人想要刷訊息 or 新對話來刷靈力。
- **Buff 事件**（v1）：無事件 / 霊脈活性 1.2x / 凪 1.1x / 冥月 1.5x / 狂乱 2.0x。
- **商店 + 霊格**：靈力主要消費於外觀類的內容（稱號異名 / icon 變體 / bar 配色 / 特效），並且會根據總獲得量自動晉升「霊格」階級。
- **資料**：state 存在 `~/.claude/statusline/.cc-xp.dat`（base64 + HMAC 簽章；手改會被重置）。全部 local，不上傳。

## 自訂

打開 `~/.claude/cc-xp/xp-statusline.py` 最上方常數區即可調整：

- **`TITLES`** — 各等級的稱號與異名（中二稱號池）。
- **`BUFFS`** — buff 事件池：每個事件的機率、倍率與持續時間。
- **`SHOP`** — 靈力商店的品項與售價。
- **`REI_RATE`** — 靈力累積速率（每 token 換多少靈力）。
- **`BAR_THEMES`** — XP 進度條的配色主題。
- **`C_*`** — statusline 各部位的顏色（ANSI / 256 色）。
- **`LINE_SPACING`** — 三行之間插入幾個空白行（`0` = 緊湊）。
- **`F` / `A` / `R`** — 升級曲線參數，決定每級所需 XP。

## Roadmap

### 已實裝
- ✅ Lv. / 日式中二稱號 / XP 進度條，XP = claude-only 終生 token
- ✅ 靈力 RPG **Buff 事件** + 反刷雙閘（週期 + 活動）
- ✅ 靈力**商店**（稱號異名 / icon 變體 / bar 配色 / 特效）+ 自動**霊格**階級
- ✅ 事件開關、輕度防作弊（簽章 state）、一行安裝 / 更新

### 未來 Roadmap
- ⏳ **Quest 型挑戰事件**：「Y 分鐘內消耗 X token → 獎勵靈力 / 解鎖」，到期判定成功/失敗
- ⏳ **轉蛋**：花靈力抽外觀，含重複保護
- ⏳ **靈力當事件燃料**：花靈力主動重抽 / 保底一個 buff
- ⏳ 更多 Buff 類型與稱號 / 季節限定外觀
- ⏳ statusline line 1 微調項

歡迎開 issue 許願或送 PR（見 [CONTRIBUTING](./CONTRIBUTING.md)）。

## License

MIT
