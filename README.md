# 音乐库一键整理工具 (Music Organizer)

自动化整理本地音乐库：重命名文件、归类目录、补全元数据、去除重复。

## 功能特性

- **自动分类**: 歌手/专辑/歌曲 三级目录结构
- **标签补全**: 从文件名、目录结构提取歌手/专辑/年份
- **网络刮削**: 网易云音乐 / MusicBrainz / 酷狗音乐 三源并行补全
- **音频指纹**: AcoustID (chromaprint) 识别未知歌曲
- **歌手归一**: 繁简转换、英文名映射、多别名合并
- **去重**: 按文件大小分组 + 哈希精确比对
- **跨平台**: Windows / Linux / macOS / 群晖 DSM / 飞牛 NAS

## 快速开始

### Windows

```powershell
.\organize.ps1
# 或指定路径
.\organize.ps1 -Source "D:\Music" -Output "D:\Music2"
# 试运行
.\organize.ps1 --dry-run
# 含网络刮削
.\organize.ps1 --scrape
```

### Linux / macOS / NAS

```bash
chmod +x organize.sh
./organize.sh
# 指定路径
SOURCE_DIR=/your/music OUTPUT_DIR=/your/output ./organize.sh
# 试运行
./organize.sh --dry-run
# 含网络刮削
./organize.sh --scrape
```

### Docker (推荐群晖/飞牛等 NAS)

```bash
# 1. 修改 docker-compose.yml 中的 volumes 路径
# 2. 构建并运行
docker-compose up --rm
# 附加参数
docker-compose run --rm music-organizer --scrape --fingerprint
```

## 依赖安装

### Python 依赖

```bash
pip install -r requirements.txt
```

### 系统级依赖（音频指纹识别）

音频指纹功能需要 chromaprint (`fpcalc`) 命令行工具：

| 平台 | 安装命令 |
|------|----------|
| Debian/Ubuntu | `sudo apt install libchromaprint-tools` |
| CentOS/RHEL | `sudo yum install chromaprint` |
| macOS | `brew install chromaprint` |
| Windows | 下载 `fpcalc.exe` 并加入 PATH |
| Docker | 镜像内已预装 |

下载地址: https://github.com/acoustid/chromaprint/releases

## AcoustID API Key 配置

音频指纹识别需要免费的 AcoustID API Key。

**申请**: 访问 https://acoustid.org/api-key 申请免费 KEY

**配置方式（二选一）**:

### 方式1: 环境变量（推荐，不修改代码）

```bash
# Linux / macOS / NAS
export ACOUSTID_API_KEY="你的KEY"

# Windows
set ACOUSTID_API_KEY=你的KEY

# Docker (docker-compose.yml)
environment:
  - ACOUSTID_API_KEY=你的KEY
```

### 方式2: 修改源码

打开 `fingerprint.py`，找到第 42 行：

```python
# >>> 第 42 行: 将 YOUR_ACOUSTID_API_KEY_HERE 替换为你的 AcoustID API Key <<<
DEFAULT_API_KEY = 'YOUR_ACOUSTID_API_KEY_HERE'
```

将 `YOUR_ACOUSTID_API_KEY_HERE` 替换为你的 KEY。

> **注意**: 请勿将你的真实 KEY 提交到 Git 仓库。建议使用环境变量方式。

## 命令行参数

| 参数 | 说明 |
|------|------|
| `-s / --source` | 源音乐目录（默认: `./music`） |
| `-o / --output` | 输出目录（默认: `./music2`） |
| `-m / --name-map` | 歌手名映射文件（默认: `name_map.json`） |
| `--dry-run` | 试运行，不复制文件 |
| `--write-tags` | 将整理后的元数据写入音频标签 |
| `--scrape` | 启用网络刮削补全元数据 |
| `--fingerprint` | 启用音频指纹识别 |
| `--clear-cache` | 清除刮削缓存 |
| `--no-scrape` | 跳过网络刮削 |
| `--version` | 显示版本信息 |

## 平台部署指南

### 飞牛 NAS / 通用 Linux NAS

```bash
cd /vol1/1000/Downloads/music-organizer
git pull
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo apt install libchromaprint-tools  # 指纹识别（可选）
python3 organize_music.py -s /vol1/1000/music -o /vol1/1000/music2 --write-tags --scrape
```

### 群晖 DSM

群晖 DSM 无原生包管理器，**强烈建议使用 Docker 部署**：

1. 在 DSM 的 Container Manager (Docker) 中导入本项目
2. 修改 `docker-compose.yml` 中的 volumes 路径
3. 可选: 设置 `ACOUSTID_API_KEY` 环境变量
4. ARM 架构设备需确认镜像支持

如需原生运行（不推荐）：
1. 在 DSM 套件中心安装 Python3
2. 通过 SSH 安装依赖
3. 注意 DSM 的 Python 版本可能较低

### macOS

```bash
brew install python3 chromaprint
git clone <repo-url>
cd music-organizer/github-release
pip3 install -r requirements.txt
./organize.sh
```

### Windows

1. 安装 Python 3.8+ (勾选 Add to PATH)
2. 下载 `fpcalc.exe` 并加入 PATH (可选，指纹识别用)
3. 打开 PowerShell
4. `pip install -r requirements.txt`
5. `.\organize.ps1`

## 输出文件

| 文件 | 说明 |
|------|------|
| `organize_report.txt` | 整理报告（歌手数/专辑数/歌曲数/去重数等） |
| `artists_found.txt` | 发现的歌手列表 |
| `artist_variants.json` | 歌手名变体映射记录 |
| `netease_cache.json` | 网易云刮削缓存 |
| `scraper_cache.json` | MusicBrainz 刮削缓存 |

## 技术架构

```
organize_music.py (主程序)
├── encoding_fix.py          # 编码修复 + 繁简转换
├── artist_normalizer.py     # 歌手名归一化
├── scraper.py               # MusicBrainz 刮削器
├── netease_scraper.py       # 网易云音乐刮削器
├── kugou_scraper.py         # 酷狗音乐刮削器
├── fingerprint.py           # AcoustID 指纹识别
├── shazam_fingerprint.py    # Shazam 指纹识别（可选）
├── progress.py              # 进度条
├── version.py               # 版本信息
└── name_map.json            # 歌手名映射表
```

## License

GPLv2
