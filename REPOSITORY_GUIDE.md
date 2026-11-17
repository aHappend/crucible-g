# Crucible-G — Repository guide / 文件导航

[English](README.md) · [简体中文](README.zh-CN.md)

Documentation inventory checked on 2026-11-17, against repository base `d4d7651ee2183ed48f560a9476d29df42e0819eb`.

## Reading the inventory / 阅读方法

This is a path-level index, not a new experiment or a recertification. Each measurement belongs to the exact linked record and directory. Different copies of a chip can contain different source revisions and results. A recorded pass does not imply that another copy, model size, software stack or board image passed.

本页按实际路径列出交付物，不代表新实验或重新签核。同名芯片的多份目录可能有不同源码和结果；一份记录的通过不外推到其他副本、模型规模、软件栈或板卡镜像。

## Source, tests and reports / 源码、测试与报告

| Existing directory | Source / constraints | Public tests / technical documents | Reports |
| --- | --- | --- | --- |
| [`chips/crucible_g1/`](chips/crucible_g1/) | [`chips/crucible_g1/rtl/`](chips/crucible_g1/rtl/) | [`chips/crucible_g1/tests/`](chips/crucible_g1/tests/) · [`chips/crucible_g1/design/`](chips/crucible_g1/design/) | [`chips/crucible_g1/REPORT.md`](chips/crucible_g1/REPORT.md) · [`chips/crucible_g1/REPORT.pdf`](chips/crucible_g1/REPORT.pdf) · [`chips/crucible_g1/SHOWCASE_REPORT.pdf`](chips/crucible_g1/SHOWCASE_REPORT.pdf) · [`chips/crucible_g1/SHOWCASE_REPORT.zh-CN.pdf`](chips/crucible_g1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/crucible_g2/`](chips/crucible_g2/) | [`chips/crucible_g2/rtl/`](chips/crucible_g2/rtl/) | [`chips/crucible_g2/tests/`](chips/crucible_g2/tests/) · [`chips/crucible_g2/design/`](chips/crucible_g2/design/) | [`chips/crucible_g2/REPORT.md`](chips/crucible_g2/REPORT.md) · [`chips/crucible_g2/REPORT.pdf`](chips/crucible_g2/REPORT.pdf) · [`chips/crucible_g2/SHOWCASE_REPORT.pdf`](chips/crucible_g2/SHOWCASE_REPORT.pdf) · [`chips/crucible_g2/SHOWCASE_REPORT.zh-CN.pdf`](chips/crucible_g2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/crucible_g3/`](chips/crucible_g3/) | [`chips/crucible_g3/rtl/`](chips/crucible_g3/rtl/) | [`chips/crucible_g3/tests/`](chips/crucible_g3/tests/) · [`chips/crucible_g3/design/`](chips/crucible_g3/design/) | [`chips/crucible_g3/REPORT.md`](chips/crucible_g3/REPORT.md) · [`chips/crucible_g3/REPORT.pdf`](chips/crucible_g3/REPORT.pdf) · [`chips/crucible_g3/SHOWCASE_REPORT.pdf`](chips/crucible_g3/SHOWCASE_REPORT.pdf) · [`chips/crucible_g3/SHOWCASE_REPORT.zh-CN.pdf`](chips/crucible_g3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/crucible_g4/`](chips/crucible_g4/) | [`chips/crucible_g4/rtl/`](chips/crucible_g4/rtl/) | [`chips/crucible_g4/tests/`](chips/crucible_g4/tests/) · [`chips/crucible_g4/design/`](chips/crucible_g4/design/) | [`chips/crucible_g4/REPORT.md`](chips/crucible_g4/REPORT.md) · [`chips/crucible_g4/REPORT.pdf`](chips/crucible_g4/REPORT.pdf) · [`chips/crucible_g4/SHOWCASE_REPORT.pdf`](chips/crucible_g4/SHOWCASE_REPORT.pdf) · [`chips/crucible_g4/SHOWCASE_REPORT.zh-CN.pdf`](chips/crucible_g4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/crucible_g5/`](chips/crucible_g5/) | [`chips/crucible_g5/rtl/`](chips/crucible_g5/rtl/) | [`chips/crucible_g5/tests/`](chips/crucible_g5/tests/) · [`chips/crucible_g5/design/`](chips/crucible_g5/design/) | [`chips/crucible_g5/REPORT.md`](chips/crucible_g5/REPORT.md) · [`chips/crucible_g5/REPORT.pdf`](chips/crucible_g5/REPORT.pdf) · [`chips/crucible_g5/SHOWCASE_REPORT.pdf`](chips/crucible_g5/SHOWCASE_REPORT.pdf) · [`chips/crucible_g5/SHOWCASE_REPORT.zh-CN.pdf`](chips/crucible_g5/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible-g1/`](crucible-g1/) | [`crucible-g1/rtl/`](crucible-g1/rtl/) | [`crucible-g1/tests/`](crucible-g1/tests/) · [`crucible-g1/design/`](crucible-g1/design/) | [`crucible-g1/REPORT.md`](crucible-g1/REPORT.md) · [`crucible-g1/REPORT.pdf`](crucible-g1/REPORT.pdf) · [`crucible-g1/SHOWCASE_REPORT.pdf`](crucible-g1/SHOWCASE_REPORT.pdf) · [`crucible-g1/SHOWCASE_REPORT.zh-CN.pdf`](crucible-g1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible-g2/`](crucible-g2/) | [`crucible-g2/rtl/`](crucible-g2/rtl/) | [`crucible-g2/tests/`](crucible-g2/tests/) · [`crucible-g2/design/`](crucible-g2/design/) | [`crucible-g2/REPORT.md`](crucible-g2/REPORT.md) · [`crucible-g2/REPORT.pdf`](crucible-g2/REPORT.pdf) · [`crucible-g2/SHOWCASE_REPORT.pdf`](crucible-g2/SHOWCASE_REPORT.pdf) · [`crucible-g2/SHOWCASE_REPORT.zh-CN.pdf`](crucible-g2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible-g3/`](crucible-g3/) | [`crucible-g3/rtl/`](crucible-g3/rtl/) | [`crucible-g3/tests/`](crucible-g3/tests/) · [`crucible-g3/design/`](crucible-g3/design/) | [`crucible-g3/REPORT.md`](crucible-g3/REPORT.md) · [`crucible-g3/REPORT.pdf`](crucible-g3/REPORT.pdf) · [`crucible-g3/SHOWCASE_REPORT.pdf`](crucible-g3/SHOWCASE_REPORT.pdf) · [`crucible-g3/SHOWCASE_REPORT.zh-CN.pdf`](crucible-g3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible-g4/`](crucible-g4/) | [`crucible-g4/rtl/`](crucible-g4/rtl/) | [`crucible-g4/tests/`](crucible-g4/tests/) · [`crucible-g4/design/`](crucible-g4/design/) | [`crucible-g4/REPORT.md`](crucible-g4/REPORT.md) · [`crucible-g4/REPORT.pdf`](crucible-g4/REPORT.pdf) · [`crucible-g4/SHOWCASE_REPORT.pdf`](crucible-g4/SHOWCASE_REPORT.pdf) · [`crucible-g4/SHOWCASE_REPORT.zh-CN.pdf`](crucible-g4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible-g5/`](crucible-g5/) | [`crucible-g5/rtl/`](crucible-g5/rtl/) | [`crucible-g5/tests/`](crucible-g5/tests/) · [`crucible-g5/design/`](crucible-g5/design/) | [`crucible-g5/REPORT.md`](crucible-g5/REPORT.md) · [`crucible-g5/REPORT.pdf`](crucible-g5/REPORT.pdf) · [`crucible-g5/SHOWCASE_REPORT.pdf`](crucible-g5/SHOWCASE_REPORT.pdf) · [`crucible-g5/SHOWCASE_REPORT.zh-CN.pdf`](crucible-g5/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible_g1/`](crucible_g1/) | [`crucible_g1/rtl/`](crucible_g1/rtl/) | [`crucible_g1/tests/`](crucible_g1/tests/) · [`crucible_g1/design/`](crucible_g1/design/) | [`crucible_g1/REPORT.md`](crucible_g1/REPORT.md) · [`crucible_g1/REPORT.pdf`](crucible_g1/REPORT.pdf) · [`crucible_g1/SHOWCASE_REPORT.pdf`](crucible_g1/SHOWCASE_REPORT.pdf) · [`crucible_g1/SHOWCASE_REPORT.zh-CN.pdf`](crucible_g1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible_g2/`](crucible_g2/) | [`crucible_g2/rtl/`](crucible_g2/rtl/) | [`crucible_g2/tests/`](crucible_g2/tests/) · [`crucible_g2/design/`](crucible_g2/design/) | [`crucible_g2/REPORT.md`](crucible_g2/REPORT.md) · [`crucible_g2/REPORT.pdf`](crucible_g2/REPORT.pdf) · [`crucible_g2/SHOWCASE_REPORT.pdf`](crucible_g2/SHOWCASE_REPORT.pdf) · [`crucible_g2/SHOWCASE_REPORT.zh-CN.pdf`](crucible_g2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible_g3/`](crucible_g3/) | [`crucible_g3/rtl/`](crucible_g3/rtl/) | [`crucible_g3/tests/`](crucible_g3/tests/) · [`crucible_g3/design/`](crucible_g3/design/) | [`crucible_g3/REPORT.md`](crucible_g3/REPORT.md) · [`crucible_g3/REPORT.pdf`](crucible_g3/REPORT.pdf) · [`crucible_g3/SHOWCASE_REPORT.pdf`](crucible_g3/SHOWCASE_REPORT.pdf) · [`crucible_g3/SHOWCASE_REPORT.zh-CN.pdf`](crucible_g3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible_g4/`](crucible_g4/) | [`crucible_g4/rtl/`](crucible_g4/rtl/) | [`crucible_g4/tests/`](crucible_g4/tests/) · [`crucible_g4/design/`](crucible_g4/design/) | [`crucible_g4/REPORT.md`](crucible_g4/REPORT.md) · [`crucible_g4/REPORT.pdf`](crucible_g4/REPORT.pdf) · [`crucible_g4/SHOWCASE_REPORT.pdf`](crucible_g4/SHOWCASE_REPORT.pdf) · [`crucible_g4/SHOWCASE_REPORT.zh-CN.pdf`](crucible_g4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`crucible_g5/`](crucible_g5/) | [`crucible_g5/rtl/`](crucible_g5/rtl/) | [`crucible_g5/tests/`](crucible_g5/tests/) · [`crucible_g5/design/`](crucible_g5/design/) | [`crucible_g5/REPORT.md`](crucible_g5/REPORT.md) · [`crucible_g5/REPORT.pdf`](crucible_g5/REPORT.pdf) · [`crucible_g5/SHOWCASE_REPORT.pdf`](crucible_g5/SHOWCASE_REPORT.pdf) · [`crucible_g5/SHOWCASE_REPORT.zh-CN.pdf`](crucible_g5/SHOWCASE_REPORT.zh-CN.pdf) |

## Public result records / 公开结果记录

Status and numbers below are transcribed only from the linked record. Functional simulation, generic synthesis, standalone/virtual-pin timing, bridge connectivity, workload readback and system-software execution are separate scopes. Missing entries mean that this index found no matching public record at that path, not that an experiment failed or never occurred.

下表状态与数值只来自对应文件。功能仿真、通用综合、独立 IP／虚拟引脚时序、桥接连通性、工作负载读回和系统软件执行分别解释；未列出不等于判定失败或从未做过。

| Exact directory | Record | Recorded result and scope |
| --- | --- | --- |
| `chips/crucible_g1` | [`chips/crucible_g1/evidence/verification-receipts.json`](chips/crucible_g1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g1` | [`chips/crucible_g1/evidence/rtl-timing-lint.json`](chips/crucible_g1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/crucible_g1` | [`chips/crucible_g1/evidence/quartus-sta.json`](chips/crucible_g1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `102.88`; setup slack ns: `0.28`; hold slack ns: `0.039` |
| `chips/crucible_g1` | [`chips/crucible_g1/evidence/ppa-resource-summary.json`](chips/crucible_g1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g1` | [`chips/crucible_g1/evidence/board-hil.json`](chips/crucible_g1/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `chips/crucible_g2` | [`chips/crucible_g2/evidence/verification-receipts.json`](chips/crucible_g2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g2` | [`chips/crucible_g2/evidence/rtl-timing-lint.json`](chips/crucible_g2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/crucible_g2` | [`chips/crucible_g2/evidence/quartus-sta.json`](chips/crucible_g2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `115.49`; setup slack ns: `1.341`; hold slack ns: `0.036` |
| `chips/crucible_g2` | [`chips/crucible_g2/evidence/ppa-resource-summary.json`](chips/crucible_g2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g2` | [`chips/crucible_g2/evidence/board-hil.json`](chips/crucible_g2/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `chips/crucible_g3` | [`chips/crucible_g3/evidence/verification-receipts.json`](chips/crucible_g3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g3` | [`chips/crucible_g3/evidence/rtl-timing-lint.json`](chips/crucible_g3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/crucible_g3` | [`chips/crucible_g3/evidence/quartus-sta.json`](chips/crucible_g3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `115.77`; setup slack ns: `1.362`; hold slack ns: `0.044` |
| `chips/crucible_g3` | [`chips/crucible_g3/evidence/ppa-resource-summary.json`](chips/crucible_g3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g3` | [`chips/crucible_g3/evidence/board-hil.json`](chips/crucible_g3/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `chips/crucible_g4` | [`chips/crucible_g4/evidence/verification-receipts.json`](chips/crucible_g4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g4` | [`chips/crucible_g4/evidence/rtl-timing-lint.json`](chips/crucible_g4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/crucible_g4` | [`chips/crucible_g4/evidence/quartus-sta.json`](chips/crucible_g4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `116.84`; setup slack ns: `1.441`; hold slack ns: `0.046` |
| `chips/crucible_g4` | [`chips/crucible_g4/evidence/ppa-resource-summary.json`](chips/crucible_g4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g4` | [`chips/crucible_g4/evidence/board-hil.json`](chips/crucible_g4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `chips/crucible_g5` | [`chips/crucible_g5/evidence/verification-receipts.json`](chips/crucible_g5/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g5` | [`chips/crucible_g5/evidence/rtl-timing-lint.json`](chips/crucible_g5/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/crucible_g5` | [`chips/crucible_g5/evidence/quartus-sta.json`](chips/crucible_g5/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `132.26`; setup slack ns: `2.439`; hold slack ns: `0.039` |
| `chips/crucible_g5` | [`chips/crucible_g5/evidence/ppa-resource-summary.json`](chips/crucible_g5/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/crucible_g5` | [`chips/crucible_g5/evidence/board-hil.json`](chips/crucible_g5/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `crucible-g1` | [`crucible-g1/evidence/verification-receipts.json`](crucible-g1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g1` | [`crucible-g1/evidence/rtl-timing-lint.json`](crucible-g1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible-g1` | [`crucible-g1/evidence/quartus-sta.json`](crucible-g1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `102.88`; setup slack ns: `0.28`; hold slack ns: `0.039` |
| `crucible-g1` | [`crucible-g1/evidence/ppa-resource-summary.json`](crucible-g1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g1` | [`crucible-g1/evidence/board-hil.json`](crucible-g1/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `crucible-g2` | [`crucible-g2/evidence/verification-receipts.json`](crucible-g2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g2` | [`crucible-g2/evidence/rtl-timing-lint.json`](crucible-g2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible-g2` | [`crucible-g2/evidence/quartus-sta.json`](crucible-g2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `115.49`; setup slack ns: `1.341`; hold slack ns: `0.036` |
| `crucible-g2` | [`crucible-g2/evidence/ppa-resource-summary.json`](crucible-g2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g2` | [`crucible-g2/evidence/board-hil.json`](crucible-g2/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `crucible-g3` | [`crucible-g3/evidence/verification-receipts.json`](crucible-g3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g3` | [`crucible-g3/evidence/rtl-timing-lint.json`](crucible-g3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible-g3` | [`crucible-g3/evidence/quartus-sta.json`](crucible-g3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `115.77`; setup slack ns: `1.362`; hold slack ns: `0.044` |
| `crucible-g3` | [`crucible-g3/evidence/ppa-resource-summary.json`](crucible-g3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g3` | [`crucible-g3/evidence/board-hil.json`](crucible-g3/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `crucible-g4` | [`crucible-g4/evidence/verification-receipts.json`](crucible-g4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g4` | [`crucible-g4/evidence/rtl-timing-lint.json`](crucible-g4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible-g4` | [`crucible-g4/evidence/quartus-sta.json`](crucible-g4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `116.84`; setup slack ns: `1.441`; hold slack ns: `0.046` |
| `crucible-g4` | [`crucible-g4/evidence/ppa-resource-summary.json`](crucible-g4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g4` | [`crucible-g4/evidence/board-hil.json`](crucible-g4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `crucible-g5` | [`crucible-g5/evidence/verification-receipts.json`](crucible-g5/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g5` | [`crucible-g5/evidence/rtl-timing-lint.json`](crucible-g5/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible-g5` | [`crucible-g5/evidence/quartus-sta.json`](crucible-g5/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `132.26`; setup slack ns: `2.439`; hold slack ns: `0.039` |
| `crucible-g5` | [`crucible-g5/evidence/ppa-resource-summary.json`](crucible-g5/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible-g5` | [`crucible-g5/evidence/board-hil.json`](crucible-g5/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `crucible_g1` | [`crucible_g1/evidence/verification-receipts.json`](crucible_g1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g1` | [`crucible_g1/evidence/rtl-timing-lint.json`](crucible_g1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible_g1` | [`crucible_g1/evidence/quartus-sta.json`](crucible_g1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `102.88`; setup slack ns: `0.28`; hold slack ns: `0.039` |
| `crucible_g1` | [`crucible_g1/evidence/ppa-resource-summary.json`](crucible_g1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g1` | [`crucible_g1/evidence/board-hil.json`](crucible_g1/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `crucible_g2` | [`crucible_g2/evidence/verification-receipts.json`](crucible_g2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g2` | [`crucible_g2/evidence/rtl-timing-lint.json`](crucible_g2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible_g2` | [`crucible_g2/evidence/quartus-sta.json`](crucible_g2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `115.49`; setup slack ns: `1.341`; hold slack ns: `0.036` |
| `crucible_g2` | [`crucible_g2/evidence/ppa-resource-summary.json`](crucible_g2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g2` | [`crucible_g2/evidence/board-hil.json`](crucible_g2/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `crucible_g3` | [`crucible_g3/evidence/verification-receipts.json`](crucible_g3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g3` | [`crucible_g3/evidence/rtl-timing-lint.json`](crucible_g3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible_g3` | [`crucible_g3/evidence/quartus-sta.json`](crucible_g3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `115.77`; setup slack ns: `1.362`; hold slack ns: `0.044` |
| `crucible_g3` | [`crucible_g3/evidence/ppa-resource-summary.json`](crucible_g3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g3` | [`crucible_g3/evidence/board-hil.json`](crucible_g3/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `crucible_g4` | [`crucible_g4/evidence/verification-receipts.json`](crucible_g4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g4` | [`crucible_g4/evidence/rtl-timing-lint.json`](crucible_g4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible_g4` | [`crucible_g4/evidence/quartus-sta.json`](crucible_g4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `116.84`; setup slack ns: `1.441`; hold slack ns: `0.046` |
| `crucible_g4` | [`crucible_g4/evidence/ppa-resource-summary.json`](crucible_g4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g4` | [`crucible_g4/evidence/board-hil.json`](crucible_g4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `crucible_g5` | [`crucible_g5/evidence/verification-receipts.json`](crucible_g5/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g5` | [`crucible_g5/evidence/rtl-timing-lint.json`](crucible_g5/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `crucible_g5` | [`crucible_g5/evidence/quartus-sta.json`](crucible_g5/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `132.26`; setup slack ns: `2.439`; hold slack ns: `0.039` |
| `crucible_g5` | [`crucible_g5/evidence/ppa-resource-summary.json`](crucible_g5/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `crucible_g5` | [`crucible_g5/evidence/board-hil.json`](crucible_g5/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |

## File-management policy / 文件管理约定

- Keep RTL, constraints, tests and result originals in their existing locations. This documentation refresh does not move or delete them.
- Hyphenated, underscored and `chips/` directories are separate existing trees, not interchangeable aliases. The index lists all of them without declaring one authoritative.
- Preserve dated reports as publications. Update the README and this guide when the public source/evidence changes; do not silently rewrite an old result.
- Keep chip artifacts separate from the private Vulcan implementation. Public reproducibility instructions must not require private framework code or internal operation traces.

保留现有源码、约束、测试和原始证据路径；连字符、下划线和 `chips/` 多份目录不自动视为等价。历史报告保留其发表时范围，公开复现不得依赖私有框架实现。
