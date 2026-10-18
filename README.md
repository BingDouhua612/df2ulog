# df2ulog

[![CI](https://github.com/BingDouhua612/df2ulog/actions/workflows/ci.yml/badge.svg)](https://github.com/BingDouhua612/df2ulog/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**简体中文** · [English](README.en.md)

把 ArduPilot DataFlash 日志（`.BIN` / Mission Planner `.log`）转成 **PX4 ULog**（`.ulg`），可直接用 PlotJuggler 分析、用 `pyulog` 回读。提供 CLI 和 Windows GUI（支持批量转换）。

![GUI 批量转换](docs/images/gui-result.png)

## 安装

```bash
git clone https://github.com/BingDouhua612/df2ulog.git
cd df2ulog
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[verify]"                          # 需要 GUI 时：pip install -e ".[gui]"
```

## 用法

```bash
df2ulog logs/flight.BIN -o out/flight.ulg --verify
df2ulog logs/flight.log -o out/flight_text.ulg      # 文本日志（按内容识别）
df2ulog inspect logs/flight.BIN --limit 20          # 只看统计
df2ulog verify out/flight.ulg --source logs/flight.BIN
```

常用参数：`-o/--output`、`--force`、`--verify`、`--report/--report-json`、`--strict`、`--allow-time-reset`。
退出码：`0` 成功 / `3` 输入无效 / `4` 转换失败 / `5` verify 失败 / `6` 输出已存在。

**GUI**：运行 `df2ulog-gui`，把多个日志拖入窗口 → "开始批量转换"。支持取消、已存在默认跳过、逐文件状态/耗时与汇总；右上角 **EN / 中文** 可切换界面语言（会记住选择）。

## 文档

- [GUI 使用与打包](docs/GUI.md)
- [格式说明](docs/FORMAT-NOTES.md) · [字段映射](docs/MAPPING.md)
- [设计决策](docs/DECISIONS.md)

## 开发

```bash
pip install -e ".[dev]"
ruff check src tests
pytest -q -m "not real"        # 真实日志测试见 CONTRIBUTING.md
```

## 许可证

[MIT](LICENSE)。第三方依赖许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
