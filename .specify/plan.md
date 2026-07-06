# Music Organizer v1.2.0 - 技术实现计划 (Plan)

> 状态：已确认
> 创建：2026-07-06
> 基于 spec.md 的规格，给出技术栈与架构选择。

## 技术调研结论

### 酷狗音乐搜索接口

- 接口：`http://mobilecdn.kugou.com/api/v3/search/song?format=json&keyword={关键词}&page=1&pagesize=1`
- 无需认证，直接 HTTP GET
- 返回 JSON：包含歌曲名、歌手名、专辑名、发行时间等
- **风险**：非官方接口，可能随时失效或变更
- **合规**：仅获取元数据（不下载音乐），法律风险较低

### AcoustID API KEY 验证

- 默认测试 KEY：`lmv7m8k7Fe`（代码中硬编码）
- 验证方式：发送 `lookup` 请求，检查返回是否为 `error` 且包含 `invalid API key`
- 有效 KEY：返回正常 JSON（即使无匹配结果）
- 无效 KEY：返回 `{"error": {"message": "invalid API key", "code": 6}}`

### 网易云音乐 / QQ音乐

- 网易云：Binaryify/NeteaseCloudMusicApi 已因版权删库停更（2024年）
- QQ音乐：仅有逆向工程项目，无稳定公开 API
- **结论**：不纳入，待官方 API 可用后再考虑

## 架构设计

```
music-organizer/
├── version.py              # 版本号（已有）
├── progress.py             # 进度条（已有）
├── organize_music.py       # 主流程（修改：集成多刮削源）
├── encoding_fix.py         # 编码修复（已有）
├── artist_normalizer.py    # 歌手规范化（已有）
├── scraper.py              # MusicBrainz 刮削（已有，保留）
├── kugou_scraper.py        # 新增：酷狗音乐刮削源
├── fingerprint.py          # AcoustID 指纹（修改：KEY 有效性检查）
├── tests/                  # 测试（扩展）
└── .specify/               # SDD 产物
```

## 实现方案

### 1. AcoustID KEY 有效性检查（修改 fingerprint.py）

```python
DEFAULT_API_KEY = 'lmv7m8k7Fe'  # 公开测试 KEY

def is_default_key(api_key):
    """检查是否为默认测试 KEY"""
    return api_key == DEFAULT_API_KEY

def validate_api_key(api_key):
    """向 AcoustID 发送测试请求验证 KEY 有效性"""
    # 发送 lookup 请求，检查返回
    # 返回 True/False/None(网络错误)
```

### 2. 酷狗音乐刮削源（新增 kugou_scraper.py）

```python
class KugouScraper:
    SEARCH_URL = "http://mobilecdn.kugou.com/api/v3/search/song"

    def search(self, keyword):
        """搜索歌曲，返回元数据列表"""

    def enrich_metadata(self, meta):
        """根据现有 meta 中的 title/artist 搜索并补全"""
```

### 3. 多刮削源链式调用（修改 organize_music.py）

刮削优先级：
1. MusicBrainz（已有 scraper.py）
2. 酷狗音乐（新增 kugou_scraper.py）
3. AcoustID 指纹（已有 fingerprint.py，增加 KEY 检查）

逻辑：
- 对每首需要刮削的歌曲，按优先级依次尝试
- 任一源返回有效信息即停止
- 所有源都失败则保留原始元数据

## 依赖变更

无新增依赖。酷狗接口为纯 HTTP 请求，使用标准库 `urllib`。

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 酷狗接口失效 | 中文刮削不可用 | 优雅降级，MusicBrainz 仍可用 |
| 酷狗接口变更 | 返回格式变化 | JSON 字段容错，缺字段不报错 |
| AcoustID 验证请求慢 | 启动延迟 | 仅启动时验证一次，超时 3 秒 |
| 默认 KEY 被限流 | 验证返回不确定 | 检查多个条件判断 KEY 状态 |
