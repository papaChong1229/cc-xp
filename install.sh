#!/usr/bin/env bash
# cc-xp 一行安裝 / 更新：下載最新腳本到 ~/.claude/cc-xp/ 並寫好 statusLine + hook + 別名。
#   bash <(curl -fsSL https://raw.githubusercontent.com/papaChong1229/cc-xp/main/install.sh)
set -euo pipefail

BRANCH="${CC_XP_BRANCH:-main}"
RAW="https://raw.githubusercontent.com/papaChong1229/cc-xp/${BRANCH}/plugins/cc-xp/scripts/xp-statusline.py"
DEST_DIR="${HOME}/.claude/cc-xp"
DEST="${DEST_DIR}/xp-statusline.py"

command -v python3 >/dev/null 2>&1 || { echo "需要 python3，請先安裝。" >&2; exit 1; }

echo "↓ 下載 cc-xp（${BRANCH}）..."
mkdir -p "${DEST_DIR}"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "${RAW}" -o "${DEST}"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "${DEST}" "${RAW}"
else
  echo "需要 curl 或 wget。" >&2; exit 1
fi
chmod +x "${DEST}"

echo "⚙ 設定中..."
python3 "${DEST}" install

echo
echo "提示：建議裝 ccusage（bunx ccusage 免安裝）與 Nerd Font。"
