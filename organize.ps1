<#
.SYNOPSIS
    Music Organizer - Windows PowerShell 启动脚本 (v1.1.0)

.DESCRIPTION
    飞牛NAS / 群晖 / 威联通等 NAS 音乐库一键整理工具的 Windows 启动脚本，
    功能类似 organize.sh：
      1. 检查 Python 是否安装
      2. 检查 mutagen 是否安装（未安装则提示 pip install 命令）
      3. 检查 chromaprint (fpcalc) 是否在 PATH 中（仅提示，不强制）
      4. 调用 organize_music.py 进行音乐文件整理

    默认源目录为当前工作目录下的 music 文件夹，输出目录为 music2 文件夹。
    默认启用 --write-tags（与 organize.sh 保持一致）。
    额外传入的参数（如 --dry-run / --scrape / --fingerprint）会原样转发给 organize_music.py。

    若运行时出现"无法加载文件 ... 因为此系统上禁止运行脚本"的执行策略错误，
    请先在 PowerShell 中执行（仅一次，作用于当前用户）：
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

.PARAMETER Source
    源音乐目录。默认为当前工作目录下的 music 文件夹。

.PARAMETER Output
    输出目录。默认为当前工作目录下的 music2 文件夹。

.EXAMPLE
    .\organize.ps1
    使用默认路径 (.\music -> .\music2) 正式整理，并补充缺失标签。

.EXAMPLE
    .\organize.ps1 -Source "D:\Music" -Output "D:\Music2" --dry-run
    指定源目录与输出目录并试运行（不复制文件，仅预览效果）。

.EXAMPLE
    .\organize.ps1 --scrape --fingerprint
    在默认路径下启用网络刮削与音频指纹识别（需配置 API Key 与 fpcalc）。

.NOTES
    Author  : music-organizer
    Version : 1.1.0
    License : GPLv2
.LINK
    https://github.com/userdaigit/music-organizer
#>

# 若遇到执行策略限制（"禁止运行脚本"），请先执行：
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

param(
    [string]$Source = "music",
    [string]$Output = "music2",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

# ===== 路径配置 =====
$ConfigDir = $PSScriptRoot
if (-not $ConfigDir) {
    $ConfigDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# 将相对路径解析为基于当前工作目录的绝对路径（便于显示与排查）
if (-not [System.IO.Path]::IsPathRooted($Source)) {
    $Source = [System.IO.Path]::GetFullPath((Join-Path $PWD $Source))
}
if (-not [System.IO.Path]::IsPathRooted($Output)) {
    $Output = [System.IO.Path]::GetFullPath((Join-Path $PWD $Output))
}

Write-Host "============================================"
Write-Host "  Music Organizer - Windows 启动脚本 v1.1.0"
Write-Host "============================================"
Write-Host "  源目录:   $Source"
Write-Host "  输出目录: $Output"
Write-Host "  配置目录: $ConfigDir"
Write-Host "============================================"
Write-Host ""

# ===== 1. 检查 Python =====
$pythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $pythonCmd = $cmd
        break
    }
}
if (-not $pythonCmd) {
    Write-Host "[错误] 未找到 Python，请先安装 Python 3。" -ForegroundColor Red
    Write-Host "  下载地址: https://www.python.org/downloads/"
    Write-Host "  安装时请勾选 'Add Python to PATH'。"
    exit 1
}
$pyVersion = (& $pythonCmd -c "import sys; print(sys.version.split()[0])" 2>$null)
Write-Host "[环境检查] Python: $pyVersion ($pythonCmd)" -ForegroundColor Green

# ===== 2. 检查 mutagen（核心依赖，必需） =====
$mutagenOk = $false
& $pythonCmd -c "import mutagen" 2>$null
if ($LASTEXITCODE -eq 0) {
    $mutagenOk = $true
}
if (-not $mutagenOk) {
    Write-Host "[错误] 未安装 Python 依赖（音频标签读写必需）。" -ForegroundColor Red
    Write-Host "  请执行以下命令安装依赖:"
    Write-Host "    pip install -r requirements.txt"
    exit 1
}
Write-Host "[环境检查] mutagen: 已安装" -ForegroundColor Green

# ===== 3. 检查 chromaprint (fpcalc) - 仅提示，不强制 =====
$fpcalc = Get-Command fpcalc -ErrorAction SilentlyContinue
if (-not $fpcalc) {
    Write-Host "[提示] 未在 PATH 中找到 fpcalc (chromaprint)，音频指纹识别功能 (--fingerprint) 不可用。" -ForegroundColor Yellow
    Write-Host "  其余整理功能不受影响。"
    Write-Host "  安装方法: 下载 https://github.com/acoustid/chromaprint/releases 的 fpcalc.exe 并加入系统 PATH。"
}
else {
    Write-Host "[环境检查] fpcalc: 已安装 ($($fpcalc.Source))" -ForegroundColor Green
}

Write-Host ""
Write-Host "[启动] 开始整理..." -ForegroundColor Cyan
Write-Host ""

# ===== 运行整理脚本 =====
# 默认启用 --write-tags（与 organize.sh 一致）；--name-map 指向配置目录。
# $RemainingArgs 中的额外参数（如 --dry-run / --scrape / --fingerprint）原样转发。
& $pythonCmd "$ConfigDir\organize_music.py" `
    --source $Source `
    --output $Output `
    --name-map "$ConfigDir\name_map.json" `
    --write-tags `
    @RemainingArgs

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[错误] organize_music.py 执行失败，退出码: $exitCode" -ForegroundColor Red
    exit $exitCode
}

Write-Host ""
Write-Host "============================================"
Write-Host "  整理完成！"
Write-Host "  查看报告: $ConfigDir\organize_report.txt"
Write-Host "  歌手列表: $ConfigDir\artists_found.txt"
Write-Host "  变体映射: $ConfigDir\artist_variants.json"
Write-Host "============================================"
