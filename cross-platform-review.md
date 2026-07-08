# 音乐整理工具跨平台兼容性审查报告

**审查日期:** 2026-07-08
**审查范围:** `d:\AITrae\music-organizer\github-release\`
**目标平台:** Windows / Linux (Ubuntu/Debian/CentOS) / macOS / 群晖 DSM

---

## 一、文件路径处理

### 1.1 严重问题: `build_target_path()` 使用硬编码 `/` 作为路径分隔符

**位置:** `organize_music.py` 第 722 行

```python
def build_target_path(meta, is_singleton, artist_canonical):
    # ...
    return f"{artist_dir}/{album_part}/{filename}"  # 硬编码 '/'
```

**影响:**
- Windows 上虽然 Python 的 `Path` 可以处理 `/`，但在纯字符串拼接后作为目标路径的一部分时，逻辑上是错误的（尽管 `Path(output_dir) / f"{target_rel}{ext}"` 在 Windows 上能部分容错，但构建的目标相对路径本身不是跨平台的）
- 更严重的是 `target_rel` 被作为字符串输出到报告、缓存中，在 Windows 环境下显示的路径格式是 Unix 风格

**修复建议:**
```python
from pathlib import Path
# ...
return str(Path(artist_dir) / album_part / filename)
```

### 1.2 严重问题: `organize.ps1` 使用硬编码反斜杠路径

**位置:** `organize.ps1` 第 129-132 行

```powershell
& $pythonCmd "$ConfigDir\organize_music.py" `
    --source $Source `
    --output $Output `
    --name-map "$ConfigDir\name_map.json" `
```

**影响:** PowerShell 中 `"$ConfigDir\organize_music.py"` 的 `\` 在特定上下文（如某些转义场景）下可能出问题，但 PowerShell 通常能处理。不过 `"$ConfigDir\name_map.json"` 中的 `\` 后接 `n` 或其他字符时可能被误解为转义序列。

**修复建议:** 使用 `Join-Path` 或正斜杠：
```powershell
& $pythonCmd (Join-Path $ConfigDir "organize_music.py") `
    --source $Source `
    --output $Output `
    --name-map (Join-Path $ConfigDir "name_map.json") `
