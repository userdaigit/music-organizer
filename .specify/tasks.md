# Music Organizer v1.2.0 - 任务清单 (Tasks)

> 状态：已确认
> 创建：2026-07-06
> 基于 plan.md 拆解的可执行任务。

## 阶段 1：AcoustID KEY 有效性检查

- [ ] T1.1 修改 `fingerprint.py`：新增 `DEFAULT_API_KEY` 常量和 `is_default_key()` 函数
- [ ] T1.2 修改 `fingerprint.py`：新增 `validate_api_key()` 函数，发送测试请求验证 KEY
- [ ] T1.3 修改 `fingerprint.py`：`is_available()` 方法增加 KEY 有效性检查
- [ ] T1.4 修改 `organize_music.py`：启动时检测 KEY，无效则提示并跳过指纹识别

## 阶段 2：酷狗音乐刮削源

- [ ] T2.1 创建 `kugou_scraper.py`：`KugouScraper` 类，搜索接口调用
- [ ] T2.2 实现 `search(keyword)` 方法：返回搜索结果列表
- [ ] T2.3 实现 `enrich_metadata(meta)` 方法：根据 title/artist 搜索并补全 album/year
- [ ] T2.4 添加速率限制（0.5 秒/次，避免被禁）
- [ ] T2.5 添加错误处理和超时（5 秒）

## 阶段 3：主流程集成

- [ ] T3.1 修改 `organize_music.py`：初始化酷狗刮削器
- [ ] T3.2 修改刮削步骤：按 MusicBrainz → 酷狗 → AcoustID 链式调用
- [ ] T3.3 添加 `--scrapers` 参数：指定刮削源顺序
- [ ] T3.4 为每个刮削源显示独立进度条

## 阶段 4：测试

- [ ] T4.1 为 `fingerprint.py` 的 KEY 检查函数编写测试
- [ ] T4.2 为 `kugou_scraper.py` 编写测试（mock HTTP 请求）
- [ ] T4.3 更新 `test_organize.py`：覆盖多刮削源链式调用逻辑
- [ ] T4.4 运行全部测试确认通过

## 阶段 5：文档与发布

- [ ] T5.1 更新 `README.md`：多刮削源说明、酷狗接口风险提示
- [ ] T5.2 更新 `CHANGELOG.md`：v1.2.0 变更记录
- [ ] T5.3 更新 `version.py`：版本号改为 1.2.0
- [ ] T5.4 更新 `DEPENDENCIES.md`：酷狗接口说明
- [ ] T5.5 同步 3 个分发目录
- [ ] T5.6 提交、推送、创建 v1.2.0 tag

## 验收检查

- [ ] AcoustID 默认 KEY 检测和提示功能实现
- [ ] 酷狗音乐搜索刮削源实现
- [ ] 多刮削源按优先级链式调用
- [ ] 刮削失败优雅降级
- [ ] pytest 全部通过
- [ ] CI 全绿
- [ ] 文档完整
