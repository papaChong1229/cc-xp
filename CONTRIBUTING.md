# Contributing to cc-xp

歡迎貢獻！本專案採 **fork + Pull Request** 流程，任何人都不能直接 push 到本 repo。

## 分支模型

| 分支 | 用途 | 規則 |
|---|---|---|
| `main` | **release / 穩定版**。一行安裝 (`install.sh`) 與 plugin marketplace 都抓這支 | 受保護，只接受來自 `develop` 的 release PR；不直接開發 |
| `develop` | **整合 / 開發中**。所有功能、修補先進這裡 | 受保護，只接受 PR |
| `feature/*`、`fix/*` | 你 fork 內的工作分支 | 自由 |

發版：`develop` → 開 PR 合進 `main` → 在 `main` 打 tag（如 `v0.2.0`）。

## 流程

1. **Fork** 這個 repo 到你的帳號。
2. 從 `develop` 開分支：`git checkout develop && git checkout -b feature/我的功能`。
3. 改完、本機驗證（見下）。
4. 推到你的 fork，對**本 repo 的 `develop`** 開 PR（不是 `main`）。
5. 通過 review 後合併。

## 本機驗證

改 `plugins/cc-xp/scripts/xp-statusline.py` 後至少跑：

```bash
python3 -m py_compile plugins/cc-xp/scripts/xp-statusline.py     # 語法
echo '{"model":{"display_name":"Opus"}}' | python3 plugins/cc-xp/scripts/xp-statusline.py   # render 不崩
python3 plugins/cc-xp/scripts/xp-statusline.py help              # 指令說明
```

碰到事件 / 靈力 / 商店邏輯，請附上對應的隔離測試（用暫存 state 路徑，勿動真實 `~/.claude`）。

## 原則

- **誠實守恆**：等級 / 稱號 / token 永遠等於真實 token，事件只能動「靈力」這條獨立貨幣。任何破壞這點的 PR 不會被接受。
- 不新增會上傳使用者資料的行為（本工具全 local）。
- 數值 / 文案 / 外觀的調整集中在腳本最上方常數區。
