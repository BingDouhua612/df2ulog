# DataFlash → ULog 映射规格（MAPPING）

> 版本：2026-10-18。本文是定稿后的映射/命名/时间/单位/日志规则，供使用者与维护者查阅。

## 1. DataFlash 格式字符 → ULog 类型（附录 A，冻结）

| DF 字符 | pymavlink `__getattr__` 返回值/缩放 | ULog 字段类型 | 说明 |
|---|---|---|---|
| `a` | 二进制 `array('h')` 32 元素；文本 `"[...]"` 字符串 | `int16_t[32]` | 每轴 64 B；不足补 0、超过截断；**禁止补到 64 元素** |
| `b` | int | `int8_t` | |
| `B` | int | `uint8_t` | |
| `h` | int | `int16_t` | |
| `H` | int | `uint16_t` | |
| `i` | int | `int32_t` | |
| `I` | int | `uint32_t` | |
| `q` | int | `int64_t` | |
| `Q` | int | `uint64_t` | 时间戳源 |
| `f` | float32 | `float` | |
| `d` | float64 | `double` | |
| `g` | float16 → Python float | `float` | 加宽到 float32 |
| `n` | str（UTF-8，NUL 截断） | `char[4]` | |
| `N` | str | `char[16]` | |
| `Z` | str | `char[64]` | |
| `c` | int16 ÷100 → float | `float` | pymavlink 已还原，**不得再缩放** |
| `C` | uint16 ÷100 → float | `float` | 同上 |
| `e` | int32 ÷100 → float | `float` | 同上 |
| `E` | uint32 ÷100 → float | `float` | 同上 |
| `L` | int32 ÷1e7 → float | `double` | 经纬度，double 保留精度 |
| `M` | 二进制 int；文本 str | `uint8_t` | 二进制取 `& 0xFF`；文本 `int(str)`，失败抛 `ValueError` |

共 21 个字符；表外字符 → `UnsupportedFormatCharError`（CLI 退出码 4）。**取值一律通过 `m.__getattr__(列名)`**（缩放已由 pymavlink 应用），禁止 `m._elements`。

## 2. 字段（column）映射

1. 字段顺序：`uint64_t timestamp` 第一，其余按 DataFlash `Columns` 顺序（时间戳列本身不重复写入）。
2. 字段名清洗：仅保留 `[A-Za-z0-9_]`，其它替换 `_`；首字符非字母/下划线前缀 `_`；截断到 63 字节。
3. 重名：第二个起追加 `_2`、`_3`…；若清洗结果恰为保留名 `timestamp` → 改名为 `col_timestamp`。
4. 数值保真：每个字段要么按上表写入，要么在报告中显式记录跳过（`field_error:<field>`）；不做静默丢字段。
5. **不写任何 `_padding`**（无对齐填充）。

## 3. topic 命名与多实例（ADR-04/ADR-05）

- 一个 DataFlash 数据类型（一条 FMT 定义）→ 一个 ULog 消息名（一条 `F` 记录）。
- `ulog_name` = DF 名称清洗（规则同字段）；清洗后重名时按 `type_id` 升序，第一个保留原名，其余追加 `_<type_id>`（仍冲突再追加 `_`）。
- **实例列**：`FMTU.UnitIds` 中 `#` 的位置 = 实例列下标（`unit_ids.find('#')`；越界或没有 `#` → 无实例）。实例列原值作为 `A.multi_id`（必须 0..255；非法值跳过并告警，`--strict` 下失败）；实例列本身仍作为普通数据字段保留（保真）。
- **禁止合并实例**：每个 `(ulog_name, multi_id)` 一条 `A` 记录；`msg_id` 按 `(ulog_name, multi_id)` 升序从 0 递增分配。
- 参考日志实例事实（BIN 与文本一致）：

| 类型 | multi_id 集合 | topic 数 |
|---|---|---|
| `IMU`, `FCNS`, `FTNS` | {0,1} | 各 2 |
| `ESC` | {2,3,4,5} | 4 |
| `STAK` | {0..21,255} | 23 |
| `UART` | {0,1,2,3,4,6} | 6 |
| `SURF`, `VIBE`, `XKT` | {0,1} | 各 2 |
| `XKF1`,`XKF2`,`XKF3`,`XKF4`,`XKFS`,`XKQ` | {0,1} | 各 2 |
| `MAV` | {0,2,3}（`chan`） | 3 |
| 其余 39 个单实例类型 | {0} | 各 1 |
| **合计** | | **99** |

> 早期规格 v2 §2.6 原写 97（把 `MAV` 误归为单实例）；经真实数据复核后决定以 ADR-05 为准，**验收基线 = 99 topic**（记录于 `docs/DECISIONS.md` D-03）。`GPS/GPA` 实测只有实例 0。

- PlotJuggler 曲线命名：单实例类型 `topic/field`；某消息名只要存在任一 `multi_id > 0`，该名字**所有**实例都加 `.%02d` 后缀（实例 0 也加）。例：`IMU.00/GyrX`、`IMU.01/GyrX`、`ESC.02/RPM`、`MAV.02/txp`、`GPS/Lat`（无后缀）、`XKF5/…`（无后缀）。

## 4. 时间戳策略（ADR-08）

1. 数据消息时间戳优先 `TimeUS`（uint64 微秒）；无 `TimeUS` 但有 `TimeMS` → `TimeMS × 1000`；两者都没有 → 不是数据 topic，跳过并计数。
2. ULog 文件头 `start_timestamp` = 所有写入 topic 的 `first_ts_us` 最小值；**不平移、不归零**（保留原始开机微秒，UTC 只作 INFO 锚点）。
3. 每个 `(ulog_name, multi_id)` 维护 `last_ts`：
   - `raw <= last_ts` 且回退 `<= 1,000,000 µs` → `raw = last_ts + 1` 并计数（报告 `nudged`）；
   - 回退 `> 1 s` → 默认抛 `TimeOrderError`（退出码 4）；`--allow-time-reset` 时同样 `+1 µs` 并记高危警告。
