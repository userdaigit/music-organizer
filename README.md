# Music Organizer - NAS 音乐库一键整理工具

> 飞牛NAS / 群晖 / 威联通等 NAS 音乐文件自动化整理工具

## 功能特点

- **自动整理文件夹结构**：按 `歌手/年份-专辑/歌曲` 层级自动重排
- **feat. 合作方识别**：自动拆分 `歌手A feat. 歌手B` 到标题字段
- **歌手名规范化**：自动合并同一歌手的不同写法（如"周杰伦"和"Jay Chou"）
- **编码修复**：自动检测并修复 GBK/GB18030/BIG5 乱码标签
- **网络刮削**：通过 MusicBrainz API 补全缺失的专辑/年份信息
- **音频指纹识别**：信息全缺时通过 AcoustID 识别歌曲
- **序号保留**：保留原专辑中的轨道序号（如 `01-`）
- **智能分组**：3首以上保留专辑，1-2首降级为单曲（文件名保留专辑名）
- **去重校验**：按文件哈希去重，避免重复文件
- **原文件不动**：整理结果复制到新目录，不修改原始文件

## 目标目录结构

```
/music2/
├── 周杰伦-Jay Chou/
│   ├── 2001-范特西/
│   │   ├── 01-双截棍-周杰伦-范特西.mp3
│   │   ├── 02-简单爱-周杰伦-范特西.mp3
│   │   └── 03-开不了口-周杰伦-范特西.mp3
│   └── 其他/
│       └── 等你下课 feat. 林俊杰-周杰伦-范特西.mp3
├── Adele/
│   └── 其他/
│       └── Hello-Adele-25.flac
└── 林俊杰/
    └── 其他/
        └── 江南-林俊杰-第二天堂.mp3
```

## 快速开始

### 方式一：Python 脚本（推荐 NAS 用户）

```bash
# 1. 安装依赖
pip3 install mutagen pyacoustid

# 2. 试运行（不复制，查看效果）
python3 organize_music.py -s /music -o /music2 --dry-run

# 3. 正式整理
python3 organize_music.py -s /music -o /music2 --write-tags

# 4. 全功能（含网络刮削 + 音频指纹）
python3 organize_music.py -s /music -o /music2 --write-tags --scrape --fingerprint
```

### 方式二：Docker 部署

```bash
# 1. 修改 docker-compose.yml 中的路径
# 2. 试运行
docker compose run --rm music-organizer --dry-run

# 3. 正式运行
docker compose run --rm music-organizer
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-s, --source` | 源音乐目录 | `/music` |
| `-o, --output` | 输出目录 | `/music2` |
| `-m, --name-map` | 中英文名映射 JSON 文件 | `name_map.json` |
| `-n, --dry-run` | 试运行模式（不复制） | 否 |
| `-w, --write-tags` | 补充缺失标签到新文件 | 否 |
| `--scrape` | 启用 MusicBrainz 网络刮削 | 否 |
| `--fingerprint` | 启用音频指纹识别 | 否 |
| `--no-network` | 禁用所有网络功能 | 否 |

## 依赖及许可证

