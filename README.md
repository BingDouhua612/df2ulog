# df2ulog

[![CI](https://github.com/BingDouhua612/df2ulog/actions/workflows/ci.yml/badge.svg)](https://github.com/BingDouhua612/df2ulog/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

把 **ArduPilot DataFlash** 日志（`.BIN` 二进制 / Mission Planner 文本 `.log`）转换成 **PX4 ULog v1**（`.ulg`），可直接用 [PlotJuggler](https://plotjuggler.io/) 分析，并可用 [`pyulog`](https://github.com/PX4/pyulog) 回读（`file_corruption == False`）。提供 **CLI** 与 **Windows 桌面 GUI（深色主题、支持批量转换）**。

*English summary: convert ArduPilot DataFlash logs (`.BIN`/`.log`) to PX4 ULog (`.ulg`) with a streaming writer, CLI, optional verification and a PySide6 GUI with batch conversion.*

## 特性

- **两种输入**：DataFlash `.BIN`（pymavlink 读取）与 Mission Planner 文本 `.log`；按内容识别格式，不依赖扩展名。
- **标准输出**：ULog v1（Header / B / I / F / P / A / D / L / S 记录），`pyulog` 与 PlotJuggler 可直接打开。
- **流式转换**：三遍扫描（元数据 → topic 统计 → 流式写数据），大日志内存占用平稳。
- **确定性**：同一输入 + 同一选项，输出**逐字节一致**。
- **可选校验**：`verify` = ULog lint + `pyulog` 回读 + 源文件全量重放比对。
- **多实例 topic**：按 FMTU 的实例列拆分（如 `IMU.00`、`ESC.02`、`MAV.02`）。
- **报告**：纯文本 / JSON 转换报告。
- **GUI（可选）**：拖拽、输出预览、后台转换、进度、结果面板；**批量队列**（逐文件状态/耗时、可取消、已存在默认跳过）。

## 安装

需要 Python ≥ 3.10。CLI 依赖 `pymavlink`；`verify` 额外需要 `pyulog`；GUI 额外需要 `PySide6`。

```bash
git clone https://github.com/BingDouhua612/df2ulog.git
cd df2ulog
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[verify]"        # CLI + verify
# 需要 GUI 时再装：
python -m pip install -e ".[gui,verify]"
```

Windows 下 `df2ulog` / `df2ulog-gui` 命令会安装到虚拟环境的 `Scripts\` 目录。

## CLI 快速开始

```bash
# 二进制 DataFlash
df2ulog logs/flight_01.BIN -o out/flight_01.ulg --report-json out/flight_01.json --verify

# Mission Planner 文本日志（按内容识别）
df2ulog logs/flight_01.log -o out/flight_01_text.ulg

# 只看统计，不写文件
df2ulog inspect logs/flight_02.BIN --limit 30

# 校验已有输出与源文件是否一致
df2ulog verify out/flight_01.ulg --source logs/flight_01.BIN
```

默认输出 = 输入同目录同名 `.ulg`；已存在时退出码 6（用 `--force` 覆盖）。

常用参数：

| 参数 | 说明 |
|---|---|
| `-o/--output PATH` | 输出路径（默认 `<source>.ulg`） |
| `--force` | 覆盖已存在输出 |
| `--verify` | 转换后执行完整校验 |
| `--report PATH` | 写文本报告 |
| `--report-json PATH` | 写 JSON 报告 |
| `--strict` | 字段转换失败 / 无时间戳数据消息 / 尾部截断 → 失败（退出 4） |
| `--allow-time-reset` | 时间回退 >1 s 时 +1 µs 修正并记录高危警告（默认报错） |

退出码：`0` 成功，`3` 输入无效，`4` 转换失败，`5` verify 失败，`6` 输出已存在。

## GUI（Windows 桌面）

```bash
df2ulog-gui
```

![批量队列](docs/images/gui-selected.png)

![批量结果](docs/images/gui-result.png)

操作流程：把一个或多个 `.BIN`/`.log` 拖入窗口（或点"添加文件…"多选）→ 队列表格显示格式/大小/状态 → 选择输出目录（留空 = 每个文件输出到各自目录）→"开始批量转换"。

- **批量**：顺序转换、逐文件进度与耗时、单个失败不影响后续；
- **取消**：当前文件完成后停止后续排队文件；
- **已存在默认跳过**（勾选"覆盖已存在文件"则覆盖）；
- 结果汇总"成功 N · 跳过 M · 失败 K"，失败原因在详情面板列出。

打包为免 Python 的 Windows 应用（可选）：

```powershell
.\scripts\build_gui.ps1                                   # 构建
.\scripts\build_gui.ps1 -SmokeLog D:\logs\flight_01.BIN   # 构建 + 冒烟测试
```

产物在 `dist\df2ulog-gui\`（onedir，需整个目录一起分发）。详见 [docs/GUI.md](docs/GUI.md)。

## 兼容性与限制

- 输出为 **ULog v1**；不生成 ULog v2 独有字段。
- 多实例 topic 依赖固件的 FMTU 实例列信息；没有实例信息时按单实例处理。
- 时间回退默认报错（`--allow-time-reset` 可修正并警告）。
- 不支持的 DF 格式字符或字段转换失败按严格程度报错或降级（见 `--strict`）。
- GUI 面向 Windows（PySide6 跨平台但主要在 Windows 上测试）；CLI 理论跨平台。
- 本项目为实验/分析用途，不对飞行数据本身的正确性负责。

## 文档

- [docs/GUI.md](docs/GUI.md) — GUI 使用与打包
- [docs/MAPPING.md](docs/MAPPING.md) — DF → ULog topic/字段映射
- [docs/FORMAT-NOTES.md](docs/FORMAT-NOTES.md) — ULog v1 写出字节细节
- [docs/DECISIONS.md](docs/DECISIONS.md) — 设计决策记录
- [docs/acceptance.md](docs/acceptance.md) — 自动/人工验收记录

## 开发

```bash
python -m pip install -e ".[dev]"
ruff check src tests
pytest -q -m "not real"        # 合成夹具测试（CI 默认）
```

真实日志验收测试需要本地日志，通过 `tests/real_logs.local.json`（git-ignored）或环境变量 `DF2ULOG_REAL_LOGS_FILE` 提供，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)。第三方依赖许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