4. 绝不使用 `m._timestamp` 做时间轴（它含 GPS/UTC 时间基）。

## 5. 单位（仅报告，不写 ULog）

- `UNIT` 的 `Id`（数值字符码）→ `Label`；`MULT` 的 `Id` → 乘子（`float("%.7g" % v)` 规整，与 pymavlink 一致）。
- 每个字段单位 = `unit_lookup[UnitIds[i]]`；若 `MultIds[i]` 有乘子且该格式字符本身无缩放（`c/C/e/E/L/M` 之外）：
  - 乘子在 `MULT_TO_PREFIX`（`0.1→d`、`0.01→c`、`0.001→m`、`1e-6→µ`、`1e-9→n`、`1.0/0.0→""`）→ 加前缀；
  - 其它乘子 → `"<mult:.4g> <label>"`。
- 单位只出现在 `--report`/`--report-json` 的 `topics[].fields[].unit` 中，**不写入 `.ulg`**。

## 6. INFO / 参数 / L 记录（ADR-12）

- **INFO（全部字符串，按 key 字典序）**：`converter`、`source_file`（basename）、`source_format`、`sys_name="ArduPilot"`、`time_base="microseconds since boot; no UTC shift"`；有值时另写 `ver_sw`（固件）、`ver_hw`（板卡）、`frame`、`gps_week`、`gps_ms`、`gps_utc`、`rtc_utc`。参考 BIN 为 **11** 条（无有效 RTC）。
  - GPS UTC：第一条 `GWk>0 且 GMS>0` 的 GPS → `1980-01-06T00:00:00Z + GWk 周 + GMS ms - 18 s 闰秒`。
  - RTC：`Epoch` 换算后年份在 2000..2100 才写 `rtc_utc`。
- **初始参数 `P`**：`--params initial`（默认）把唯一参数按名称排序写 `float <NAME>`；非有限值跳过并告警；`--params none` 不写。参数在日志中变更只报告（`param_conflicts`），不写 ULog 变更记录。
- **`L` 记录**（level='6' INFO；`--no-logging` 关闭）：`MSG` 原文；`EV: <事件名> (id=<Id>)`；`MODE: <名称> (num=<ModeNum>, raw=<Mode>)`（文本 `Mode` 为字符串直接用；整数用 `mavutil.mode_mapping_bynumber(mav_type)` 解析，失败用 `ModeNum`）。不去重。参考 BIN = **27** 条（MSG 14 + EV 11 + MODE 2）。

## 7. 跳过与失败规则（ADR-11/ADR-14）

| 情形 | 处理 |
|---|---|
| `FMT/FMTU/UNIT/MULT/PARM/VER/RTC` | 元数据，不写数据 topic（参数/INFO 另处理） |
| `MSG/EV/MODE` | 写 `L`（除非 `--no-logging`） |
| `FILE/DU32/D32/D16/DFLT` | 跳过并计数 `type:<NAME>` |
| 未知消息类型（无 FMT 定义） | 跳过并计数 `unknown_type` |
| 列数≠格式字符数 / 格式字符不可映射 / 无时间戳列 | 跳过该类型并计数 `unmappable:<reason>` / `no_timestamp`，告警 |
| 实例值非法（非整数/越界） | 跳过该消息并计数 `invalid_instance`，每类型告警一次 |
| 字段转换失败 | 跳过该记录并计数 `field_error:<field>`；`--strict` → 退出 4 |
| 未知格式字符（DFReader 构造期）/ 坏 FMTU | 显式失败：退出 4 / 退出 3（不静默跳过） |
| 过滤后无数据 topic | 失败退出 4 |

退出码：`0` 成功；`2` 参数/用法；`3` 输入不可识别/不可读/坏 FMTU；`4` 转换失败（含未知格式字符、strict、时间大回退、无数据 topic）；`5` verify 失败/pyulog 未安装；`6` 输出已存在（无 `--force`）。

## 8. 文本 `.log` 限制（ADR-09）

- 数值为物理值、约 7 位有效数字，精度损失是**输入固有**；不补偿、不假装无损，建议优先 `.BIN`。
- `MSG` 文本中 `", "` 会被截断（MP 导出/读取固有）。
- `M` 为字符串、`a` 为 `"[...]"`、`FMT` 定义交错、`FMTU/UNIT/MULT` 可能晚于数据；本工具用自建注册表（全文件 pass A）保证实例/单位正确。
- 文本日志末尾无 tail 概念（`source_tail_bytes=0`）。

## 9. 校验（`df2ulog verify`，ADR-15）

1. **独立结构 lint**（不依赖 pyulog）：文件头/magic/version、记录顺序、B 恰 40 B、incompat 全 0、F 先于 A、A 先于 D、D 长度**精确等于**订阅 `payload_size`、每 msg_id 时间戳单调非降、S 恰 8 B、至少 1 A 与 1 D。
2. **pyulog 回读**：无异常、`file_corruption is False`、`len(data_list) > 0`。
3. **有 `--source`**：用同一 plan 重建并重放源文件，逐 topic/逐字段精确比对（整数精确；float32 按位；double 精确；char int8；时间戳精确；参数、`L` 记录、INFO 必需键）。
4. **无 source 有 `--report-json`**：比对 topic 集合/条数/首末时间戳/参数数/L 记录数。
5. 每项输出 PASS/FAIL 与差异样例（最多 20 条）；CLI 退出码 0/5。**不允许只检查"pyulog 能打开"**。