```

### 1.3 问题: 默认路径参数为 Unix 绝对路径

**位置:** `organize_music.py` 第 1649-1651 行

```python
parser.add_argument('--source', '-s', default='/music', help='...')
parser.add_argument('--output', '-o', default='/music2', help='...')
```

**影响:** Windows 上直接运行 `python organize_music.py` 会尝试访问 `C:\music`，通常不存在。

**修复建议:** 默认改为当前目录下的相对路径，如 `./music` 和 `./music2`，或检测平台后给出不同的默认值。

### 1.4 问题: `organize.sh` 和 `docker-compose.yml` 硬编码飞牛 NAS 路径

**位置:** `organize.sh` 第 19-20 行，`docker-compose.yml` 第 21-23 行

```bash
SOURCE_DIR="${SOURCE_DIR:-/vol1/1000/music}"
OUTPUT_DIR="${OUTPUT_DIR:-/vol1/1000/music2}"
```

**影响:** 这些路径是飞牛 NAS 的特定挂载点，在其他 Linux 发行版、macOS 或群晖 DSM 上不存在。

**修复建议:** 默认改为 `./music` 和 `./music2`，通过环境变量覆盖。

---

## 二、依赖安装

### 2.1 严重问题: `pyacoustid` 依赖非 Python 原生库 chromaprint

**位置:** `requirements.txt` 第 2 行，`fingerprint.py`

```txt
pyacoustid>=1.3.0
```

**影响:**
- `pyacoustid` 是 Python 包，但它依赖 `chromaprint` C 库或 `fpcalc` 命令行工具
- 这些**不能**通过 `pip` 安装，需要系统包管理器：
  - Ubuntu/Debian: `apt-get install chromaprint-tools`
  - CentOS/RHEL: `yum install chromaprint-tools` (EPEL)
  - macOS: `brew install chromaprint`
  - Windows: 需手动下载 `fpcalc.exe` 并加入 PATH
  - **群晖 DSM: 无包管理器，极难安装，Docker 是唯一可行方案**

**修复建议:**
1. 在 `requirements.txt` 中注释说明：
   ```txt
   mutagen>=1.47.0
   # pyacoustid 需要额外的系统依赖 chromaprint/fpcalc
   # Ubuntu/Debian: apt-get install chromaprint-tools
   # macOS: brew install chromaprint
   # Windows: 下载 https://github.com/acoustid/chromaprint/releases
   pyacoustid>=1.3.0
   opencc-python-reimplemented>=0.1.7
   ```
2. 在代码中优雅降级：指纹模块不可用时仅打印警告，不影响基础整理功能（当前已实现，很好）

### 2.2 问题: `shazamio` 未列入 requirements.txt 且平台兼容性差

**位置:** `shazam_fingerprint.py` 第 99 行

**影响:**
- `shazamio` 依赖 Rust 扩展，在某些 ARM 架构（如群晖部分型号）上可能无法安装
- 要求 Python >= 3.10（`shazam_fingerprint.py` 第 12 行注明）
- 群晖 DSM 默认 Python 版本可能低于 3.10
- 未列入 `requirements.txt`，用户需手动安装

**修复建议:**
1. 在 `requirements.txt` 中加入可选依赖说明：
   ```txt
   # 可选依赖（音频指纹）
   # shazamio>=0.0.1; python_version>="3.10"
   ```
2. 在 README 中说明群晖用户建议使用 Docker 部署

### 2.3 问题: `opencc-python-reimplemented` 与系统 OpenCC 的混淆

**位置:** `requirements.txt` 第 3 行，`encoding_fix.py` 第 34 行

**影响:** `opencc-python-reimplemented` 是纯 Python 实现，跨平台可用，没问题。但如果用户误装 `opencc`（需要 C++ 编译），在 Windows 和群晖上可能编译失败。

**修复建议:** 在文档中明确指定使用 `opencc-python-reimplemented` 而非 `opencc`。

---

## 三、脚本执行

### 3.1 问题: `organize.sh` shebang 非最通用写法

**位置:** `organize.sh` 第 1 行

```bash
#!/bin/bash
```

**影响:**
- 某些最小化系统（如 Alpine Linux、部分嵌入式/群晖环境）可能没有 `/bin/bash`，只有 `/bin/sh` 或 `/usr/bin/env bash`
- 群晖 DSM 的 `/bin/bash` 不一定存在，取决于用户是否通过第三方套件安装

**修复建议:**
```bash
#!/usr/bin/env bash
```

### 3.2 问题: `organize.sh` 依赖 `apt` 命令提示

**位置:** `organize.sh` 第 36, 46 行

```bash
echo "  飞牛NAS 可通过 SSH 执行: sudo apt install python3 python3-pip"
echo "  安装: sudo apt install chromaprint-tools"
```

**影响:**
- CentOS/RHEL 使用 `yum`/`dnf`，Alpine 使用 `apk`，macOS 使用 `brew`
- 群晖 DSM 没有 `apt`

**修复建议:** 改为通用提示：
```bash
echo "  请根据系统安装 python3 和 chromaprint-tools："
echo "    Debian/Ubuntu: sudo apt install python3 python3-pip chromaprint-tools"
echo "    CentOS/RHEL:   sudo yum install python3 python3-pip chromaprint-tools"
echo "    macOS:         brew install python3 chromaprint"
echo "    群晖 DSM:      建议使用 Docker 部署"
```

### 3.3 问题: `organize.sh` 使用 `pip3 install` 无隔离

**位置:** `organize.sh` 第 41 行

```bash
pip3 install -r "$CONFIG_DIR/requirements.txt" 2>/dev/null || true
```

**影响:**
- 直接写入系统 Python 的 site-packages，可能破坏系统包管理
- 在群晖 DSM、macOS 等系统上，系统 Python 通常不建议直接 `pip install`

**修复建议:** 优先使用 `python3 -m pip install --user`，或引导用户使用 `venv`：
```bash
# 创建虚拟环境（如果不存在）
VENV_DIR="$CONFIG_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -r "$CONFIG_DIR/requirements.txt"
python3 "$CONFIG_DIR/organize_music.py" ...
```

### 3.4 问题: `organize.ps1` 文件头有 BOM 且仅限 Windows

**位置:** `organize.ps1` 第 1 行开头有 `﻿` (UTF-8 BOM)

**影响:**
- BOM 在某些编辑器或执行环境中可能产生不可见字符问题
- PowerShell 脚本天然不跨平台（虽然 PowerShell Core 支持 Linux/macOS，但绝大多数 Linux/macOS 用户不会安装）

**修复建议:**
1. 保存为无 BOM 的 UTF-8 文件
2. 为 Linux/macOS 提供一个通用的 Python 入口脚本替代 PowerShell

### 3.5 问题: 缺少统一的跨平台入口脚本

**影响:** 目前有三个入口：
- `organize.sh` — Linux/macOS (Bash)
- `organize.ps1` — Windows (PowerShell)
- `Docker` — 跨平台但配置复杂

缺少一个纯 Python 的跨平台启动器，可以直接在任何有 Python 的平台上运行。

**修复建议:** 提供一个 `run.py` 作为统一的跨平台入口：
```python
#!/usr/bin/env python3
import subprocess, sys, os
# 检查依赖、检查 fpcalc、然后调用 organize_music.py
```

---

## 四、Docker 构建

### 4.1 问题: Dockerfile 基于 Debian，未声明平台支持

**位置:** `Dockerfile` 第 1 行

```dockerfile
FROM python:3.12-slim
```

**影响:**
- `python:3.12-slim` 默认是 `linux/amd64`，在 ARM 架构的群晖（如 DS220j, DS423+ 等）上需要通过 QEMU 模拟或显式使用多平台镜像
- `chromaprint-tools` 和 `ffmpeg` 的 Debian 包在 ARM 上可用，但构建时如果不指定 `--platform` 可能拉取错误架构的镜像

**修复建议:**
1. 在 `docker-compose.yml` 中加入平台声明：
   ```yaml
   services:
     music-organizer:
       platform: linux/amd64  # 或根据主机选择
   ```
2. 在 README 中说明群晖 ARM 设备需要启用 Docker 的 "使用最新镜像" 或手动构建

### 4.2 问题: docker-compose.yml 使用绝对主机路径

**位置:** `docker-compose.yml` 第 21-25 行

```yaml
volumes:
  - /vol1/1000/music:/music:ro
  - /vol1/1000/music2:/music2
  - ./config:/config
