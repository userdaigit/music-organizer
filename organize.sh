#!/usr/bin/env bash
# ============================================================
# 音乐库一键整理 v1.2 - 启动脚本（跨平台 Linux/macOS/NAS）
# ============================================================
# 使用方法:
#   1. 将整个 music-organizer 文件夹上传到你的设备
#   2. SSH/终端连接到设备
#   3. cd 到 music-organizer 目录
#   4. chmod +x organize.sh
#   5. ./organize.sh --dry-run    # 试运行
#   6. ./organize.sh              # 正式整理
#   7. ./organize.sh --scrape     # 含网络刮削
#   8. ./organize.sh --scrape --fingerprint  # 全功能
#
# 路径配置:
#   默认使用当前目录下的 music/ 和 music2/
#   可通过环境变量覆盖:
#     SOURCE_DIR=/your/music ./organize.sh
#     OUTPUT_DIR=/your/output ./organize.sh
# ============================================================

set -e

# ===== 路径配置（按你的实际情况修改） =====
SOURCE_DIR="${SOURCE_DIR:-./music}"
OUTPUT_DIR="${OUTPUT_DIR:-./music2}"
CONFIG_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  音乐库一键整理工具 v1.2"
echo "============================================"
echo "  源目录:   $SOURCE_DIR"
echo "  输出目录: $OUTPUT_DIR"
echo "  配置目录: $CONFIG_DIR"
echo "============================================"
echo ""

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装。"
    echo "  请根据系统安装 python3："
    echo "    Debian/Ubuntu: sudo apt install python3 python3-pip"
    echo "    CentOS/RHEL:   sudo yum install python3 python3-pip"
    echo "    macOS:         brew install python3"
    echo "    群晖 DSM:      建议使用 Docker 部署"
    exit 1
fi

# 检查并安装依赖（使用虚拟环境，避免污染系统 Python）
VENV_DIR="$CONFIG_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[创建虚拟环境]"
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "[检查依赖]"
pip install -q -r "$CONFIG_DIR/requirements.txt" 2>/dev/null || true

# 检查 chromaprint（音频指纹功能依赖）
if ! command -v fpcalc &> /dev/null; then
    echo "  [提示] fpcalc 未安装，音频指纹功能不可用"
    echo "  安装方式："
    echo "    Debian/Ubuntu: sudo apt install chromaprint-tools"
    echo "    CentOS/RHEL:   sudo yum install chromaprint-tools"
    echo "    macOS:         brew install chromaprint"
    echo "    Windows:       下载 fpcalc.exe 并加入 PATH"
    echo "    Docker:        镜像内已包含"
else
    echo "  fpcalc: 已安装"
fi

echo ""

# 运行整理脚本
python3 "$CONFIG_DIR/organize_music.py" \
    --source "$SOURCE_DIR" \
    --output "$OUTPUT_DIR" \
    --name-map "$CONFIG_DIR/name_map.json" \
    --write-tags \
    "$@"

echo ""
echo "============================================"
echo "  整理完成！"
echo "  查看报告: $CONFIG_DIR/organize_report.txt"
echo "  歌手列表: $CONFIG_DIR/artists_found.txt"
echo "  变体映射: $CONFIG_DIR/artist_variants.json"
echo "============================================"
