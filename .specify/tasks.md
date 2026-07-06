# Music Organizer v2.0 - 任务清单 (Tasks)

> 状态：草案 (Draft)
> 创建：2026-07-06
> 基于 plan.md 拆解的可执行任务。

## 阶段 1：基础设施

- [ ] T1.1 创建 `logger.py`：基于 logging 模块，支持 --verbose/--quiet
- [ ] T1.2 创建 `config.py`：加载 YAML 配置，命令行参数覆盖
- [ ] T1.3 创建 `config.example.yaml`：完整配置示例
- [ ] T1.4 更新 `requirements.txt`：添加 PyYAML

## 阶段 2：增量整理

- [ ] T2.1 创建 `manifest.py`：记录已整理文件清单（JSON 格式）
- [ ] T2.2 在 `organize_music.py` 中集成 manifest：运行前加载，运行后写入
- [ ] T2.3 添加 `--force` 参数：强制重新整理已存在 manifest 中的文件

## 阶段 3：主流程重构

- [ ] T3.1 将 `organize_music.py` 中的 print 替换为 logger 调用
- [ ] T3.2 集成配置文件加载逻辑
- [ ] T3.3 保持向后兼容：不传配置文件时行为与 v1.x 一致

## 阶段 4：测试

- [ ] T4.1 为 `logger.py` 编写测试
- [ ] T4.2 为 `config.py` 编写测试
- [ ] T4.3 为 `manifest.py` 编写测试
- [ ] T4.4 更新 `test_organize.py`：覆盖增量整理逻辑
- [ ] T4.5 测试覆盖率检查 >= 80%

## 阶段 5：文档与发布

- [ ] T5.1 更新 README.md：配置文件使用说明
- [ ] T5.2 更新 CHANGELOG.md：v2.0 变更记录
- [ ] T5.3 更新 DEPENDENCIES.md：添加 PyYAML
- [ ] T5.4 更新 version.py：版本号改为 2.0.0
- [ ] T5.5 创建 git tag v2.0 + GitHub Release
- [ ] T5.6 在飞牛NAS 实际环境验证

## 验收检查

- [ ] 所有 MUST HAVE 功能实现
- [ ] pytest 全部通过
- [ ] CI 全绿
- [ ] 文档完整
