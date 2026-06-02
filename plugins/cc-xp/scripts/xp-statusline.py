#!/usr/bin/env python3
"""
XP / Level statusline for Claude Code.

把「終生累計消耗的 token 數」當經驗值，換算等級 Lv. + 日本中二風稱號，
並畫一條 XP 進度條。資料層用 ccusage（daily --json 的 summary.totalTokens），
配快取 + 背景非阻塞更新，避免每次 render 都全掃 transcript 造成卡頓。

輸出（多行）：
  line 1: 原本的 ~/.claude/scripts/statusline.sh 輸出（非破壞性包裝）
  line 2: Lv.N [稱號] ⬩ <終生總量>
  line 3: [██████░░░] 42.56% (本級進度 / 本級跨度)

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
LINE_SPACING = 0            # 三行之間插入幾個空白行（0=緊湊，1=各空一行）

# 圖示（Nerd Font glyph；想換直接改這裡）
ICON_CLAUDE = "✻"          # 模型前的 Claude 標記
ICON_FOLDER = ""      #  資料夾
ICON_GIT    = ""      #  git branch
ICON_TITLE  = ""      #  稱號
NO_GIT_TEXT = "no git repo"

# 顏色
C_RESET  = "\033[0m"
C_MODEL  = "\033[1;38;5;75m"            # 亮藍：模型名
C_FOLDER = "\033[38;5;180m"            # 暖棕：資料夾
C_GIT    = "\033[38;5;108m"            # 灰綠：branch
C_DIM    = "\033[38;5;240m"            # 分隔線 / 暗
C_LV     = "\033[1;38;5;255m"          # 等級：亮白（粗）
C_TITLE  = "\033[1;38;5;213m"          # 稱號：亮紫粉
C_TOTAL  = "\033[38;5;245m"            # 總量：灰
C_META   = "\033[38;5;245m"            # ctx/5hr/weekly：灰
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


def ccusage_cmd():
    """挑一個能跑 ccusage 的方式：全域 > bun x > npx。回傳 list 前綴或 None。"""
    from shutil import which
    if which("ccusage"):
        return ["ccusage"]
    if which("bun"):
        return ["bun", "x", "ccusage"]
    if which("npx"):
        return ["npx", "--yes", "ccusage"]
    return None


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


def fetch_lifetime_tokens(timeout: int):
    """跑 ccusage daily --json，回傳 summary.totalTokens（int）或 None。"""
    pre = ccusage_cmd()
    if pre is None:
        return None
    # --offline：免連網較快；--breakdown：取 per-model 拆分供 CLAUDE_ONLY 過濾。
    for extra in (["--offline", "--breakdown"], ["--breakdown"]):
        try:
            out = subprocess.run(
                pre + ["daily", "--json"] + extra,
                capture_output=True, text=True, timeout=timeout,
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


# ───────────────────────────────── 顯示 ─────────────────────────────────


def humanize(n: float) -> str:
    n = float(n)
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= size:
            v = n / size
            return (f"{v:.1f}".rstrip("0").rstrip(".")) + unit
    return str(int(n))


def _pct_str(val):
    if isinstance(val, (int, float)):
        return f"{round(val)}%"
    return "?%"


def _git_branch(cwd):
    if not cwd:
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def build_line1(data: dict) -> str:
    model = (data.get("model") or {}).get("display_name") or "?"
    model = model.replace("1M context", "1M")  # (1M context) → (1M)
    effort = (data.get("effort") or {}).get("level")
    model_disp = f"{model} - {effort}" if effort else model
    ws = data.get("workspace") or {}
    cwd = ws.get("current_dir") or data.get("cwd") or ""
    folder = os.path.basename(cwd.rstrip("/")) if cwd else "?"
    branch = _git_branch(cwd)
    git_part = (f"{C_GIT}{ICON_GIT} {branch}{C_RESET}" if branch
                else f"{C_DIM}{ICON_GIT} {NO_GIT_TEXT}{C_RESET}")
    return (
        f"{C_DIM}[{C_RESET}{C_MODEL}{ICON_CLAUDE} {model_disp}{C_RESET}{C_DIM}]{C_RESET} "
        f"{C_DIM}⬩{C_RESET} {C_FOLDER}{ICON_FOLDER} {folder}{C_RESET} "
        f"{C_DIM}|{C_RESET} {git_part}"
    )


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


def render_xp_lines(xp: int, meta: dict, equipped: dict, events_on: bool, state: dict):
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

    line2 = (
        f"{title_seg} "
        f"{C_LV}Lv. {level}{C_RESET} "
        f"{C_TOTAL}⬩ {humanize(xp)}{C_RESET} "
        f"{C_DIM}|{C_RESET} {C_META}ctx {meta['ctx']}{C_RESET} "
        f"{C_DIM}|{C_RESET} {C_META}5hr {meta['five']}{C_RESET} "
        f"{C_DIM}|{C_RESET} {C_META}weekly {meta['weekly']}{C_RESET}"
    )
    line3 = (
        f"{C_DIM}[{C_RESET}{bar}{C_DIM}]{C_RESET} {c_pct}{pct:.2f}%{C_RESET} "
        f"{C_NUM}({int(progress):,} / {int(span):,}){C_RESET}"
    )
    if events_on:
        rei = int(state.get("rei", 0))
        line3 += f" {C_DIM}⬩{C_RESET} {C_REI}靈 {rei:,}{C_RESET}"
        rk = reikaku_name(state.get("rei_earned_total", 0))
        if rk:
            line3 += f" {C_REIKAKU}霊格:{rk}{C_RESET}"
        buff = active_buff_or_none(state)
        if buff:
            remain = max(0, int((buff["expires_at"] - time.time()) / 60))
            line3 += (f"  {C_BUFF}{force_emoji(buff['icon'])} {buff['name']} "
                      f"{buff['mult']:g}x {remain}m{C_RESET}")
    return line2, line3


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


# ───────────────────────────────── 主流程 ─────────────────────────────────


def main():
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
    try:
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        data = {}

    cw = data.get("context_window") or {}
    rl = data.get("rate_limits") or {}
    meta = {
        "ctx": _pct_str(cw.get("used_percentage")),
        "five": _pct_str((rl.get("five_hour") or {}).get("used_percentage")),
        "weekly": _pct_str((rl.get("seven_day") or {}).get("used_percentage")),
    }

    cfg = load_config()
    events_on = bool(cfg.get("events_enabled", True))
    state = load_state() if events_on else new_state()
    equipped = state["equipped"] if events_on else dict(DEFAULT_EQUIPPED)

    xp = get_lifetime_tokens()
    l2, l3 = render_xp_lines(xp, meta, equipped, events_on, state)

    sep = "\n" * (1 + max(0, LINE_SPACING))
    sys.stdout.write(sep.join([build_line1(data), l2, l3]))


if __name__ == "__main__":
    main()
