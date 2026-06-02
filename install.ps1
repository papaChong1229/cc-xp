# cc-xp 一行安裝 / 更新 (Windows PowerShell)：
#   irm https://raw.githubusercontent.com/papaChong1229/cc-xp/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$branch = if ($env:CC_XP_BRANCH) { $env:CC_XP_BRANCH } else { "main" }
$raw = "https://raw.githubusercontent.com/papaChong1229/cc-xp/$branch/plugins/cc-xp/scripts/xp-statusline.py"
$destDir = Join-Path $HOME ".claude\cc-xp"
$dest = Join-Path $destDir "xp-statusline.py"

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Error "需要 Python，請先安裝 python3 並加入 PATH。"; exit 1 }

Write-Host "↓ 下載 cc-xp ($branch)..."
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
Invoke-WebRequest -Uri $raw -OutFile $dest

Write-Host "⚙ 設定中..."
& $py $dest install

Write-Host "`n提示：建議裝 ccusage（bunx ccusage 免安裝）與 Nerd Font。"
