# Music Organizer - 项目宪法 (Constitution)

> 本文件定义项目的治理原则与开发规范，指导 v2.0 及后续所有开发。
> 由 Spec Kit SDD 流程生成，手动创建于 2026-07-06。

## 核心原则

### 1. 需求前置
- 所有新功能必须先写 spec（`/speckit.specify`），再写代码
- 需求变更必须更新 spec 后再修改代码
- 禁止 "先写代码再补文档"

### 2. 测试驱动
- 每个新功能必须配套 pytest 测试
- 测试必须在 CI（GitHub Actions）中通过
- 禁止合并未通过测试的代码

### 3. 版本管理
- 版本号集中在 `version.py` 管理
- 遵循语义化版本：MAJOR.MINOR.PATCH
- 每次发布创建 git tag + GitHub Release

### 4. 跨平台兼容
- 核心逻辑必须同时支持 Linux/Windows/macOS
- 路径处理统一使用 `pathlib.Path`
- 启动脚本同时提供 `.sh`（bash）和 `.ps1`（PowerShell）

### 5. 许可证合规
- 所有依赖必须在 `DEPENDENCIES.md` 中声明许可证
- 新增依赖前必须检查与 GPLv2 的兼容性
- 禁止引入不兼容许可证的依赖

### 6. 文档同步
- 代码变更必须同步更新 README.md 和 CHANGELOG.md
- 用户可见的变更必须在 CHANGELOG 中记录
- API 配置变更必须在 README 中说明

### 7. 进度反馈
- 所有耗时操作必须显示进度条
- 进度条样式统一使用 `progress.py` 模块
- 不计算 ETA（预估不准确时不如不显示）

## 技术约束

| 约束 | 说明 |
|------|------|
| Python 版本 | >= 3.9 |
| 核心依赖 | mutagen (GPLv2), pyacoustid (MIT) |
| 可选依赖 | chromaprint (LGPLv2.1+) |
| 许可证 | GPLv2（因 mutagen 传染性） |
| 测试框架 | pytest |
| CI/CD | GitHub Actions |

## 编码规范

- 文件编码：UTF-8
- 缩进：4 空格
- 行宽：100 字符
- 函数文档：三引号 docstring
- 类型提示：公开函数必须有类型提示（v2.0 目标）
