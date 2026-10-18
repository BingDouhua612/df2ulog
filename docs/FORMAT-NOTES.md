# DataFlash → ULog 格式说明（FORMAT-NOTES）

> 版本：2026-10-18。
> 本文记录本工具**写端**的逐记录字节规格、读取端（pyulog 1.2.4 / PlotJuggler 3.6.0）的实测行为，以及 DataFlash/MP 文本日志的格式事实。所有字节事实以真实文件与读取端源码为准。

## 1. ULog v1 文件布局

### 1.1 文件头（16 B）

```
偏移  内容
0..6  magic = 55 4C 6F 67 01 12 35   ("ULog" + 01 12 35)
7     version = 01
8..15 start_timestamp = uint64 LE（微秒，开机时间，不平移）
```

真实 PX4 ULog 样本前 16 B 实测：`55 4c 6f 67 01 12 35 01 6c a1 5d 22 00 00 00 00`
→ version=1、start_ts=576,561,516 µs。

### 1.2 记录头（3 B）

```
uint16 msg_size   payload 字节数（不含这 3 B，小端）
uint8  msg_type   记录类型字符：B I F P A D L S
```

### 1.3 记录类型与 payload 布局（本工具写端规格）

| 类型 | payload 布局 | 本工具写法 |
|---|---|---|
| `B` Flag Bits | `compat_flags[8]` + `incompat_flags[8]` + `appended_offsets[3]×u64` = **40 B** | 第一条记录；全 0；size 必须恰 40 |
| `F` Format | 纯格式串 UTF-8（无 msg_id、无 NUL），每个字段以 `;` 结尾 | `name:uint64_t timestamp;type field;...;`，每个唯一消息名一条 |
| `I` Info | `u8 key_len` + key（`"char[N] <键名>"`）+ value | **全部字符串值**（规避 PlotJuggler 数值 INFO 显示 bug）；按 key 字典序写 |
| `M` Multi Info | — | **不写** |
| `P` Parameter | `u8 key_len` + key（`"float <名称>"`）+ float32 | 初始参数；按名称排序写；非有限值跳过并告警 |
| `Q` Default Parameter | — | **不写**（因此 `B.compat_flags[0]` bit0=0） |
| `A` Add Logged | `u8 multi_id` + `u16 msg_id` + name（无 NUL） | 每个 `(ulog_name, multi_id)` 一条 |
| `R` Remove Logged | — | **不写** |
| `D` Data | `u16 msg_id` + data（data 以 `u64 timestamp` 开头） | 逐条流式写；`msg_size = 2 + 8 + Σ字段字节` |
| `L` Logging | `u8 level('6')` + `u64 timestamp` + UTF-8 文本（无 NUL） | `MSG/EV/MODE` → INFO 级日志 |
| `S` Sync | 8 B magic `2F 73 13 20 25 0C BB 12` | 末尾一条，size=8 |

**记录顺序（冻结）**：`Header → B → I* → F* → P* → A* → (D|L)* → S`。F 必须全部在 A 之前；定义段只允许 `B/I/F/P`；数据段只允许 `D/L/S`。

### 1.4 示例（`QfB`：TimeUS、float X、uint8 Y）

- 格式串：`TOPIC:uint64_t timestamp;float X;uint8_t Y;`
- 字段字节：8 + 4 + 1 = 13 → `payload_size = 13`；D 记录 `msg_size = 2 + 13 = 15`
- **没有任何 `_padding` 字段**。

## 2. 无 padding 设计（ADR-07）

本工具**不写任何 `_padding` 字段**，格式串里只有 `uint64_t timestamp` 和按 DataFlash 列顺序排列的数据字段，D 数据 = 8 B 时间戳 + 字段字节（packed），不做任何对齐。

依据：

- **pyulog 1.2.4** 用 numpy **packed** structured dtype 读取（`np.dtype([...])` 默认 `align=False`），按顺序切片，不需要对齐填充；
- **PlotJuggler 3.6.0** 逐字段按格式串推进指针（`message += size`），并跳过任何名为 `_padding*` 的字段；真实 PX4 日志里的 `_paddingN` 是固件 C 结构体对齐的产物，**不是读取端要求**；
- 这样 `itemsize == max_data_size == 我们写的长度`，天然满足 pyulog 的 D 长度校验（见 §4）。

## 3. 读取端行为：pyulog 1.2.4（校验 oracle）

- 文件头只校验前 7 B magic；`version` 任意（>1 仅打印警告）。
- **D 长度检查是区间**：`data_size < dtype.itemsize` 或 `data_size > max_data_size` → `file_corruption=True`；中间值截断到 `itemsize`。本工具无 padding ⇒ `itemsize == max_data_size ==` 写出的长度，必然通过。
- 订阅解析时删除**尾部** `_padding*` 字段；中段 `_padding*` 保留为普通字段（本工具不产生）。
- `char` 与数组字段按元素展開为独立键：`Name[0]`…`Name[15]`、`x[0]`…`x[31]`；char 元素为 **int8**，数组元素为对应整型/浮点。
- 定义段读到 `A`/`L`/`C` 结束；缺 `B` 不报错；`B` < 40 B 会 `struct.error`，> 40 B 仅警告。
- 置 `file_corruption` 的情形：D 的 msg_id 无订阅、D 长度越界、未知记录类型且 size==0 或 >10000、读取过程 IndexError；**文件中途截断不置 corrupt**。
- `I`/`P` 的 key 必须是 `"<类型> <名称>"`；`char[N]` 的 N 不参与读取（读取剩余字节，遇 NUL 截断）。