```

**影响:** `/vol1/1000/music` 是飞牛 NAS 特定路径，在其他任何系统上都不存在。

**修复建议:** 使用占位符并加注释：
```yaml
volumes:
  # 请修改为你实际的音乐库路径
  - /path/to/your/music:/music:ro
  - /path/to/your/output:/music2
  - ./config:/config
```

---

## 五、编码处理

### 5.1 良好实践: 显式指定 UTF-8 编码

所有 `open()` 调用都显式指定了 `encoding='utf-8'`，这是正确的跨平台做法。

### 5.2 问题: 未处理系统 locale 非 UTF-8 的情况

**位置:** 全局

**影响:** 在某些 Linux 服务器或旧版群晖 DSM 上，系统 locale 可能设置为 `C` 或 `POSIX`（非 UTF-8），此时：
- 终端输出中文可能乱码
- `datetime.now().strftime` 等行为可能异常

**修复建议:** 在入口脚本中设置环境变量：
```python
import os, locale
# 强制使用 UTF-8
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
# 或至少检测并警告
if locale.getpreferredencoding().lower() not in ('utf-8', 'utf8'):
    print("[警告] 系统 locale 非 UTF-8，中文输出可能乱码")
```

### 5.3 问题: `opencc` 未安装时的降级处理正确但无提示

**位置:** `encoding_fix.py` 第 29-38 行

当前实现会静默跳过繁简转换，这没问题，但用户可能不知道繁简转换被禁用了。

**修复建议:** 在启动时检测并提示：
```python
if get_t2s_converter() is False:
    print("[提示] opencc 未安装，繁简转换已禁用（pip install opencc-python-reimplemented）")
