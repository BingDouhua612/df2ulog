# 执行决策记录（docs/DECISIONS.md）

> 本文记录实现过程中遇到的事实/设计冲突及处理方式，不涉及字节格式改动；文中引用的 §/ADR 编号来自内部规格文档（未随公开仓库发布）。

## D-01 夹具消息名长度：`MINI2` / `ISBDX` → `MIN2` / `ISBD`

- **计划原文**：§6.2 F1 使用第二个数据 topic 名 `MINI2`；F4 数据类型名 `ISBDX`。
- **§2 事实**：§2.2.2「`Name:char[4]`」，§6.1 FMT payload 为 `struct.pack("<BB4s16s64s", ...)`，FMT 名称字段固定 4 字节（pymavlink `DFFormat.name` 经 `null_term` 截断）。真实参考日志中该类型名亦为 `ISBD`（`FMT, 166, 207, ISBD, QHHaaa, ...`）。
- **处理**：夹具消息名一律 ≤4 字符：`MINI2`→`MIN2`、`ISBDX`→`ISBD`。数据内容（`QLLc`、`QHHaaa`、D 负载 204 B）与所有验收数值不变。不属于 §2 字节格式冲突，无需改任何格式逻辑。

## D-02 夹具中 21 个格式字符拆分为两个类型

- **计划原文**：§6.2 F2「`all_chars.bin`：附录 A 全部 21 个格式字符」。
- **§2 事实**：§2.2.2「Format ≤16 字符」，FMT 的 `Format` 字段为 `char[16]`。
- **处理**：F2 拆成 `ALLA`（format `QabBhHiIqfdgnNZ`，含 `a`/`b`/`B`/`h`/`H`/`i`/`I`/`q`/`f`/`d`/`g`/`n`/`N`/`Z`）与 `ALLB`（format `QcCeELM`），共覆盖 21 个字符；`a` 仍为 32×int16。逐字节映射逻辑不受影响。

## D-03 【STOP】Task 6 Step 5 门禁：真实 BIN 得到 99 个 topic，而 §2.6 写 97（根因：`MAV` 实为多实例）

- **触发条款**：计划 §0.4 STOP 条件 #2（Task 6 Step 5 真实 BIN 首次端到端 55 F / **97** A / 227,905 D / 1,266 P / 27 L）+ 执行说明「若不符立即停止并报告，不要改实现去凑数」。
- **实测方式**（项目虚拟环境，本地参考日志，未随仓库发布）：
  ```powershell
  python -c "from pathlib import Path; from df2ulog.converter import convert_file, ConversionOptions; r=convert_file(Path('logs/reference.BIN'), ConversionOptions(output=Path('out/ref_bin.ulg'))); print(len(r.topics), r.data_record_count, r.params_written, r.logging_records, r.info_records)"
  python -c "import pyulog; u=pyulog.ULog('out/ref_bin.ulg'); print(u.file_corruption, len(u.data_list))"
  ```
- **实测结果**：`topics 99 / D 227905 / P 1266 / L 27 / info 11`；`lint_ok True`；pyulog：`corrupt False topics 99 D 227905 params 1266 logs 27 info 11`；ULog `F` 记录 55；耗时 20.79 s；`source_tail_bytes=16`。
  - 与 §2.6 相比：D/P/L/INFO/F/固件/GPS 锚点**全部命中**；唯一差异是 **A 记录数 99 ≠ 97**。
- **多出 2 个 topic 的定位**（未改任何实现）：把 99 个 `(ulog_name, multi_id)` 与 §2.6 的推导逐类型对照，唯一超出的是 `MAV`：
  - `MAV` FMTU = `('s#----s-s', 'F-000-C-C')`，`#` 下标 1；`MAV` 列 = (`TimeUS, chan, txp, rxp, rxdp, flags, ss, tf, mgs`) ⇒ 实例列是 `chan`（MAVLink 通道号）。
  - BIN 中 `MAV.chan` 实测计数 `{0: 38, 2: 38, 3: 38}`（首条时间 13,967,085 / 14,072,096 / 14,094,588 µs）。
  - 参考文本日志原始行同样为多通道：`MAV, 13967085, 0, ...`、`MAV, 14072096, 2, ...`、`MAV, 14094588, 3, ...`（`chan ∈ {0,2,3}`）。
  - 其余 15 个多实例类型（IMU/FCNS/FTNS/ESC/STAK/UART/SURF/VIBE/XKT/XKF1–4/XKFS/XKQ）与 §2.6 完全一致；`GPS`、`GPA` 实测**只有实例 0**（各 378 条，`chan`/`I` 全 0）——这同时证伪了 v1「99 来自 GPS/GPA 双实例」的归因。
