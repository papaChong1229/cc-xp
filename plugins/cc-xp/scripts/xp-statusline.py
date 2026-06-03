#!/usr/bin/env python3
"""
XP / Level statusline for Claude Code.

把「終生累計消耗的 token 數」當經驗值，換算等級 Lv. + 日本中二風稱號，
並畫一條 XP 進度條。資料層用 ccusage（daily --json 的 summary.totalTokens），
配快取 + 背景非阻塞更新，避免每次 render 都全掃 transcript 造成卡頓。

輸出：cc-xp 只追加兩行，不再自畫 model/folder/git 那行。
  line A: [稱號] Lv.N ⬩ <終生總量>
  line B: [██████░░░] 42.56% (本級進度 / 本級跨度)   ← 括號數字自動換 K/M/B 單位
非破壞性包裝：若使用者原本已設 statusLine，install 會記下它，render 時先執行
那條原指令、把它的輸出接在最上面，cc-xp 兩行附在其下。沒有原指令就只輸出兩行。

用法：
  正常：Claude Code 透過 stdin 餵 JSON 呼叫本檔。
  背景刷新：本檔以 `--refresh` 被自己 spawn，跑 ccusage 寫快取，不讀 stdin。
"""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time

# ─────────────────────────── 可調參數（你之後都能改）───────────────────────────

HOME = os.path.expanduser("~")

# 升級曲線：T(L)=F*(L-1)+A*(R^(L-1)-1)/(R-1)，單級 D(L)=F+A*R^(L-1)
# 由 Codex 校準：Lv.176 ≈ 10B 累計、單級跨度 ≈ 884.8M，貼近參考圖。
F = 100_000
A = 178.1064532296
R = 1.09210306927758

# 稱號表：(起始等級, 稱號, icon)。找「起始等級 <= 目前等級」中最大的那一階。
# 日本中二風，刻意避開武俠詞；中段保留「影武者」。最高階為封頂稱號。
# icon 用 emoji，逐階貼合語感；想換單色 Nerd Font glyph 直接改該欄即可。
# (起始等級, 稱號, icon, 異名, 異名icon)。異名/異名icon 為商店可解鎖的變體套組。
TITLES = [
    (1,   "見習イレギュラー", "✨",   "名無シノ異物", "🥚"),
    (6,   "黒猫ノ契約者", "🐈‍⬛",   "夜陰ノ使い魔", "🐾"),
    (11,  "片翼ノ観測者", "👁",     "堕天ノ瞳", "🪽"),
    (19,  "幽玄ノ詠ミ手", "🔮",     "呪詛ノ紡ギ手", "📜"),
    (28,  "蒼雷ノデバッガー", "⚡",   "雷霆ノ討伐者", "🌩"),
    (39,  "影武者", "🥷",           "暗影ノ伽藍主", "🗡"),
    (53,  "深淵ヲ覗ク者", "🕳",     "奈落ノ巡礼者", "🌀"),
    (69,  "月蝕ノ執行者", "🌘",     "蝕ノ裁キ手", "🌑"),
    (86,  "虚空ノ錬成師", "⚗",      "無ヨリ生ム者", "🧪"),
    (106, "黒曜ノ支配者", "💠",     "黒鋼ノ王", "🖤"),
    (126, "禁書庫ノ番人", "📕",     "禁忌ノ司書", "📓"),
    (151, "夜天ノ裁定者", "🌌",     "星辰ノ審判者", "🌠"),
    (176, "終焉ノ理", "☄",         "終末ノ法則", "🌋"),
    (201, "無限回廊ノ君主", "♾",    "永劫ノ覇王", "🔱"),
    (226, "神域プロンプトマスター", "⛩", "神咒ノ大賢者", "🕊"),
    (251, "因果ヲ書キ換エル者", "🖋", "運命改竄者", "🧬"),
    (276, "零ノ黙示録", "🌑",       "虚無ノ預言者", "🌫"),
    (300, "天壊スル終極ノ概念", "☠", "世界ヲ終ワラセル者", "👁‍🗨"),
]

# 只計 Claude Code 自己的 token（濾掉 codex / gpt / gemini 等）；False = 全部 agent
CLAUDE_ONLY = True

CACHE_PATH = os.path.join(HOME, ".claude", "statusline", "xp-cache.json")
CACHE_TTL_SEC = 60          # 快取多久算過期 → 觸發背景刷新
FIRST_RUN_TIMEOUT = 25      # 首次無快取時，同步等 ccusage 的上限秒數
REFRESH_TIMEOUT = 120       # 背景刷新跑 ccusage 的上限秒數

BAR_WIDTH = 19              # XP 進度條寬度（字元）

# 圖示（Nerd Font glyph；想換直接改這裡）
ICON_TITLE  = ""      #  稱號

# 顏色
C_RESET  = "\033[0m"
C_DIM    = "\033[38;5;240m"            # 分隔線 / 暗
C_LV     = "\033[1;38;5;255m"          # 等級：亮白（粗）
C_TITLE  = "\033[1;38;5;213m"          # 稱號：亮紫粉
C_TOTAL  = "\033[38;5;245m"            # 總量：灰
C_BAR_F  = "\033[38;2;76;175;80m"      # XP 條已填：經典 XP 綠 (#4CAF50)
C_BAR_E  = "\033[38;2;46;58;46m"       # XP 條未填：暗綠灰
C_PCT    = "\033[1;38;2;102;200;106m"  # 百分比：亮綠（粗）
C_NUM    = "\033[38;5;244m"            # 進度數字：灰
C_REI    = "\033[38;5;159m"            # 靈力：淡青
C_BUFF   = "\033[1;38;5;219m"          # buff：亮粉（粗）
C_REIKAKU = "\033[38;5;141m"           # 霊格：淡紫