```

---

## 六、群晖 DSM 特定问题

### 6.1 严重问题: 群晖 DSM 默认无 Python 3.10+

**影响:**
- 群晖 DSM 7.x 套件中心提供的 Python 版本通常为 3.8 或 3.9
- `shazamio` 要求 Python >= 3.10
- 用户需手动安装 Python 或使用 Docker

**修复建议:**
1. 在 README 的群晖章节中明确指出：
   - DSM 7.0+ 建议通过 Docker 运行
   - 如需原生运行，需安装 Python 3.10+（通过第三方套件或手动编译）
2. 将 `shazamio` 标记为纯可选，当 Python < 3.10 时自动跳过

### 6.2 严重问题: 群晖 DSM 无包管理器，无法安装 chromaprint

**影响:** 群晖 DSM 没有 `apt`/`yum`/`brew`，无法安装 `fpcalc` 或 `ffmpeg`（除非通过第三方套件源如 SynoCommunity 或手动编译）。

**修复建议:**
1. 在 README 中明确推荐群晖用户使用 Docker 部署
2. 提供群晖 Docker 的详细步骤（通过 Container Manager / DSM 7.2+）
3. 对于无法使用 Docker 的 ARM 群晖，说明指纹功能不可用

### 6.3 问题: 群晖内存和 CPU 限制

**影响:**
- 入门级群晖（如 DS220j）只有 512MB ~ 1GB 内存
- 音频指纹识别（特别是 ShazamIO 的 Rust 扩展）和 ffmpeg 处理可能消耗大量内存
- 多线程刮削（`organize_music.py` 第 1262 行 `threading.Thread`）在低内存设备上可能导致 OOM

**修复建议:**
1. 增加 `--workers` / `--threads` 参数控制并发数，默认在低内存环境下设为 1
2. 在启动时检测可用内存（通过 `/proc/meminfo`），内存 < 1GB 时自动禁用指纹和多线程刮削
3. 在文档中说明入门级群晖建议仅使用基础整理功能（不启用 `--scrape` 和 `--fingerprint`）

### 6.4 问题: 群晖文件系统特性

**影响:**
- 群晖使用 ext4 或 btrfs，对长文件名、特殊字符支持良好，与 Linux 一致
- 但群晖的共享文件夹路径通常是 `/volume1/music` 而非 `/vol1/1000/music`

**修复建议:** 文档中纠正群晖默认路径为 `/volume1/music`。

---

## 七、缓存和配置文件位置

### 7.1 问题: 所有缓存/报告使用相对路径（基于 name_map.json 所在目录）

**位置:** `organize_music.py` 第 944-990 行

```python
config_dir = Path(name_map_path).parent
artist_cache_file = config_dir / 'artist_cache.json'
scraper_cache = config_dir / 'scraper_cache.json'
# ...
report_file = config_dir / 'organize_report.txt'
```

**影响:**
- 如果用户从不同的工作目录运行脚本（如通过 cron 定时任务），`name_map.json` 的相对路径解析会变化
- 缓存文件散落在用户指定的配置目录中，没有统一的标准位置

**修复建议:**
1. 采用 XDG Base Directory 规范：
   - Linux/macOS: `~/.cache/music-organizer/` 存放缓存，`~/.config/music-organizer/` 存放配置
   - Windows: `%LOCALAPPDATA%\music-organizer\cache\` 和 `%APPDATA%\music-organizer\config\`
2. 提供一个 `--config-dir` 参数覆盖默认位置
3. 或者至少将默认 `name_map.json` 路径解析为绝对路径后存入缓存文件

### 7.2 问题: 缓存文件无清理机制，可能无限增长

**位置:** 各 scraper 缓存文件

**影响:** 长期使用后，`scraper_cache.json`、`netease_cache.json` 等可能变得非常大。

**修复建议:** 增加缓存文件大小检查或 TTL 机制。

---

## 八、异步与并发问题

### 8.1 问题: `shazam_fingerprint.py` 使用已弃用的 `asyncio.get_event_loop()`

**位置:** `shazam_fingerprint.py` 第 117 行

```python
loop = asyncio.get_event_loop()
```

**影响:**
- Python 3.10+ 中 `asyncio.get_event_loop()` 在没有运行中的事件循环时会发出 DeprecationWarning
- Python 3.12+ 中行为可能进一步改变
- 在 Jupyter Notebook 或其他已存在事件循环的环境中，`loop.is_running()` 的判断逻辑复杂且容易出错

**修复建议:** 使用 `asyncio.run()` 作为统一入口，或采用线程池隔离：
```python
def _shazam_recognize(filepath):
    import asyncio
    from shazamio import Shazam

    async def _recognize():
        shazam = Shazam()
        try:
            return await shazam.recognize(str(filepath))
        except Exception:
            try:
                return await shazam.recognize_song(str(filepath))
            except Exception:
                return None

    # 使用新线程运行异步函数，避免与主线程事件循环冲突
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, _recognize())
        try:
            return _parse_shazam_result(future.result(timeout=30))
        except Exception:
            return None
```

---

## 九、其他平台相关问题

### 9.1 问题: `shutil.copy2` 在跨文件系统时的元数据保留问题

**位置:** `organize_music.py` 第 1516 行

```python
shutil.copy2(meta['source_path'], str(target_path))
```

**影响:**
- `copy2` 尝试保留所有元数据（时间戳、权限等）
- 在跨文件系统复制（如从 ext4 到 btrfs，或 SMB 挂载到本地）时，某些元数据可能无法保留，导致抛出 `OSError`
- 虽然代码已经捕获了 `OSError`，但会打印错误并计入失败

**修复建议:** 如果 `copy2` 因元数据失败，回退到 `copy`：
```python
try:
    shutil.copy2(meta['source_path'], str(target_path))