本项目 `df2ulog verify` 的 Check 2 即用 pyulog 做回读 oracle。

## 4. 读取端行为：PlotJuggler 3.6.0 ULog 插件

- 只 `memcmp` 前 7 字节 magic，**不校验 version 字节**。
- 定义段：`B` 若出现，`msg_size` 必须**恰为 40**，否则加载失败；定义段读到 `A` 结束；`A` 引用未定义的 `F` 会崩溃 ⇒ 我们保证所有 `F` 在 `A` 前；定义段遇到未知记录类型只打印后跳过。
- 定义段 `P` 只支持 `float` 与 `int32_t`（本工具只写 float）。
- D 记录：前 8 B 当 `uint64` 时间戳；格式串中名为 `timestamp` 的 `uint64_t` 字段在解析格式时被移除；`_padding*` 字段按数组长度跳过；**不校验 D 记录长度**。
- 曲线命名：`topic/field`；数组字段 `topic/field.%02d`（如 `ISBD/x.00`）；多实例命名见 `docs/MAPPING.md` §3。
- `I` 记录：`char[...]` 值取剩余字节；数值类型 INFO 有 bug ⇒ 本工具 INFO 全部用 `char[]` 字符串。
- 数据段忽略 `P/M/Q/C/O/R`；`L` 记录进入 Logs 表；加载后弹 Params / Info / Logs 三张表。

## 5. 本机真实文件实测

- 参考 PX4 `.ulg`：version=1、`B` payload 40 B、`I` 的 `char[40] ver_sw` 值恰 40 B 无 NUL、`A` 示例 `00 00 00 + "action_request"`、文件结尾不一定是 `S`。
- 参考 DataFlash BIN 开头实测：`a3 95 80 80 59 46 4d 54 00 42 42 6e 4e 5a ...`（`0x59`=89 为 FMT.Length），即 FMT 自身 `type=0x80、len=89、format=BBnNZ`。
- 参考 BIN 末尾有 1 个不完整帧（16 B 尾字节）→ 本工具 `source_tail_bytes=16` 并写入 warnings，不静默丢数据；文本日志 tail=0。

## 6. MP 文本 `.log` 格式事实

- `FMT` 定义**交错**出现（每种类型首次使用前），`FMTU/UNIT/MULT` 可能晚于数据（参考日志 ESC 首条数据远早于 ESC 的 FMTU）⇒ 实例/单位必须在**独立全文件扫描**中重建（本工具 pass A / `DataFlashRegistry`），不得依赖 pymavlink 的 `m.fmt.units` / `instance_field`（文本模式会丢失）。
- 文本数值是**物理值**（`c/C/e/E/L` 不再缩放；pymavlink 文本模式 `_apply_multiplier=False`），精度约 7 位有效数字。
- `M` 字段在文本中是字符串（如 `MODE` 的 `AltHold`）；`a` 字段文本形如 `"[0 0 1 ...]"`（32 个数，空格分隔）；`n/N/Z` 为字符串。
- MP 导出的 `MSG` 文本含 `", "` 会被文本 reader 截断（输入固有，文档记录，不视为缺陷）；UNIT 条数与 BIN 可能差 1（参考日志 37 vs 38）。
- 文本精度损失是**输入固有**问题，不做补偿；优先使用 `.BIN`。

## 7. 确定性

- `.ulg` 内**不含**当前时间、随机数、绝对路径（`INFO.source_file` 只写 basename）。
- 同一输入 + 同一选项两次转换 **SHA256 相同**（由确定性测试覆盖，CI 用合成夹具验证）。
- 报告（text/json）可含 `generated_at` 与耗时（非确定性），不影响 `.ulg`。

## 8. 与一个早期私有实现的字节级差异

下表对比某早期私有实现（未公开），仅作设计背景。

| 项 | 旧实现 | 本工具 |
|---|---|---|
| ULog version | 0 | **1** |
| `S` 记录 | 16 B、magic 错误 | **8 B、正确 magic** |
| 多实例 | 合并（55 topic） | **multi_id 拆分（参考日志 99 topic）** |
| `a` 数组 | 补零放大到 64 | **32×int16，不放大** |
| D 记录 | 全量驻留内存 | **流式逐条写，内存有界** |
| 输入格式 | 只 `.BIN` | **`.BIN` + MP 文本 `.log`（按内容识别）** |
| 元数据 | 依赖 `m.fmt.units/instance_field` | **自建注册表（pass A 全文件扫描）** |
| 校验器 | 无独立 lint/JSON 报告 | **`verify`：独立 lint + pyulog + 源重放逐字段比对** |
| 时间戳策略 | 粗糙 | **ADR-08：`TimeUS` 优先、小回退 +1 µs 计数、大回退报错** |
| 布局 | 中部/尾部两套 padding 算法 | **packed、无 padding** |
