# Crucible-G — Graphics and rendering accelerator RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

Documentation updated: 2026-11-17. This page describes a repository snapshot, not a live job dashboard.

## Overview

**Crucible-G** publishes chip RTL, technical reports and verification artifacts. Triangle setup, tiled rasterization, depth/texture processing and later ray/3D Gaussian rendering research across G1–G5.

The chip project is public; Vulcan itself remains private and closed-source. Future public releases must be limited to chip technology and public reproducibility materials, excluding Vulcan internal architecture and operating materials. This refresh organizes documentation only; it is not a comprehensive disclosure audit of historical material and does not claim that the existing repository tree has undergone such clearance.

## Scope and evidence

Use the [exact-directory result index](REPOSITORY_GUIDE.md). Functional simulation, synthesis, standalone/virtual-pin timing, board-bridge probing, workload readback and system-software execution are different evidence scopes. A pass at one scope does not establish another. Existing historical results are retained; this documentation refresh neither upgrades nor invalidates them.

Read timing, utilization and performance values from their specific records and applicability conditions; results from differently located copies are not merged. This page makes no fleet-wide claim of physical-board completion, full-model inference, physical Linux boot or measured power/energy efficiency.

## Repository guide

The [repository guide](REPOSITORY_GUIDE.md) lists existing source, constraints, tests, reports and result paths. Hyphenated, underscored and `chips/` directories can be different publication copies; none is silently designated authoritative, moved or deleted.

Start reproduction from the selected chip’s public specification, test instructions and scripts. Tool, input and board requirements belong to that directory. Chip experiments were not rerun as part of this documentation update.

## Existing chip directories

| Chip / variant | Existing root paths | Public artifacts |
| --- | --- | --- |
| CRUCIBLE-G1 | [`crucible-g1/`](crucible-g1/) · [`crucible_g1/`](crucible_g1/) | [REPORT.md](crucible-g1/REPORT.md) · [REPORT.pdf](crucible-g1/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g1/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g1/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G2 | [`crucible-g2/`](crucible-g2/) · [`crucible_g2/`](crucible_g2/) | [REPORT.md](crucible-g2/REPORT.md) · [REPORT.pdf](crucible-g2/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g2/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g2/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G3 | [`crucible-g3/`](crucible-g3/) · [`crucible_g3/`](crucible_g3/) | [REPORT.md](crucible-g3/REPORT.md) · [REPORT.pdf](crucible-g3/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g3/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g3/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G4 | [`crucible-g4/`](crucible-g4/) · [`crucible_g4/`](crucible_g4/) | [REPORT.md](crucible-g4/REPORT.md) · [REPORT.pdf](crucible-g4/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g4/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g4/SHOWCASE_REPORT.zh-CN.pdf) |
| CRUCIBLE-G5 | [`crucible-g5/`](crucible-g5/) · [`crucible_g5/`](crucible_g5/) | [REPORT.md](crucible-g5/REPORT.md) · [REPORT.pdf](crucible-g5/REPORT.pdf) · [SHOWCASE_REPORT.pdf](crucible-g5/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](crucible-g5/SHOWCASE_REPORT.zh-CN.pdf) |

## Architecture catalog and publications

| Generation | Chip | Architecture / research scope | Record navigation | Reports |
| --- | --- | --- | --- | --- |
| **Gen-1** | **CRUCIBLE-G1** | 2D/3D Triangle Setup & Half-Space Barycentric Edge-Function Tile Rasterizer (Q16.16 Fixed-Point) | [Exact-directory records](REPOSITORY_GUIDE.md) | *Planned* |
| **Gen-2** | **CRUCIBLE-G2** | 16×16 Tile Z-Buffer Depth Unit + Perspective-Correct Barycentric Attribute & Gouraud Shading Interpolator | [Exact-directory records](REPOSITORY_GUIDE.md) | *Planned* |
| **Gen-3** | **CRUCIBLE-G3** | Bilinear Texture Mapping Cache + Blinn-Phong Specular/Diffuse Lighting & Alpha-Blending Fragment Pipeline | [Exact-directory records](REPOSITORY_GUIDE.md) | *Planned* |

Later generation directories are listed above; their technical scope and records remain directory-specific.

## Related projects

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark is a research direction, not a published chip delivery in this repository; no implementation or repository link is asserted here.