except OSError:
    shutil.copy(meta['source_path'], str(target_path))
```

### 9.2 问题: `os.path.getsize` 和 `os.walk` 混用 `pathlib.Path`

**位置:** `organize_music.py` 第 851-858 行，第 758 行

```python
for root, dirs, filenames in os.walk(source_dir):
    # ...
    files.append(Path(root) / fn)
```

**影响:** `os.walk` 接受字符串或 Path，但返回字符串。混用本身不会导致错误，但不够一致。有些调用如 `os.path.getsize(s['source_path'])` 中的 `source_path` 已经是 `str`，这没问题。

**修复建议:** 统一使用 `pathlib.Path` 的 `rglob` 替代 `os.walk`：
```python
def scan_audio_files(source_dir):
    files = []
    source = Path(source_dir)
    for f in source.rglob('*'):
        if f.is_file() and not f.name.startswith('.') and f.suffix.lower() in AUDIO_EXTENSIONS:
            files.append(f)
    return files
```

### 9.3 问题: CI 仅测试 Ubuntu

**位置:** `.github/workflows/ci.yml` 第 12 行

```yaml
runs-on: ubuntu-latest
```

**影响:** 无法及时发现 Windows/macOS 上的路径、编码、依赖问题。

**修复建议:** 扩展 CI 矩阵：
```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
    python-version: ["3.9", "3.11", "3.13"]
```

---

## 十、问题严重程度汇总

| 严重程度 | 数量 | 问题类别 |
|---------|------|---------|
| 严重 | 6 | 路径硬编码、chromaprint 非 pip 安装、群晖无 Python 3.10+、群晖无包管理器、shazamio 平台兼容性、Docker 平台未声明 |
| 中等 | 8 | shebang、pip 无隔离、BOM、默认路径 Unix-only、locale 未处理、缓存位置非标准、asyncio 弃用 API、copy2 跨文件系统 |
| 轻微 | 4 | 混用 os/pathlib、apt-only 提示、CI 仅 Ubuntu、opencc 包名混淆 |

---

## 十一、修复优先级建议

### P0（必须修复）
1. `organize_music.py` `build_target_path()` 使用 `Path` 而非字符串拼接 `/`
2. `organize.ps1` 使用 `Join-Path` 替代硬编码 `\`
3. `docker-compose.yml` 将 `/vol1/1000/music` 改为占位符路径
4. `requirements.txt` 增加 chromaprint/fpcalc 的系统依赖说明

### P1（强烈建议）
5. `organize.sh` shebang 改为 `#!/usr/bin/env bash`
6. 提供纯 Python 跨平台入口脚本 `run.py`
7. 默认路径改为相对路径 `./music` 和 `./music2`
8. 增加 `--config-dir` 参数，支持 XDG 标准路径
9. `shazam_fingerprint.py` 移除弃用的 `get_event_loop()` 用法
10. `shutil.copy2` 失败时回退到 `shutil.copy`

### P2（建议优化）
11. CI 扩展至 Windows 和 macOS
12. 启动时检测 locale 并警告
13. 群晖用户专用 Docker 部署文档
14. 低内存环境自动降级（减少线程、禁用指纹）
15. 统一使用 `pathlib.Path.rglob` 替代 `os.walk`

---

## 附录: 各平台部署建议

| 平台 | 推荐部署方式 | 指纹功能 | 注意事项 |
|------|------------|---------|---------|
| Windows | `organize.ps1` 或 Python 直接运行 | 需手动下载 fpcalc.exe | 注意 PowerShell 执行策略 |
| Ubuntu/Debian | `organize.sh` 或 Docker | `apt install chromaprint-tools` | pip 建议加 `--user` |
| CentOS/RHEL | `organize.sh` 或 Docker | `yum install chromaprint-tools` (EPEL) | 同上 |
| macOS | `organize.sh` 或 Python 直接运行 | `brew install chromaprint` | 需安装 Homebrew |
| 群晖 DSM (x86) | **Docker** | Docker 镜像内已包含 | 使用 Container Manager |
| 群晖 DSM (ARM) | **Docker** | 需确认 ARM 镜像可用 | 部分型号性能有限 |
| 飞牛 NAS | `organize.sh` 或 Docker | `apt install chromaprint-tools` | 原生开发目标平台 |