# ════════════════════════ RPG 事件系統（模型 3）════════════════════════
# 核心：等級/稱號/token 永遠誠實；事件只動「靈力」這條獨立貨幣。
STATE_PATH = os.path.join(HOME, ".claude", "statusline", ".cc-xp.dat")   # 藏路徑 + 簽章
OLD_STATE_PATH = os.path.join(HOME, ".claude", "statusline", "xp-state.json")  # 舊明文，遷移用
CONFIG_PATH = os.path.join(HOME, ".claude", "statusline", "xp-config.json")    # 開關（明文，使用者可改）
# 輕度防作弊：base64 + HMAC 簽章，手改 state 檔→簽章不符→重置。金鑰在腳本內，
# 故僅嚇阻隨手改，非真正不可偽造（要那種需後端）。摻 user salt 讓檔案不可跨人搬。
_SECRET = b"cc-xp/state-integrity/v1/9f3c7a21"

REI_RATE = 1.0 / 1_000_000     # 靈力 / token（go-forward 累積，不回溯）
ROLL_PERIOD_SEC = 90 * 60      # 兩次擲骰最短間隔（牆鐘）
MIN_MSGS = 8                   # 自上次擲骰起最少訊息數（反刷）

# Buff 事件池：(id, 名稱, icon, 倍率, 時長分, 權重)。"_none_" 為「無事件」。
BUFFS = [
    ("_none_",   "",          "",   1.0, 0,  60),
    ("reimyaku", "霊脈活性",   "🌀", 1.2, 30, 18),
    ("nagi",     "凪ノ恩恵",   "🌫", 1.1, 60, 14),
    ("meigetsu", "冥月ノ加護", "🌕", 1.5, 15,  6),
    ("ranbu",    "狂乱モード", "⚡", 2.0,  8,  2),
]

# 霊格 階級：(門檻 rei_earned_total, 名稱)。由終生靈力獲得量自動晉級。
REIKAKU = [
    (0,     ""),
    (500,   "序"),
    (2000,  "弐"),
    (5000,  "参"),
    (12000, "伍"),
    (30000, "極"),
    (80000, "神"),
]

# XP bar 配色主題：theme_id -> (filled, empty, pct)
BAR_THEMES = {
    "green":    ("\033[38;2;76;175;80m",  "\033[38;2;46;58;46m",  "\033[1;38;2;102;200;106m"),
    "purple":   ("\033[38;2;156;92;255m", "\033[38;2;46;38;64m",  "\033[1;38;2;180;130;255m"),
    "gold":     ("\033[38;2;255;193;77m", "\033[38;2;64;52;28m",  "\033[1;38;2;255;214;130m"),
    "electric": ("\033[38;2;64;196;255m", "\033[38;2;26;46;64m",  "\033[1;38;2;130;220;255m"),
    "crimson":  ("\033[38;2;229;76;76m",  "\033[38;2;64;30;30m",  "\033[1;38;2;255;120;120m"),
}

# 商店目錄：id -> (slot, 顯示名, 價格靈力, value)
#   slot: title_variant / icon_variant / bar_theme / effect
#   value: bar_theme→theme key；effect→效果 id；異名/icon 變體 value 無意義(用套組)
SHOP = {
    "alt_titles":   ("title_variant", "稱號異名套組",     800, "alt"),
    "alt_icons":    ("icon_variant",  "icon 變體套組",    500, "alt"),
    "bar_purple":   ("bar_theme",     "bar 主題・裂隙紫", 300, "purple"),
    "bar_gold":     ("bar_theme",     "bar 主題・蜜金",   300, "gold"),
    "bar_electric": ("bar_theme",     "bar 主題・電藍",   300, "electric"),
    "bar_crimson":  ("bar_theme",     "bar 主題・緋紅",   300, "crimson"),
    "fx_glow":      ("effect",        "特效・稱號發光",   400, "glow"),
    "fx_frame":     ("effect",        "特效・名牌框",     400, "frame"),
    "fx_star":      ("effect",        "特效・前綴星",     350, "star"),
}

DEFAULT_EQUIPPED = {"title_variant": None, "icon_variant": None,
                    "bar_theme": "green", "effect": None}

# ───────────────────────────────── 曲線計算 ─────────────────────────────────


def cum_xp(level: int) -> float:
    """進入第 level 級所需的累計 XP，T(level)。"""
    if level <= 1:
        return 0.0
    return F * (level - 1) + A * (R ** (level - 1) - 1) / (R - 1)


def level_span(level: int) -> float:
    """第 level 級升到 level+1 的單級需求，D(level)。"""
    return F + A * (R ** (level - 1))


def level_for_xp(xp: float):
    """回傳 (等級, 本級已累進度, 本級跨度)。"""
    level = 1
    # 迴圈上限保護；正常 XP（即使 1e15）也落在數百級內。
    while level < 2000 and cum_xp(level + 1) <= xp:
        level += 1
    base = cum_xp(level)
    span = level_span(level)
    progress = xp - base
    return level, progress, span