| 依赖 | 用途 | 许可证 |
|------|------|--------|
| [mutagen](https://github.com/quodlibet/mutagen) | 音频标签读写 | GPLv2 |
| [pyacoustid](https://github.com/beetbox/pyacoustid) | 音频指纹识别 | MIT |
| [chromaprint](https://acoustid.org/chromaprint) | 指纹算法库 | LGPLv2.1+ |
| [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API) | 元数据查询 | CC0 (公共领域) |
| [AcoustID API](https://acoustid.org/webservice) | 指纹查询服务 | 免费使用 |

> **注意**：因依赖 mutagen (GPLv2)，本项目必须以 GPLv2 协议开源。

## 命名规则

| 类型 | 规则 | 示例 |
|------|------|------|
| 歌手文件夹 | 中文名-英文名（按需） | `周杰伦-Jay Chou` |
| 专辑文件夹 | 年份-专辑名 | `2001-范特西` |
| 专辑歌曲 | 序号-歌曲名-歌手-专辑 | `01-双截棍-周杰伦-范特西.mp3` |
| 零散歌曲 | 序号-歌曲名-歌手-专辑 | `等你下课-周杰伦-范特西.mp3` |

## 配置文件

### name_map.json（歌手中英文名映射）

首次运行会生成 `artists_found.txt` 列出所有歌手。按需补充映射表：

```json
{
  "周杰伦": "周杰伦-Jay Chou",
  "Jay Chou": "周杰伦-Jay Chou",
  "Adele": "Adele"
}
```

### 歌手名规范化策略

- 中国歌手只有中文名的 → 只用中文名
- 外国歌手只用英文名 → 只用英文名
- 其他语言歌手 → 用原语言名
- 同时有中英文名 → 用"中文名-英文名"

## 外部 API 配置（重要）

本项目可选使用两个免费的外部 API 来增强功能。不配置也能正常使用基础整理功能，但网络刮削和音频指纹识别需要配置后才能工作。

### 1. MusicBrainz API（网络刮削功能，`--scrape` 参数）

MusicBrainz 是一个开放的公共音乐元数据库，本项目通过其 API 查询歌手别名、专辑信息、发行年份等 [$TRAE_REF](https://musicbrainz.org/doc/MusicBrainz_API)。

**使用要求**（参考 [$TRAE_REF](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)）：

| 要求 | 说明 |
|------|------|
| 无需 API Key | MusicBrainz API 免费使用，无需注册 |
| 必须设置 User-Agent | 每个请求必须携带含联系方式的应用标识，否则会被限流甚至封禁 |
| 限流：每秒1次请求 | 本项目已内置1.1秒间隔的自动限流，无需手动控制 |
| 非商业用途免费 | 商业用途需购买商用许可 |

**User-Agent 修改位置**：

代码中默认值为 `MusicOrganizer/1.0 (https://github.com/userdaigit/music-organizer)`。如需修改为你自己的仓库地址：

- 文件 `artist_normalizer.py` 第 140 行：
  ```python
  MB_USER_AGENT = "MusicOrganizer/1.0 (https://github.com/userdaigit/music-organizer)"
  ```
- 文件 `scraper.py` 第 24 行：
  ```python
  MB_USER_AGENT = "MusicOrganizer/1.0 (https://github.com/userdaigit/music-organizer)"
  ```

> **为什么需要改？** MusicBrainz 要求 User-Agent 中包含开发者联系方式（URL 或邮箱），以便在应用异常时联系开发者。不含有效联系方式可能被识别为"匿名"应用而遭限流（503错误）[$TRAE_REF](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)。

### 2. AcoustID API（音频指纹识别功能，`--fingerprint` 参数）

AcoustID 是基于音频指纹的歌曲识别服务。当歌曲文件名和标签都完全缺失信息时，通过音频内容本身识别歌曲 [$TRAE_REF](https://acoustid.org/webservice)。

**使用要求**：

| 要求 | 说明 |
|------|------|
| 需要 API Key | 必须自行申请，免费 |
| 限流：每秒3次请求 | 本项目已内置自动限流 |
| 需要安装 chromaprint | 系统需安装 `fpcalc` 工具（Docker镜像已包含） |

**API Key 申请步骤**：

1. 访问 [acoustid.org/api-key](https://acoustid.org/api-key)
2. 填写应用名称和描述（可随意填写，如"个人音乐整理"）
3. 提交后立即获得 API Key（一串字母数字，如 `abc123def456`）

**API Key 配置位置**（三选一）：

**方式 A：环境变量（推荐，Docker 和脚本通用）**
```bash
# 脚本运行时设置
export ACOUSTID_API_KEY="你的API Key"
python3 organize_music.py -s /music -o /music2 --fingerprint

# Docker 运行时设置
docker compose run --rm -e ACOUSTID_API_KEY="你的API Key" music-organizer --fingerprint
```

**方式 B：docker-compose.yml 文件**
```yaml
environment:
  - ACOUSTID_API_KEY=你的API Key    # 修改第 18 行，替换默认值
```

**方式 C：直接修改 fingerprint.py（不推荐，会暴露在源码中）**
```python
# 文件 fingerprint.py 第 26 行
ACOUSTID_API_KEY = os.environ.get('ACOUSTID_API_KEY', '你的API Key')
```

> **注意**：代码中默认包含一个公开测试 Key `lmv7m8k7Fe`，多人共用会被限流。正式使用请务必替换为自己的 Key。

### 3. chromaprint 安装（音频指纹功能的系统依赖）

音频指纹功能需要系统的 `fpcalc` 工具，安装方式：

| 环境 | 安装命令 |
|------|----------|
| Debian/Ubuntu (飞牛NAS/群晖) | `sudo apt install chromaprint-tools` |
| Docker | Dockerfile 中已自动安装 |
| macOS | `brew install chromaprint` |
| Windows | 下载 [chromaprint releases](https://github.com/acoustid/chromaprint/releases) 并添加到 PATH |

不安装 chromaprint 不影响其他功能，仅 `--fingerprint` 参数不可用。

## 限制说明

1. **MusicBrainz 对华语音乐覆盖率有限**：网络刮削对欧美音乐效果好，华语音乐建议先用 [Music Scraper](https://post.m.smzdm.com/p/117413765/) 刮削标签
2. **"中文名-英文名"无法 100% 全自动**：MusicBrainz 能查到别名的歌手可自动映射，查不到的需手动补充 `name_map.json`

## License

本项目使用 [GPLv2](LICENSE) 协议开源。

## 致谢

- [mutagen](https://github.com/quodlibet/mutagen) - 音频元数据处理
- [pyacoustid](https://github.com/beetbox/pyacoustid) - AcoustID Python 绑定
- [MusicBrainz](https://musicbrainz.org/) - 开放音乐元数据
- [AcoustID](https://acoustid.org/) - 音频指纹识别服务
