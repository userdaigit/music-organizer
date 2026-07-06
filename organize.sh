#!/bin/bash
# ============================================================
# 飞牛NAS 音乐库一键整理 v1.0 - 启动脚本
# ============================================================
# 使用方法:
#   1. 将整个 music-organizer 文件夹上传到飞牛NAS
#   2. SSH 连接到飞牛NAS
#   3. cd 到 music-organizer 目录
#   4. chmod +x organize.sh
#   5. ./organize.sh --dry-run    # 试运行
#   6. ./organize.sh              # 正式整理
#   7. ./organize.sh --scrape     # 含网络刮削
#   8. ./organize.sh --scrape --fingerprint  # 全功能
# ============================================================

set -e

# ===== 路径配置（按你的实际情况修改） =====
SOURCE_DIR="${SOURCE_DIR:-/vol1/1000/music}"
OUTPUT_DIR="${OUTPUT_DIR:-/vol1/1000/music2}"
CONFIG_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  飞牛NAS 音乐库一键整理工具 v1.0"
echo "============================================"
echo "  源目录:   $SOURCE_DIR"
echo "  输出目录: $OUTPUT_DIR"
echo "  配置目录: $CONFIG_DIR"
echo "============================================"
echo ""

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装。"
    echo "  飞牛NAS 可通过 SSH 执行: sudo apt install python3 python3-pip"
    exit 1
fi

# 检查并安装依赖
echo "[检查依赖]"
pip3 install mutagen pyacoustid 2>/dev/null || true

# 检查 chromaprint（音频指纹功能依赖）
if ! command -v fpcalc &> /dev/null; then
    echo "  [提示] fpcalc 未安装，音频指纹功能不可用"
    echo "  安装: sudo apt install chromaprint-tools"
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