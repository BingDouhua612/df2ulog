# 验收记录

本文件记录可复现的自动验收方式与人工验收清单。**真实飞行日志、个人路径和本地
验收数据不随仓库发布**；需要真实日志的测试通过本地配置启用，否则自动跳过。

## 1. 自动验收（与 CI 等价）

| 检查 | 命令 | 期望 |
|---|---|---|
| Lint | `ruff check src tests` | `All checks passed!` |
| 合成夹具测试 | `pytest -q -m "not real"` | 全部通过 |
| 真实日志（可选） | 配置 `tests/real_logs.local.json` 后 `pytest -q -m real` | 通过；未配置时自动 skip |
| GUI 测试（可选） | `QT_QPA_PLATFORM=offscreen pytest tests/test_gui_app.py tests/test_gui_batch.py -q` | 全部通过（未装 PySide6 时 skip） |

覆盖范围：ULog codec / writer / lint、DataFlash 与文本日志源解析、DF→ULog
mapping、converter、报告、verifier、CLI、GUI（offscreen）与 GUI 批量后端。

## 2. 转换正确性

- 合成夹具：转换 → ULog lint 通过 → `pyulog` 回读 `file_corruption == False`；
- 文本/BIN 同源一致性：同一夹具的两种格式转换结果一致（测试覆盖）；
- 确定性：同一输入 + 同一选项两次转换输出逐字节一致；
- 真实日志（可选）：在本地配置后做结构、lint、回读与全量重放校验；具体
  飞行数据相关锚点仅维护者在本地保存，不进入公开仓库。

## 3. GUI 自动验收

- offscreen 测试：窗口构建、深色主题、输出预览、拖拽高亮、批量队列、
  取消、批量结果与汇总；
- 端到端：真实线程转换合成夹具 → 进度到达 100% → 产出 `.ulg`。

## 4. 人工验收清单（发布前在本机执行）

1. CLI：`df2ulog <本地日志> -o out/test.ulg --verify` → 退出码 0。
2. GUI：`df2ulog-gui` → 拖入多个日志 → 队列显示格式/大小/状态；开始批量
   转换 → 逐行显示成功/跳过，底部汇总正确。
3. 覆盖策略：不勾选"覆盖已存在文件"重跑 → 已存在输出标记"跳过"；勾选后
   重跑 → 覆盖成功。
4. 取消：批量进行中点"取消" → 当前文件完成后停止，后续标记"已取消"。
5. PlotJuggler 3.6.0（或更新版本）打开 `out/test.ulg` → 可加载、无报错、
   曲线可见。
6. 打包版（可选）：`scripts/build_gui.ps1 -SmokeLog <本地日志>` →
   `PACKAGING SMOKE PASS`。

结论栏：☐ PASS　☐ FAIL　　日期：__________　　签字：__________