def title_for_level(level: int, alt_name=False, alt_icon=False):
    """回傳 (稱號, icon)；alt_* 為 True 時取異名/異名icon。"""
    row = TITLES[0]
    for t in TITLES:
        if level >= t[0]:
            row = t
        else:
            break
    name = row[3] if alt_name else row[1]
    icon = row[4] if alt_icon else row[2]
    return name, icon


def reikaku_name(rei_earned_total: float) -> str:
    """由終生靈力獲得量回傳霊格名稱（空字串=未達序階）。"""
    name = ""
    for threshold, n in REIKAKU:
        if rei_earned_total >= threshold:
            name = n
        else:
            break
    return name


# ───────────────────────────────── ccusage ─────────────────────────────────


# statusline 常跑在精簡 / 非互動環境（GUI 啟動、login-shell-only），nvm / bun 的 bin
# 多半沒被 shell rc 載進 PATH。下面這些是各家全域安裝的常見落點，補進來再給 which 找，
# 並且同一份 PATH 也餵給 subprocess——全域 ccusage 是 `#!/usr/bin/env node` shebang，
# 要 node 在 PATH 上才跑得起來（bun x 自帶 runtime 不受影響，這就是「bunx 行、npm 全域不行」的根因）。
_EXTRA_PATH_DIRS = (
    os.path.join(HOME, ".bun", "bin"),
    os.path.join(HOME, ".local", "bin"),
    os.path.join(HOME, ".npm-global", "bin"),
    os.path.join(HOME, "node_modules", ".bin"),
    "/usr/local/bin",
    "/opt/homebrew/bin",
)


def _augmented_path():
    """現有 PATH 疊上常見全域安裝位置（含 nvm 各版 bin），回傳去重後的 PATH 字串。"""
    parts = (os.environ.get("PATH", "") or "").split(os.pathsep)
    extra = list(_EXTRA_PATH_DIRS)
    nvm_root = os.path.join(HOME, ".nvm", "versions", "node")
    try:
        for ver in sorted(os.listdir(nvm_root)):
            extra.append(os.path.join(nvm_root, ver, "bin"))
    except OSError:
        pass
    seen, out = set(), []
    for p in parts + extra:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return os.pathsep.join(out)


def ccusage_runners():
    """回傳所有可用的 ccusage 執行前綴，依偏好排序（全域 > bun x > npx）。

    跟舊版 ccusage_cmd 的差別：不再只挑第一個。多個都在就全給，執行時逐一 fallback，
    這樣偵測到的全域 ccusage 萬一跑不起來，仍會退到 bun x / npx。
    """
    from shutil import which
    path = _augmented_path()
    runners = []
    cc = which("ccusage", path=path)
    if cc:
        runners.append([cc])
    bun = which("bun", path=path)
    if bun:
        runners.append([bun, "x", "ccusage"])
    npx = which("npx", path=path)
    if npx:
        runners.append([npx, "--yes", "ccusage"])
    return runners


def _extract_total_tokens(data):
    """從 ccusage daily --json 取終生 totalTokens，相容多版結構。"""
    # CLAUDE_ONLY：用 per-model breakdown 只加總 claude* 模型
    if CLAUDE_ONLY:
        rows = data.get("daily") or data.get("data")
        if isinstance(rows, list):
            total, found = 0, False
            for r in rows:
                if not isinstance(r, dict):
                    continue
                for mb in r.get("modelBreakdowns", []):
                    name = str(mb.get("modelName", "")).lower()
                    if name.startswith("claude"):
                        found = True
                        total += (mb.get("inputTokens", 0) + mb.get("outputTokens", 0)
                                  + mb.get("cacheCreationTokens", 0)
                                  + mb.get("cacheReadTokens", 0))
            if found:
                return int(total)
        # 沒 breakdown（舊版 ccusage）→ 退回全 agent 總量
    # 全 agent：頂層 .totals / .summary 的 totalTokens
    for key in ("totals", "summary"):
        node = data.get(key)
        if isinstance(node, dict) and isinstance(node.get("totalTokens"), (int, float)):
            return int(node["totalTokens"])
    # 再退而求其次：加總每日 totalTokens
    rows = data.get("daily") or data.get("data")
    if isinstance(rows, list):
        s = sum(r.get("totalTokens", 0) for r in rows if isinstance(r, dict))
        if s > 0:
            return int(s)
    return None


# flag 組合（依偏好遞減）。--offline：免連網較快；--breakdown：取 per-model 拆分供
# CLAUDE_ONLY 過濾。後面兩組是給不認得 --breakdown 的舊版 ccusage 的安全網，最後 plain
# 一定能拿到頂層 totals.totalTokens。
_FLAG_COMBOS = (["--offline", "--breakdown"], ["--breakdown"], ["--offline"], [])


