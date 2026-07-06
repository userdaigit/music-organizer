# Music Organizer v2.0 - 技术实现计划 (Plan)

> 状态：草案 (Draft)
> 创建：2026-07-06
> 基于 spec.md 的规格，给出技术栈与架构选择。

## 技术栈

| 层 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.9+ | 已有代码基础 |
| 配置 | PyYAML | 行业标准，可读性好 |
| 日志 | logging（标准库） | 无需额外依赖 |
| 测试 | pytest | 已有套件 |
| CLI | argparse（标准库） | 已有基础，不引入 click/typer |
| Web UI（可选） | Flask | 轻量，NAS 友好 |

## 架构设计

```
music-organizer/
├── version.py              # 版本号（已有）
├── config.py               # 新增：配置文件加载
├── progress.py             # 进度条（已有）
├── organize_music.py       # 主流程（重构）
├── encoding_fix.py         # 编码修复（已有）
├── artist_normalizer.py    # 歌手规范化（已有）
├── scraper.py              # 网络刮削（已有）
├── fingerprint.py          # 音频指纹（已有）
├── manifest.py             # 新增：增量整理清单
├── logger.py               # 新增：日志系统
├── tests/                  # 测试（已有，扩展）
├── config.example.yaml     # 新增：配置示例
└── .specify/               # SDD 产物
```

## 实现顺序

1. **logger.py** - 日志系统（其他模块的基础）
2. **config.py** - 配置文件加载
3. **manifest.py** - 增量整理清单
4. **organize_music.py 重构** - 集成以上三个模块
5. **测试扩展** - 为新模块添加测试
6. **文档更新** - README + CHANGELOG

## 依赖变更

| 新增依赖 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| PyYAML | >=6.0 | MIT | 配置文件解析 |

MIT 与 GPLv2 兼容，无许可证冲突。

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 配置文件向后兼容 | 用户升级后旧命令可能不工作 | 保留命令行参数，配置文件可选 |
| manifest 格式变更 | v2.0 manifest 与 v1.x 不兼容 | v1.x 无 manifest，无影响 |
| Flask 引入安全风险 | NAS 暴露 Web UI | 默认不启动，需显式 `--web` |