- **正确性判断**：按 §2.2.5/§2.2.6 的元数据规则（FMTU `UnitIds` 中 `#` 的位置 = 实例列 → multi_id）与 ADR-05（禁止合并实例），`MAV` 必须拆成 3 个 topic。因此 97 + 2 = **99** 是数据本身决定的；§2.6「单实例类型（40 类）……`MAV`……」的表述与其自身的 `#` 规则矛盾，应为计划事实错误。
- **交叉验证**：参考文本 `.log` 用同一实现转换 → `topics 99 / D 227906 / P 1266 / L 27 / info 11 / tail 0`，文本 `MAV` 亦为 3 个实例。两格式 topic 集合一致。
- **未做**：没有把 `MAV` 强制成实例 0（那会违反 ADR-05「禁止合并实例」与数值保真），没有修改 §2.6 数字来“通过”门禁，没有继续 Task 7+。
- **待决定**：
  - **A（推荐）**：接受 99 topic，按 ADR-05 把 §2.6 / §8.2 / 附录 G 的 topic 数从 97 修正为 99（并把 `MAV` 移入多实例表：`MAV`{0,2,3}），然后继续 Task 7–10；PlotJuggler 曲线名相应为 `MAV.00/…`、`MAV.02/…`、`MAV.03/…`。
  - **B**：书面指示对 `MAV` 强制 single-instance（需修改计划契约；与「禁止合并实例」冲突，不推荐）。
- **附带观察（不触发 STOP）**：
  - 参考 BIN 末尾存在 1 个不完整帧：`source_tail_bytes=16`，末 32 B 为 `... 09 a3 95 68 fe c2 10 03 00 00 00 00 c7 e6 73 bc 2e d8 61 39`；已按 F9 行为写入 warnings，不静默丢数据。文本日志 tail=0。§2.6 未把 tail 列为锚点。
  - 当前 9.7 MB BIN 单次转换耗时 20.79 s（含 3 遍遍历），高于 §8.3 的 ≤10 s 目标；待门禁裁决后于 Task 10 Step 3 做性能优化（流式写已满足，优化点在遍历/解析次数）。

### D-03 项目决定（2026-10-18）：**A — 接受 99 topic**

- 决定采用 **A**：以 ADR-05 与真实数据为准，**验收基线 topic 数 = 99**（`MAV{0, 2, 3}` 计入多实例；`GPS/GPA` 仍只有实例 0）。
- 生效范围（本项目内，不改计划文件本身，计划文件按纪律保持原样）：
  - Task 6 Step 5 门禁按 `F 55 / A 99 / D 227,905 / P 1,266 / L 27 / INFO 11 / lint PASS / corrupt False` **判定通过**；
  - Task 9 文本锚点同类修正：**99 topic / 227,906 D / 1,266 P / 27 L**；
  - Task 10 `tests/test_real_logs.py` 与最终报告使用 **99**；
  - PlotJuggler 人工清单中 `MAV` 曲线名为 `MAV.00/…`、`MAV.02/…`、`MAV.03/…`（其余单实例类型仍无后缀）。
- 未采纳 B；`MAV` 不得合并实例、不得丢弃 chan 2/3 数据。

## D-04 进度回调：对冻结签名 `convert_file` 的向后兼容扩展（GUI 功能，2026-10-18）

- **背景**：计划 §4.7 冻结 `convert_file(source_path, options)`；GUI（方案 A：PySide6）需要真实进度条，否则 42 MB 日志转换 20+ 秒只能显示不确定动画。
- **处理**：仅给 `convert_file` 追加 **keyword-only 可选参数**
  `progress_callback: Callable[[str, int], None] | None = None`，回调 `(phase, percent)`，phase ∈ `scan / planned / definitions / write / done`，percent 单调不减、最后必为 `("done", 100)`。
  - `build_conversion_plan` / `iter_output_records` / `verify_ulog` 等其余冻结签名**保持不变**；
  - CLI、verifier、全部既有测试不传该参数，行为完全不变；
  - `.ulg` 字节内容与确定性不变（输出 SHA256 与优化前逐字节一致，由确定性测试覆盖）。
- 对应实施计划：内部实施计划（未随公开仓库发布）。