def fetch_lifetime_tokens(timeout: int):
    """跑 ccusage daily --json，回傳終生 totalTokens（int）或 None。

    對「每個可用 runner × 每組 flag」逐一嘗試，第一個成功就回。timeout 當作整體
    牆鐘預算（非每次嘗試），避免最壞情況下 runner×flag 連乘把 statusline 卡死。
    """
    runners = ccusage_runners()
    if not runners:
        return None
    env = dict(os.environ)
    env["PATH"] = _augmented_path()
    deadline = time.monotonic() + timeout
    for pre in runners:
        for extra in _FLAG_COMBOS:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                return None
            try:
                out = subprocess.run(
                    pre + ["daily", "--json"] + extra,
                    capture_output=True, text=True, timeout=remaining, env=env,
                )
                if out.returncode != 0 or not out.stdout.strip():
                    continue
                data = json.loads(out.stdout)
                total = _extract_total_tokens(data)
                if total is not None:
                    return total
            except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError):
                continue
    return None


def read_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d.get("tokens"), (int, float)) and isinstance(d.get("ts"), (int, float)):
            return d
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def write_cache(tokens: int):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"tokens": int(tokens), "ts": time.time()}, fh)
    os.replace(tmp, CACHE_PATH)


def spawn_background_refresh():
    """非阻塞 spawn 自己 --refresh，更新快取後即退出。"""
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--refresh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def get_lifetime_tokens():
    """快取優先即時回傳；過期則背景刷新；首次無快取才同步取一次。"""
    cache = read_cache()
    now = time.time()
    if cache and (now - cache["ts"]) < CACHE_TTL_SEC:
        return int(cache["tokens"])
    if cache:
        spawn_background_refresh()          # 過期：先用舊值渲染，背景補
        return int(cache["tokens"])
    # 完全沒快取：同步取一次（一次性成本），失敗回 0
    toks = fetch_lifetime_tokens(FIRST_RUN_TIMEOUT)
    if toks is not None:
        write_cache(toks)
        return toks
    return 0


# 沒有任何 runner 時給使用者的安裝提示（doctor / SessionStart 共用）。
CCUSAGE_INSTALL_HINT = (
    "cc-xp：偵測不到 ccusage，等級會卡在 Lv.1。擇一安裝即可：\n"
    "  • bun（推薦，免裝套件）： curl -fsSL https://bun.sh/install | bash\n"
    "  • 或全域安裝：           npm i -g ccusage\n"
    "  • 已裝 node 也可不裝：    確保 npx 在 PATH（cc-xp 會用 npx 跑）"
)


def _runner_label(pre):
    """把 runner 前綴轉成人看得懂的名稱。"""
    exe = os.path.basename(pre[0]).lower()
    if exe.startswith("bun"):
        return "bun x ccusage"
    if exe.startswith("npx"):
        return "npx ccusage"
    return "全域 ccusage"


def cmd_doctor():
    """列出偵測到的 ccusage 執行方式 + 實際取得的 token，給使用者自查。"""
    runners = ccusage_runners()
    if not runners:
        print(CCUSAGE_INSTALL_HINT)
        return
    print("cc-xp ccusage 診斷：")
    for i, pre in enumerate(runners):
        mark = "→ 優先" if i == 0 else "  備援"
        print(f"  {mark}  {_runner_label(pre):<16} {' '.join(pre)}")
    toks = fetch_lifetime_tokens(FIRST_RUN_TIMEOUT)
    if toks is None:
        print("  ⚠ 偵測到 runner 但實際取數失敗——可能是 node 不在 PATH 或版本太舊。")
    else:
        print(f"  ✓ 取得終生 tokens：{toks:,}（CLAUDE_ONLY={CLAUDE_ONLY}）")


def cmd_ccusage_check():
    """SessionStart hook 用：偵測不到任何 runner 才輸出安裝提示，否則靜默。"""
    if not ccusage_runners():
        print(CCUSAGE_INSTALL_HINT)


# ───────────────────────────────── 顯示 ─────────────────────────────────


def humanize(n: float) -> str:
    n = float(n)
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= size:
            v = n / size
            return (f"{v:.1f}".rstrip("0").rstrip(".")) + unit
    return str(int(n))


