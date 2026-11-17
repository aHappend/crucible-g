# Crucible-G — 图形与渲染加速器 RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

文档更新：2026-11-17。本页对应仓库快照，不是实时作业看板。

## 概览

**Crucible-G**：图形与渲染加速器 RTL。下方保留芯片技术与报告入口；具体实现范围以所链接目录、规范、测试和结果原件为准。

芯片项目公开；Vulcan 本身保持私有、闭源。今后公开发布仅限芯片技术与公开复现资料，不得包含 Vulcan 内部架构或运作资料。本次更新仅整理文档，并非对全部历史材料进行全面披露审查，也不声称既有仓库树已完成此类清查。

## 范围与证据

按实际目录核对[公开结果索引](REPOSITORY_GUIDE.md)。功能仿真、综合、独立 IP／虚拟引脚时序、板卡桥接探测、工作负载数值读回和系统软件执行是不同层级；一种通过不能替代另一种。现有历史结果保留，不因本次文档更新自动升级或作废。

时钟、资源与性能指标必须读取对应目录的原始记录和适用条件；同名副本不合并为一个数值。此处不宣称全系完成上板、完整模型推理、Linux 实机启动或功耗／能效测量。

## 文件导航

[文件与证据导航](REPOSITORY_GUIDE.md)列出真实存在的源码、约束、测试、报告及结果路径。连字符、下划线和 `chips/` 目录可能是不同发布副本，不自动指定某份为权威，也不移动或删除原件。

公开复现从对应芯片的规范、测试说明和脚本开始；所需工具、输入和板卡条件以该目录为准。文档更新没有重新执行芯片实验。

## 已有芯片目录

| 芯片／变体 | 现存根路径 | 公开交付物 |
| --- | --- | --- |
| CRUCIBLE-G1 | [`crucible-g1/`](crucible-g1/) · [`crucible_g1/`](crucible_g1/) | [REPORT.md](crucible-g1/REPORT.md) · [REPORT.pdf](crucible-g1/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g1/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g1/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G2 | [`crucible-g2/`](crucible-g2/) · [`crucible_g2/`](crucible_g2/) | [REPORT.md](crucible-g2/REPORT.md) · [REPORT.pdf](crucible-g2/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g2/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g2/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G3 | [`crucible-g3/`](crucible-g3/) · [`crucible_g3/`](crucible_g3/) | [REPORT.md](crucible-g3/REPORT.md) · [REPORT.pdf](crucible-g3/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g3/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g3/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G4 | [`crucible-g4/`](crucible-g4/) · [`crucible_g4/`](crucible_g4/) | [REPORT.md](crucible-g4/REPORT.md) · [REPORT.pdf](crucible-g4/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g4/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g4/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G5 | [`crucible-g5/`](crucible-g5/) · [`crucible_g5/`](crucible_g5/) | [REPORT.md](crucible-g5/REPORT.md) · [REPORT.pdf](crucible-g5/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g5/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g5/SHOWCASE_REPORT.zh-CN.pdf) |

## 架构目录与技术报告

| 代际 | 芯片 | 架构／研究范围 | 记录导航 | 报告 |
| --- | --- | --- | --- | --- |
| **Gen-1** | **CRUCIBLE-G1** | 2D/3D 三角形建立与半空间重心坐标边缘函数分块光栅化引擎（Q16.16 定点） | [Exact-directory records](REPOSITORY_GUIDE.md) | *规划中* |
| **Gen-2** | **CRUCIBLE-G2** | 16×16 分块 Z-Buffer 深度测试 + 透视校正属性插值与 Gouraud 着色流水线 | [Exact-directory records](REPOSITORY_GUIDE.md) | *规划中* |
| **Gen-3** | **CRUCIBLE-G3** | 双线性纹理映射缓存 + Blinn-Phong 镜面/漫反射光照与 Alpha 混合片元渲染管线 | [Exact-directory records](REPOSITORY_GUIDE.md) | *规划中* |

后续代际目录已在上方补齐，具体技术范围和结果按对应目录核对。

## 关联项目

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark 是研究方向，不代表本仓库已交付对应芯片；此处不虚构实现或仓库链接。
