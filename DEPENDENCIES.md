# 依赖与第三方组件声明

本项目使用了以下开源组件。发布时需遵守各自许可证要求。

## Python 依赖

| 组件 | 版本 | 许可证 | 仓库地址 | 用途 |
|------|------|--------|----------|------|
| mutagen | >=1.47.0 | GPLv2 | https://github.com/quodlibet/mutagen | 音频标签读写 |
| pyacoustid | >=1.3.0 | MIT | https://github.com/beetbox/pyacoustid | AcoustID 音频指纹识别 |

## 系统依赖（音频指纹功能，可选）

| 组件 | 许可证 | 仓库地址 | 用途 |
|------|--------|----------|------|
| chromaprint | LGPLv2.1+ | https://github.com/acoustid/chromaprint | 音频指纹算法库 |
| ffmpeg | GPLv2+ | https://ffmpeg.org/ | 音频解码（chromaprint 依赖） |

## 外部 API

| 服务 | 许可证 | 使用条款 | 用途 |
|------|--------|----------|------|
| MusicBrainz API | CC0 (公共领域) | 每秒最多1次请求，需设置 User-Agent | 歌手/专辑/歌曲元数据查询 |
| AcoustID API | 免费使用 | 每秒最多3次请求，需 API Key | 音频指纹查询 |

## 许可证兼容性分析

### 问题：mutagen 使用 GPLv2

mutagen 库使用 GPLv2 协议，具有"传染性"：
- 任何使用 mutagen 的衍生作品必须以 GPLv2 协议开源
- 本项目因此也使用 GPLv2 协议

### 兼容性

| 组件 | 许可证 | 与 GPLv2 兼容 |
|------|--------|---------------|
| pyacoustid | MIT | ✅ 兼容 |
| chromaprint | LGPLv2.1+ | ✅ 兼容（动态链接） |
| ffmpeg | GPLv2+ | ✅ 兼容 |

### 结论

本项目可以合法发布到 GitHub，但必须：
1. 使用 GPLv2 协议（已在 LICENSE 文件中声明）
2. 在 README 中注明依赖及许可证
3. 保留所有第三方组件的版权声明

## MusicBrainz API 使用规范

参考: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting

1. **User-Agent**：必须包含应用名称、版本号和联系方式
   - 格式: `ApplicationName/Version (contact-url-or-email)`
   - 本项目使用: `MusicOrganizer/1.0 (https://github.com/userdaigit/music-organizer)`
   - 发布前请修改为你的实际 GitHub 仓库地址

2. **限流**：每个 IP 每秒最多1次请求
   - 本项目已实现自动限流（1.1秒间隔）

3. **避免高峰期**：不要在固定时间点批量查询