def wrapped_line1(raw_stdin: str, cfg: dict):
    """執行使用者原本的 statusLine 指令，回傳其輸出當第一行；無 / 失敗回 None。

    install 時把舊的 statusLine 物件記進 config 的 "wrapped_statusline"。這裡用
    同一份 stdin JSON 餵給它，抓 stdout。防遞迴：指令本身若指向 cc-xp 就不跑。
    """
    w = cfg.get("wrapped_statusline")
    if not isinstance(w, dict):
        return None
    cmd = w.get("command")
    if not cmd or "xp-statusline.py" in cmd:   # 遞迴防護：別呼叫到自己
        return None
    try:
        out = subprocess.run(
            cmd, shell=True, input=raw_stdin,
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.rstrip("\n")
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return None


def force_emoji(icon: str) -> str:
    """補 VS16 (U+FE0F) 強制彩色 emoji 呈現；ZWJ 組合字或已帶 VS16 則原樣。"""
    if "‍" in icon or icon.endswith("️"):
        return icon
    return icon + "️"


def _title_segment(title, ticon, effect):
    """依特效渲染稱號區段。"""
    tcolor = "\033[1;38;5;218m" if effect == "glow" else C_TITLE
    lb, rb = ("【", "】") if effect == "frame" else ("[", "]")
    star = "★ " if effect == "star" else ""
    return f"{tcolor}{star}{lb}{ticon} {title}{rb}{C_RESET}"


def render_xp_lines(xp: int, equipped: dict, events_on: bool, state: dict):
    level, progress, span = level_for_xp(xp)
    title, ticon = title_for_level(
        level,
        alt_name=(equipped.get("title_variant") == "alt"),
        alt_icon=(equipped.get("icon_variant") == "alt"),
    )
    ticon = force_emoji(ticon)
    pct = (progress / span * 100) if span > 0 else 0.0

    bar_f, bar_e, c_pct = BAR_THEMES.get(equipped.get("bar_theme") or "green",
                                         BAR_THEMES["green"])
    filled = int(round(pct / 100 * BAR_WIDTH))
    filled = max(0, min(BAR_WIDTH, filled))
    bar = (bar_f + "█" * filled + bar_e + "░" * (BAR_WIDTH - filled) + C_RESET)

    title_seg = _title_segment(title, ticon, equipped.get("effect"))

    line_title = (
        f"{title_seg} "
        f"{C_LV}Lv. {level}{C_RESET} "
        f"{C_TOTAL}⬩ {humanize(xp)}{C_RESET}"
    )
    line_xp = (
        f"{C_DIM}[{C_RESET}{bar}{C_DIM}]{C_RESET} {c_pct}{pct:.2f}%{C_RESET} "
        f"{C_NUM}({humanize(progress)} / {humanize(span)}){C_RESET}"
    )
    lines = [line_title, line_xp]
    if events_on:
        # 靈力 + 霊格（A2：霊格融進「靈」→ 靈〔参〕 49）接在 xp 行尾。
        rei = int(state.get("rei", 0))
        rk = reikaku_name(state.get("rei_earned_total", 0))
        rei_seg = (f"{C_REI}靈{C_REIKAKU}〔{rk}〕{C_REI} {rei:,}{C_RESET}" if rk
                   else f"{C_REI}靈 {rei:,}{C_RESET}")
        lines[1] += f" {C_DIM}⬩{C_RESET} {rei_seg}"
        # buff 獨立成行，接在 xp 行下面（只有生效時才出現）。
        buff = active_buff_or_none(state)
        if buff:
            remain = max(0, int((buff["expires_at"] - time.time()) / 60))
            lines.append(f"{C_BUFF}{force_emoji(buff['icon'])} {buff['name']} "
                         f"{buff['mult']:g}x {remain}m{C_RESET}")
    return lines


# ════════════════════════ 狀態 / 設定 / 引擎 / 商店 ════════════════════════


def load_config() -> dict:
    cfg = {"events_enabled": True}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            cfg.update(d)
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return cfg


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def new_state() -> dict:
    return {
        "version": 1, "rei": 0.0, "rei_earned_total": 0.0,
        "last_seen_tokens": None, "last_roll_at": 0, "msgs_since_roll": 0,
        "active_buff": None, "unlocked": [], "equipped": dict(DEFAULT_EQUIPPED),
    }


def _state_key() -> bytes:
    salt = (os.environ.get("USER") or os.path.basename(HOME) or "").encode()
    return hashlib.sha256(_SECRET + b"|" + salt).digest()


def _sign(blob: bytes) -> str:
    return hmac.new(_state_key(), blob, hashlib.sha256).hexdigest()


def _merge_state(d: dict) -> dict:
    st = new_state()
    if isinstance(d, dict):
        st.update(d)
        eq = dict(DEFAULT_EQUIPPED)
        if isinstance(d.get("equipped"), dict):
            eq.update(d["equipped"])
        st["equipped"] = eq
    return st


def load_state() -> dict:
    # 簽章檔
    try:
        with open(STATE_PATH, "rb") as fh:
            raw = fh.read()
        blob, _, sig = raw.rpartition(b"\n")
        if blob and hmac.compare_digest(sig.decode().strip(), _sign(blob)):
            return _merge_state(json.loads(base64.b64decode(blob)))
        # 有檔但簽章不符 → 視為竄改 → 重置（輕度嚇阻）
        if raw.strip():
            return new_state()
    except FileNotFoundError:
        pass
    except (OSError, ValueError, json.JSONDecodeError):
        return new_state()
    # 無簽章檔 → 嘗試從舊明文一次性遷移
    try:
        with open(OLD_STATE_PATH, "r", encoding="utf-8") as fh:
            st = _merge_state(json.load(fh))
        save_state(st)
        try:
            os.remove(OLD_STATE_PATH)
        except OSError:
            pass
        return st
    except (OSError, json.JSONDecodeError, ValueError):
        return new_state()


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    blob = base64.b64encode(json.dumps(st, ensure_ascii=False).encode())
    out = blob + b"\n" + _sign(blob).encode()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(out)
    os.replace(tmp, STATE_PATH)


def active_buff_or_none(st: dict):
    """回傳未過期的 active_buff，否則 None（不寫檔）。"""
    b = st.get("active_buff")
    if isinstance(b, dict) and b.get("expires_at", 0) > time.time():
        return b
    return None


def _roll_buff():
    """加權擲一次 buff；回傳 buff dict 或 None（無事件）。"""
    import random
    total = sum(w for *_, w in BUFFS)
    pick = random.uniform(0, total)
    acc = 0
    for bid, name, icon, mult, dur, weight in BUFFS:
        acc += weight
        if pick <= acc:
            if bid == "_none_":
                return None
            return {"id": bid, "name": name, "icon": icon,
                    "mult": mult, "expires_at": time.time() + dur * 60}
    return None


def cmd_tick():
    """UserPromptSubmit hook 引擎：靈力累積 + 反刷擲骰 + buff 結算。靜默，永不拋。"""
    try:
        cfg = load_config()
        if not cfg.get("events_enabled", True):
            return
        st = load_state()
        now = time.time()

        cache = read_cache()
        tokens = int(cache["tokens"]) if cache else None

        # 1) 靈力累積（go-forward；首次只記基準不發放）
        if tokens is not None:
            if st["last_seen_tokens"] is None:
                st["last_seen_tokens"] = tokens
            elif tokens > st["last_seen_tokens"]:
                delta = tokens - st["last_seen_tokens"]
                buff = active_buff_or_none(st)
                mult = buff["mult"] if buff else 1.0
                gain = delta * REI_RATE * mult
                st["rei"] += gain
                st["rei_earned_total"] += gain
                st["last_seen_tokens"] = tokens

        # 2) buff 過期結算
        if st.get("active_buff") and not active_buff_or_none(st):
            st["active_buff"] = None

        # 3) 反刷擲骰：週期 + 活動 + 無生效 buff
        st["msgs_since_roll"] = int(st.get("msgs_since_roll", 0)) + 1
        if (active_buff_or_none(st) is None
                and now - st.get("last_roll_at", 0) >= ROLL_PERIOD_SEC
                and st["msgs_since_roll"] >= MIN_MSGS):
            st["last_roll_at"] = now
            st["msgs_since_roll"] = 0
            buff = _roll_buff()
            if buff:
                st["active_buff"] = buff

        save_state(st)
    except Exception:
        return  # hook 永不阻擋送訊息


def _fmt_rei(v):
    return f"{int(v):,}"


def cmd_events(arg):
    cfg = load_config()
    if arg in ("on", "off"):
        cfg["events_enabled"] = (arg == "on")
        save_config(cfg)
    state_txt = "ON" if cfg.get("events_enabled", True) else "OFF"
    print(f"events: {state_txt}")


def _disp_width(s: str) -> int:
    """字串的終端顯示寬度（全形/寬字元算 2，組合字/VS16 算 0）。"""
    import unicodedata
    w = 0
    for ch in s:
        if ch in ("‍", "️") or unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(s: str, width: int) -> str:
    """依顯示寬度左對齊補空白。"""
    return s + " " * max(0, width - _disp_width(s))


def cmd_shop():
    st = load_state()
    print(f"靈力餘額：{_fmt_rei(st['rei'])}　|　霊格：{reikaku_name(st['rei_earned_total']) or '—'}")
    print("─" * 44)
    for sid, (slot, name, cost, val) in SHOP.items():
        owned = sid in st["unlocked"]
        equipped = st["equipped"].get(slot) == (val if slot in ("bar_theme", "effect") else "alt") and owned
        price = "已裝備" if equipped else ("已擁有" if owned else f"{cost:,} 靈")
        mark = "✅" if equipped else ("🔓" if owned else "　")
        print(f"  {_pad(sid, 14)}{_pad(name, 20)}{mark} {_pad(price, 8)}")
    print("─" * 44)
    print("買：cc-xp buy <id>　裝備：cc-xp equip <id>　卸下：cc-xp unequip <slot>")


def cmd_buy(sid):
    if sid not in SHOP:
        print(f"沒有這個品項：{sid}")
        return
    st = load_state()
    slot, name, cost, val = SHOP[sid]
    if sid in st["unlocked"]:
        print(f"已擁有：{name}")
        return
    if st["rei"] < cost:
        print(f"靈力不足：需要 {cost}，目前 {_fmt_rei(st['rei'])}")
        return
    st["rei"] -= cost
    st["unlocked"].append(sid)
    save_state(st)
    print(f"已購入：{name}（剩餘靈力 {_fmt_rei(st['rei'])}）。裝備：equip {sid}")


def cmd_equip(sid):
    if sid not in SHOP:
        print(f"沒有這個品項：{sid}")
        return
    st = load_state()
    slot, name, cost, val = SHOP[sid]
    if sid not in st["unlocked"]:
        print(f"尚未擁有：{name}（先 buy {sid}）")
        return
    st["equipped"][slot] = val if slot in ("bar_theme", "effect") else "alt"
    save_state(st)
    print(f"已裝備：{name}")


def cmd_unequip(slot):
    st = load_state()
    if slot not in DEFAULT_EQUIPPED:
        print(f"未知欄位：{slot}（title_variant/icon_variant/bar_theme/effect）")
        return
    st["equipped"][slot] = DEFAULT_EQUIPPED[slot]
    save_state(st)
    print(f"已卸下：{slot}")


COMMANDS = [
    ("install",          "一鍵設定 statusLine + 事件 hook + shell 別名 cc-xp"),
    ("install --no-hook", "同上但不設 hook（給用 plugin 提供 hook 的人）"),
    ("shop",             "靈力商店：列出可購外觀 + 餘額"),
    ("list",             "看自己擁有 / 已裝備 / 未擁有的外觀"),
    ("buy <id>",         "花靈力購買外觀"),
    ("equip <id>",       "裝備已擁有的外觀"),
    ("unequip <slot>",   "卸下外觀（slot: title_variant/icon_variant/bar_theme/effect）"),
    ("events on|off",    "開 / 關整套 RPG 事件（關閉時 statusline 退回純資訊型）"),
    ("doctor",           "診斷 ccusage：列出偵測到的執行方式與實際取得的 token"),
    ("help",             "顯示這個說明"),
    ("tick",             "（內部）事件引擎 tick，由 UserPromptSubmit hook 自動呼叫"),
    ("ccusage-check",    "（內部）偵測不到 ccusage 才提示安裝，由 SessionStart hook 呼叫"),
    ("(無參數)",          "（內部）輸出 statusline，由 Claude Code 自動呼叫"),
]


def cmd_help():
    print("cc-xp — Claude Code RPG statusline\n")
    print("用法：cc-xp <指令> [參數]\n")
    for name, desc in COMMANDS:
        print(f"  {_pad(name, 20)}{desc}")
    print("\nstate: ~/.claude/statusline/.cc-xp.dat（簽章）　開關: xp-config.json")


def _is_equipped(eq, slot, val):
    return eq.get(slot) == (val if slot in ("bar_theme", "effect") else "alt")


def cmd_list():
    st = load_state()
    owned, eq = st["unlocked"], st["equipped"]
    print(f"靈力：{_fmt_rei(st['rei'])}　霊格：{reikaku_name(st['rei_earned_total']) or '—'}\n")
    print("【已裝備】")
    shown = False
    for sid, (slot, name, cost, val) in SHOP.items():
        if sid in owned and _is_equipped(eq, slot, val):
            print(f"  ✅ {name}"); shown = True
    if not shown:
        print("  （皆為預設外觀）")
    print("【已擁有・未裝備】")
    shown = False
    for sid, (slot, name, cost, val) in SHOP.items():
        if sid in owned and not _is_equipped(eq, slot, val):
            print(f"  🔓 {_pad(sid, 14)}{name}"); shown = True
    if not shown:
        print("  （無）")
    print("【未擁有】")
    for sid, (slot, name, cost, val) in SHOP.items():
        if sid not in owned:
            print(f"  🔒 {_pad(sid, 14)}{_pad(name, 20)}{cost:,} 靈")


_ALIAS_MARKER = "# >>> cc-xp >>>"


def _shell_profile() -> str:
    sh = os.environ.get("SHELL", "")
    if "zsh" in sh:
        return os.path.join(HOME, ".zshrc")
    if "bash" in sh:
        return os.path.join(HOME, ".bashrc")
    return os.path.join(HOME, ".profile")


def _powershell_profile_path():
    """問 PowerShell 自己的 $PROFILE 路徑（Windows）。失敗回 None。"""
    override = os.environ.get("CC_XP_PS_PROFILE")  # 測試用：避免動到真實 profile
    if override:
        return override
    import subprocess
    for exe in ("pwsh", "powershell"):
        try:
            out = subprocess.run([exe, "-NoProfile", "-Command", "$PROFILE"],
                                 capture_output=True, text=True, timeout=15)
            p = out.stdout.strip()
            if out.returncode == 0 and p:
                return p
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _install_launcher(stable: str, py: str) -> str:
    """建立可在 PATH 用的 cc-xp 啟動器；回傳結果說明字串。冪等。"""
    if os.name == "nt":  # Windows
        cmd_path = os.path.join(os.path.dirname(stable), "cc-xp.cmd")
        with open(cmd_path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(f'@echo off\n"{py}" "{stable}" %*\n')
        notes = [f"已建立 {cmd_path}（把該資料夾加入 PATH 即可用 cc-xp）"]
        prof = _powershell_profile_path()
        if prof:
            try:
                existing = ""
                if os.path.exists(prof):
                    with open(prof, encoding="utf-8") as fh:
                        existing = fh.read()
                if _ALIAS_MARKER not in existing:
                    os.makedirs(os.path.dirname(prof), exist_ok=True)
                    with open(prof, "a", encoding="utf-8") as fh:
                        fh.write(f'\n{_ALIAS_MARKER}\nfunction cc-xp {{ & "{py}" "{stable}" @args }}\n'
                                 f'# <<< cc-xp <<<\n')
                    notes.append(f"已加入 PowerShell $PROFILE 函式（{prof}）")
                else:
                    notes.append(f"PowerShell $PROFILE 已有 cc-xp")
            except OSError:
                pass
        return "；".join(notes)
    # macOS / Linux
    prof = _shell_profile()
    try:
        with open(prof, encoding="utf-8") as fh:
            existing = fh.read()
    except OSError:
        existing = ""
    if _ALIAS_MARKER in existing:
        return f"已存在於 {prof}"
    with open(prof, "a", encoding="utf-8") as fh:
        fh.write(f'\n{_ALIAS_MARKER}\ncc-xp() {{ "{py}" "{stable}" "$@"; }}\n# <<< cc-xp <<<\n')
    return f"已加到 {prof}"


def cmd_install(no_hook=False):
    """把自己裝成穩定路徑，並寫好 statusLine + hook + 啟動器（跨平台、皆冪等）。"""
    import shutil
    py = sys.executable or "python3"
    stable_dir = os.path.join(HOME, ".claude", "cc-xp")
    stable = os.path.join(stable_dir, "xp-statusline.py")
    os.makedirs(stable_dir, exist_ok=True)
    src = os.path.realpath(__file__)
    if src != os.path.realpath(stable):
        shutil.copyfile(src, stable)
    try:
        os.chmod(stable, 0o755)
    except OSError:
        pass

    # settings.json：備份 → 設 statusLine（+ hook）。用 sys.executable 絕對路徑，免靠 PATH。
    settings_path = os.path.join(HOME, ".claude", "settings.json")
    try:
        with open(settings_path, encoding="utf-8") as fh:
            settings = json.load(fh)
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, json.JSONDecodeError, ValueError):
        settings = {}
    if os.path.exists(settings_path):
        shutil.copyfile(settings_path, settings_path + ".cc-xp.bak")

    # 非破壞性包裝：記下使用者原本的 statusLine，render 時先跑它、把輸出接在最上面。
    # 只在原指令不是 cc-xp 自己時才捕捉（重裝時保留先前記下的，避免吃到自己→遞迴）。
    wrapped_note = "（無原 statusLine，僅輸出 cc-xp 兩行）"
    prev = settings.get("statusLine")
    if isinstance(prev, dict) and "xp-statusline.py" not in (prev.get("command") or ""):
        cfg = load_config()
        cfg["wrapped_statusline"] = prev
        save_config(cfg)
        wrapped_note = "已記下你原本的 statusLine，會接在最上面"
    elif isinstance(load_config().get("wrapped_statusline"), dict):
        wrapped_note = "沿用先前記下的原 statusLine"

    settings["statusLine"] = {"type": "command", "command": f'"{py}" "{stable}"', "padding": 0}
    hook_added = False
    if not no_hook:
        hooks = settings.setdefault("hooks", {})
        ups = hooks.setdefault("UserPromptSubmit", [])
        already = any(
            "xp-statusline.py" in h.get("command", "") and "tick" in h.get("command", "")
            for grp in ups if isinstance(grp, dict)
            for h in grp.get("hooks", []) if isinstance(h, dict)
        )
        if not already:
            ups.append({"hooks": [{"type": "command",
                                   "command": f'"{py}" "{stable}" tick', "timeout": 10}]})
            hook_added = True

        # SessionStart：偵測不到 ccusage 時提示安裝（裝好就靜默）。
        ss = hooks.setdefault("SessionStart", [])
        ss_already = any(
            "xp-statusline.py" in h.get("command", "") and "ccusage-check" in h.get("command", "")
            for grp in ss if isinstance(grp, dict)
            for h in grp.get("hooks", []) if isinstance(h, dict)
        )
        if not ss_already:
            ss.append({"hooks": [{"type": "command",
                                  "command": f'"{py}" "{stable}" ccusage-check', "timeout": 10}]})

    tmp = settings_path + ".tmp"
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, settings_path)

    launcher_note = _install_launcher(stable, py)

    print("✅ cc-xp 安裝完成")
    print(f"  腳本        ：{stable}")
    print(f"  statusLine  ：已寫入 {settings_path}（備份 .cc-xp.bak）")
    print(f"  原 statusLine：{wrapped_note}")
    print(f"  事件 hook   ：{'已加入' if hook_added else ('略過(--no-hook)' if no_hook else '已存在')}")
    print(f"  cc-xp 指令  ：{launcher_note}")
    print("  → 重開終端讓 cc-xp 生效；重啟 Claude Code 讓 statusLine/hook 生效")


