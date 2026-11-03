# CRUCIBLE-G4 architecture

## Connected hierarchy

```
crucible_g4_top
  implementation.compatibility : crucible_g3_top (unchanged G1/G2/G3 hierarchy)
  implementation.bvh : g4_bvh
    slab : g4_slab
      divider : g4_divider
  implementation.splat : g4_splat
    sorter : g4_radix_sort
    conic : g4_conic
      exp_rom : g4_exp_rom
    compositor : g4_compositor
```

The legal generate branch prevents illegal top parameters from elaborating
unsafe child datapaths. The inactive branch reports `PARAMETER ERROR`.
`design/SPEC.md` freezes the complete externally observable ABI and numerical
contract. No engine substitutes software results or a host-sorted list.

## Ownership, storage and scheduling

| Storage | Producer | Consumer | Lifetime / release |
| --- | --- | --- | --- |
| 49-word frontend buffer | top intake | selected engine or parent replay | terminal top response consumed |
| 16-word output buffer | selected G4 engine | top output stream | word 15 consumed |
| 320-bit BVH node entries | successful BVH_WRITE | registered traversal read | next successful write or reset validity |
| node initialized bitmap | BVH_WRITE | reached-node check | reset |
| query visited bitmap | slab issue path | reached-node check | next query/reset |
| 9-bit pending stack | intersected internal nodes | registered LIFO pop | query completion/reset |
| 193-bit splat entries | successful SPLAT_WRITE | key loader and conic fetch | next successful write or reset validity |
| radix ping/pong, 41-bit pairs | loader/sequential scatter | next pass/output | sort done/reset |
| 9-bit sorted index array | sorter output | per-pixel fetch | next render/reset |
| ROM, 4097 x 17 bits | committed initialization | synchronous conic read | immutable |
| per-channel RGB accumulators | compositor sample stages | final background stages | pixel finish/reset |

Large memories use dedicated synchronous non-reset read/write processes and
`nomem2reg`/M20K inference attributes. Validity and controller state reset
asynchronously. Data RAM reset is unnecessary because only initialized scene
entries and loaded sort indices are consumed. Command buffering uses registers:
one accepted command owns the frontend, preventing write/query/render overlap
and eliminating memory coherence ambiguity.

The parent texture and DMA ports connect directly through reset masks. G4
commands select only G4 engines, so do not start legacy texture or DMA work.
G4 composed images stream independently of the parent framebuffer. Upstream
projection supplies screen-space means and full inverse conics.

## Ray engine

The node read is synchronous; metadata is checked before issuing a slab.
A 9-bit current index and explicit 7-bit stack count support every admitted
capacity. Each internal hit appends right to pending storage and selects left.
Each completed current node either finishes or synchronously pops one pending
index. Best-t clipping preserves equal-t candidates. Status reporting is a
registered record stage after the final result/count update.

The slab unit handles one axis at a time, including closed parallel-axis
acceptance. Two exact signed divisions per nonparallel axis supply the directed
integer interval. Coordinate subtraction is 33-bit before widening/shift.
The restoring divider uses unsigned magnitude, a 65-bit shifted remainder
and one compare/subtract step per clock. Signed truncation and directed endpoint
correction have separate registers, and error results follow the same latency.
This is exact lattice arithmetic, not an approximate reciprocal.

## Gaussian engine

Every accepted render scans required initialization metadata, loads keys in slot
order, performs 32 radix-2 passes (except explicit zero/one cases), stores the
returned indices and then visits pixels row-major. A pass first sequentially
counts zero bits, establishes the two destination offsets, and sequentially
scatters pairs in current order. The source and destination banks alternate.
This preserves equal-key slot order and bounded storage independent of key value.

Each pixel starts a new compositor. Before fetching its next sorted entry the
controller checks exact termination and count. Synchronous index/scene reads
feed the conic engine. The conic alpha response transfers directly into the
ready compositor, and evaluated count increments on that joint handshake.
The controller waits for accumulator update before checking termination again.
No later conic is speculatively evaluated after termination.

The conic retains signed 50-bit dx/dy quadratic products and reconstructs
coefficient terms in signed 76-bit registers. Each coefficient product is split
into a 25-bit low magnitude product and signed 25-bit high product, using at most
24x25-bit multipliers. The low product is signed using the coefficient sign;
the high product is sign-extended before a 25-bit shift. Thus the split preserves
negative cross terms without truncation. The doubled cross term, first sum and
full sum occupy distinct stages. The ROM address, synchronous ROM output,
opacity multiplication and alpha rounding follow the fixed cycle table.

The compositor registers T*alpha, rounded weight, RGB products/next T, and
accumulator update separately. Accumulators retain all `255*65536` units.
Finish registers background products, final sums and quantization separately.
Pixel records retain final T and actual evaluated count. DONE totals update
after each pixel record is accepted by the frontend; an independently buffered
top record still owns the command until its terminal word transfers.

## Timing intent and limits

One clock, no gated clocks, no combinational division/remainder, no
simulation-only real datapath, no arithmetic false paths. State labels do not
replace pipeline registers: the exact leaf stage tables are in SPEC.
Wide additions and comparisons, RAM mapping and placement require actual
Quartus STA on the specified Arria 10 part. The architecture does not assert
timing closure, throughput, hardware success or measured PPA.
Analytical progress bounds exclude external stalls and are not wall-clock
watchdogs. Independent Verifier must check functional bounds and native gates
must prove WNS>=0 at <=10 ns.

## Verification handoff and claims

All four portable commands in SPEC remain mandatory. Verifier must supply
independent rational BVH and high-precision Gaussian models, end-to-end
legacy numerical checks, both simulators, capacity/reset/stall coverage,
twelve executing defect variants, substantive Yosys hierarchy/synthesis checks
and clean-directory reproduction. Source copies alone are provenance, not a
passing legacy baseline. ROM constants must be checked against an independent
80+-digit exponential model, not imported from RTL.

Evidence paths are fresh project-relative suite directories as specified in
SPEC. Native shared-runtime timing/STA/HIL and independent review certify
their own outcomes; no final PDF is a design-verification dependency.
The historical generational handoff and intake source index remain unavailable.