# ───────────────────────────────── 主流程 ─────────────────────────────────


def main():
    # 強制 UTF-8 輸出：Windows 預設 stdout 用系統碼頁(如 cp950)，印 emoji/CJK 會 UnicodeEncodeError。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    arg = sys.argv[1] if len(sys.argv) > 1 else None

    # ── 非 render 子指令 ──
    if arg == "--refresh":
        toks = fetch_lifetime_tokens(REFRESH_TIMEOUT)
        if toks is not None:
            write_cache(toks)
        return
    if arg == "tick":
        cmd_tick()
        return
    if arg in ("help", "-h", "--help"):
        cmd_help()
        return
    if arg == "install":
        cmd_install(no_hook=("--no-hook" in sys.argv[2:]))
        return
    if arg == "list":
        cmd_list()
        return
    if arg in ("doctor", "ccusage"):
        cmd_doctor()
        return
    if arg == "ccusage-check":
        cmd_ccusage_check()
        return
    if arg == "events":
        cmd_events(sys.argv[2] if len(sys.argv) > 2 else None)
        return
    if arg == "shop":
        cmd_shop()
        return
    if arg == "buy" and len(sys.argv) > 2:
        cmd_buy(sys.argv[2])
        return
    if arg == "equip" and len(sys.argv) > 2:
        cmd_equip(sys.argv[2])
        return
    if arg == "unequip" and len(sys.argv) > 2:
        cmd_unequip(sys.argv[2])
        return

    # ── 預設：render statusline ──
    raw = sys.stdin.read()

    cfg = load_config()
    events_on = bool(cfg.get("events_enabled", True))
    state = load_state() if events_on else new_state()
    equipped = state["equipped"] if events_on else dict(DEFAULT_EQUIPPED)

    xp = get_lifetime_tokens()
    cc_lines = render_xp_lines(xp, equipped, events_on, state)

    # 使用者原本的 statusLine（若有）接最上面，cc-xp 各行附其下；沒有就只輸出 cc-xp 行。
    l1 = wrapped_line1(raw, cfg)
    lines = ([l1] if l1 is not None else []) + cc_lines
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
