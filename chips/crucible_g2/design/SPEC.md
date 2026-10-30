# CRUCIBLE-G2 product contract

## Scope and ownership

CRUCIBLE-G2 preserves the supplied CRUCIBLE-G1 triangle transform, clipping,
projection, edge-function rasterization and stream records. It adds persistent
16/24-bit strict-LESS depth, conservative early-Z and six perspective-correct
signed Q16.16 attributes. There is no texture sampler. The implementation target
is Intel Arria 10 GX 10AX115N2F45E1SG, a synchronous clock period of at most
10.0 ns. This document describes requirements, not measured timing.

Designer owns `rtl/*.sv` and the two design documents. The independent Verifier
owns `tests/*`, including `tests/verify.py`. The immutable parent inputs are
`crucible_g1_reference/rtl/*.sv`. Engineering acceptance, native timing/hardware
gates and the independently approved runtime-authored PDF are subsequent work.

## External interface and parameters

`crucible_g2_top` parameters are integer `MAX_WIDTH=256`, `MAX_HEIGHT=256`,
`TILE_LOG2=3`. Width and height are independently legal from 1 through 256;
tile log2 is 0 through 4. Partial tiles, singleton frames, non-power-of-two
dimensions and tiles larger than a frame are legal. Illegal configurations
have diagnostic-only safe elaboration and explicitly terminate simulation with
`PARAMETER ERROR`; they are not silently clamped legal configurations.

Ports are `clk`, asynchronous active-low `rst_n`, input `s_valid`,
output `s_ready`, input `s_data[31:0]`, output `m_valid`, input `m_ready`,
output `m_data[31:0]`, output `m_last`. Transfers occur only on rising edges
with valid and ready. Producers hold stalled valid/payload unchanged. Reset
cancels all work and invalidates G2 depth configuration without clearing RAM.
All external outputs are zero in reset; data/last are also zero when invalid.
Only one command is active. The next command starts strictly after the prior
completion-last transfer. Parent `crucible_g1_top` retains its parameter-free
original interface and 256 by 256 capability.

## Cycle & Degenerate-Boundary Table

| Boundary | Pre-edge condition | Post-edge effect |
|---|---|---|
| Transfer | valid and ready | Exactly one payload accepted; counters count events, not held cycles |
| Output stall | valid and not ready | Valid, payload and last remain unchanged |
| Active reset | rst_n low | Public outputs zero, partial command/work discarded, depth configuration invalid |
| First released edge | reset previously asserted | BOOT advances to receive; no input accepted before readiness |
| Completion-last | m_valid and m_ready and m_last | Completion retires; input readiness may appear afterwards, never simultaneous new-command acceptance |
| Single pixel / single tile | width=height=1, any legal tile | Explicit coordinate end comparisons; no zero-width vectors or empty clears |
| Ragged viewport | width/height not powers of two | Coordinate wrap compares against active bounds, never a modulo address expression |
| Clear versus read/write | Engine owns one transaction | Clear, tile scan and fragment transactions cannot overlap |
| Passing fragment | RAM read then strict comparison | Synchronous write commits before response-valid, including repeated addresses |
| Reset versus write | rst_n low at a clock edge | Write enable is suppressed; RAM is not asynchronously reset |
| Set versus increment | New command accepted | Per-command counters reset before any candidate/sample event |
| Empty/degenerate geometry | fewer than 3 vertices / zero area | No sample issue; status 2 / status 3 unless another nonzero fan exists |

`E0` denotes the accepting edge. A valid first visible after `Ek` cannot
transfer before `E(k+1)`. Internal channels follow the same handshake,
reset, zero-invalid-payload and stability rules.

## Input stream

The common 31 words are: tag; packed width low16/height high16; mode;
16 signed Q16.16 matrix entries in row-major order; then three vertices,
each x,y,z,w in signed Q16.16.

| Mode | Operation | Words |
|---|---|---|
| 0, 1 | Original 3D, original 2D | 31 |
| 2, 3 | G2 3D, depth16/depth24 | 49 |
| 4, 5 | Clear/configure depth16/depth24 | 31 |
| 6, 7 | G2 2D, depth16/depth24 | 49 |

G2 draw modes alone permit bit8 (disable early-Z, retain fragment tests).
All other bits are zero. The 18 appended draw words are U,V,R,G,B,A for
vertex0, then vertex1, then vertex2; all signed Q16.16 and unclamped.
Legacy 2D and G2 2D substitute `(x,y,0,65536)` before transformation.
Clear ignores matrix and vertex words. Unknown modes consume 31 words and
return legacy status1. Recognized G2 draws consume 49 even for invalid
dimensions and return G2 status1. Clears use G2 completions.

Runtime dimensions are 1..MAX_WIDTH and 1..MAX_HEIGHT. Matching clear is
required before first G2 draw and after a dimension or precision change.
Clear initializes active pixels to all ones and commits configuration only
after the last write. Legal but unconfigured draws return status4; invalid
header status1 takes priority. Invalid operations change neither stored depth
nor configuration. Legacy commands do not invalidate G2 configuration.

## Output stream

Legacy pixel records are `[0,tag,packed_xy_fan,lambda0,lambda1,lambda2]`;
completion is `[1,tag,status,pixel_total,fan_total,0]`.
Only the sixth completion word has last asserted. Packed x is bits7:0,
y15:8, fan24:16, all other bits zero.

G2 pixel records are
`[0,tag,packed_xy_fan,lambda0,lambda1,lambda2,depth,U,V,R,G,B,A]`.
Depth is zero-extended to 32 bits; lambdas are zero-extended 17-bit Q0.16.
Only passing fragments produce records.
G2 completions are
`[1,tag,status,pixels_emitted,nondegenerate_fans,tiles_tested,tiles_rejected,fragments_tested,fragments_passed,fragments_failed,0,0,0]`.
Only completion word12 has last asserted. Status0 means at least one
nondegenerate fan, even if occluded; 1 invalid header; 2 fully clipped;
3 all fans degenerate; 4 missing/mismatched depth configuration.
Successful clear is status0 with every counter zero.
Counters are unsigned32; pixels_emitted equals fragments_passed and
fragments_tested equals fragments_passed plus fragments_failed.
Early-rejected tiles generate no fragment tests. Completion follows retirement
of all pixel records. At most 382 fans, 65536 candidate samples per fan and
65536 candidate tiles per fan keep every counter below 2^32.

## Exact numerical rules

Transform uses four signed32 by signed32 products, widened exact pair/sum
tree, arithmetic shift right16, then signed32 saturation.

Ordered Sutherland-Hodgman clipping planes are w>=1 raw, x>=-w, x<=w,
y>=-w, y<=w, z>=0, z<=w. An A to B crossing with signed distances fa,fb
computes each of ten components as
`A + floor((B-A)*fa/(fa-fb))`, retaining low32. Force only the relevant
geometric component to its plane, exactly as the parent. Preserve insertion,
plane and fan order; provide storage for 384 vertices.

Project unsigned17-bit Q9.8 screen coordinates as
`x=floor((x+w)*width*256/(2*w))` and
`y=floor((w-y)*height*256/(2*w))`, clamped to the viewport endpoints.
At each clipped vertex compute unsigned41-bit `q=floor(2^40/w_raw)` and
`zd=clamp(floor(z_raw*(2^D-1)/w_raw),0,2^D-1)`.
No approximate reciprocal or floating point substitutes are allowed.

Use signed37-bit
`E(A,B,P)=(Bx-Ax)*(Py-Ay)-(By-Ay)*(Px-Ax)` and pixel centers
`(256*x+128,256*y+128)`. Top-left is `dy<0 || (dy==0 && dx>0)`.
Normalize positive area by swapping vertices1/2 and **all** their payloads.
Zero area emits no samples.
Included samples use `lambda0=floor(E12*65536/area)`,
`lambda1=floor(E20*65536/area)`, `lambda2=65536-lambda0-lambda1`.
Weights refer to normalized winding. Fragment depth is
`floor((lambda0*zd0+lambda1*zd1+lambda2*zd2)/65536)`.
Strict unsigned LESS passes; equality and equal far-plane depths fail.
Only passing fragments write.

For each signed32 attribute a the output is mathematical floor of
`(lambda0*q0*a0+lambda1*q1*a1+lambda2*q2*a2) /
 (lambda0*q0+lambda1*q1+lambda2*q2)`.
Keep denominator exact unsigned64 and numerator exact signed96.
The convex result fits signed32 without clamping. This quantized-q definition
is the bit-exact contract, including negative floor rounding.

## Early-Z and ordering

For each fan enumerate all triangle bounding-box intersecting tiles by tile
row then column. Surviving tiles traverse y then x, clipped to viewport and
bounding box. Legacy retains global row-major per fan.
Scan **every viewport pixel** of each candidate tile for maximum stored depth.
Reject exactly when enabled and minimum of the three vertex depths is at least
that maximum. Recompute per fan and tile; no cached metadata or overlapping
writes. Count every candidate once, including tiles without covered samples.
Disabled early-Z still counts candidates, but reports zero rejections.

## Literal hierarchy and packed interfaces

Top instantiates `legacy:crucible_g1_top` and `engine:g2_engine`.
Engine instantiates `setup:g2_setup`, `raster:g2_raster`,
`zbuffer:g2_zbuffer`, `interpolator:g2_interpolator`.
Setup contains `transform:g1_transform`, `clipper:g2_clipper`,
`project:g2_project`. Raster retains explicit `g1_edge` instances.
Sequential G2 division helpers are `g2_divider`; interpolation has six parallel
signed dividers. All eight parent-named modules remain in `rtl/`.

All packed words use lowest bits first. Engine/setup command inputs:
`s_header[991:0]`, `s_attributes[575:0]`.
Clipper input `s_vertices[959:0]` is three 320-bit vertices with ten
increasing32-bit lanes x,y,z,w,U,V,R,G,B,A. Output `m_vertex[319:0]`
and done count9 use separate valid/ready channels.
Project inputs add width9,height9,depth24; output `m_vertex[290:0]` packs
x17,y17,q41,zd24,then six signed32 attributes.
Setup outputs that projected channel plus done count9.
Raster inputs vertices102 in parent XY order, width9,height9,tile_x8,tile_y8;
outputs x8,y8,three lambda17 plus done valid/ready. Engine normalizes winding.
Zbuffer has separate clear, tile and fragment request/result channels:
clear width9,height9,depth24 and done; tile x8,y8,zmin24 and reject;
fragment x8,y8,depth24 and pass. Engine never overlaps their ownership.
Interpolator inputs three lambda17, q123 (q0 lowest41) and attributes576
(vertex-major); output attributes192 (U first32).
Divider inputs signed numerator96 and denominator64; output signed quotient96
and remainder64, with `n=q*d+r` and remainder sign equal to denominator or zero.
Zero denominator is an explicit simulation assertion failure.

## Arithmetic cycle contracts

Divider E0 captures; E1..E6 normalize six16-bit limbs.
E7..E582 execute 96 six-cycle quotient iterations: shift, four serial
16-bit subtraction/borrow limbs with explicit top-bit handling, decision.
E583..E588 perform six16-bit sign/floor correction limbs.
First valid is post-E588 and held through backpressure; no parallel wide compare.

Interpolator E0 captures; E1 lambda*q products; E2 pairs; E3 denominator;
E4 signed weighted attribute products; E5 pairs; E6 numerators;
all six dividers accept E7, produce post-E595, output captured E596.
First output valid is post-E596. No additional throughput is promised.
Retained g1_edge is E0 differences,E1 products,E2 result;
g1_dot4 E0 capture,E1 products,E2 pairs,E3 total,E4 saturation;
g1_divider first valid post-E98. Top-level latency is transaction-dependent.

## Verification and release requirements

`python3 tests/verify.py` is the Verifier-owned self-contained portable L1 entry.
It must run actual compact Icarus checks, compiled Verilator sweeps, independent
integer/Fraction comparisons, seven isolated behavioral RTL mutations, real
Yosys structural/zero-latch synthesis and fresh-directory compact reproduction.
No previously generated evidence, binaries or directories may be required.
`--compact` is the documented partial-reproduction interface, not full acceptance.

Mandatory cells (MAX_WIDTH,MAX_HEIGHT,TILE_LOG2):
(1,1,0),(1,1,3),(7,5,1),(9,9,2),(16,16,3),(17,9,4),(256,256,3),
each seeds17,89,2026. Each executes at least32 G2 draws,16 per precision,
both 2D/3D and windings; at least16 depth decisions and16 complete passing
six-attribute outputs (128 decisions/64 outputs for nonsingletons);
two rejected tiles,two surviving tiles,two disabled-early-Z strict failures,
and passing/failing fragments in both precisions.

Directed coverage includes all clip planes, near-zero positive w, clipped
attributes, fully clipped/degenerate/opposite winding/distinct attributes,
shared edges, x/y 0 and255, dimensions1/256, ragged/partial/oversized tiles,
negative/fractional attributes, signed32 endpoints, extreme matrices, unequal w,
depth equality/far equality/precision distinctions/draw permutations,
depth persistence across legacy, mismatched clears, invalid headers/parameters,
and reset during receive/compute/clear/stalled output.
Replay early-Z scenes disabled from an independent clear, compare exact records
and counters, require positive rejection and reduced tested fragments in an
occluded scene. Prove preserved depth using later public transactions.

Audit at least128 passing unequal-w samples against unquantized Fraction
perspective with clipped w_real in [0.25,4], attributes_real in [-8,8]:
every channel error <=2 raw LSBs, and affine discrepancy >256 raw LSBs in cases.
Required behaviorally detected isolated mutations: LESS to LEQUAL, reversed
depth order, suppressed passing write, unjustified tile rejection, corrupted
rejection counter, affine interpolation, broken winding payload identity.
Compile failures or generic crashes do not count.

No combinational division/modulo operators, mixed sequential assignment styles,
latches, undriven active outputs or black-box datapaths are permitted.
Yosys checks preserve default-top memories and also fully map a compact top.
L1 is functional/structural only. Native L1.5 timing lint, L2 Quartus17.1 STA
WNS>=0 at10.0 ns, and L3 Arria10 PCIe Gen3x8 HIL (three deterministic passes)
remain mandatory; no waiver is granted and these gates are not duplicated in L1.
Fresh `evidence/l1-<timestamp_or_hash>/` receipts retain exact commands, hashes,
versions, times, exit/timeout, logs and coverage without overwriting failures.
Portable copies include only RTL, design docs, tests and immutable parent RTL;
never runtime metadata, private paths, credentials, device IDs or binaries.
Tools must already exist; do not install dependencies.

### Current evidence status and limits

Passing L1 simulation, independent-reference comparisons, behavioral mutation
sensitivity, Yosys synthesis and clean-directory reproduction evidence is retained
at `evidence/l1-20261030T162101Z-f8fd97a9/`. These results establish the checked
functional and structural behavior, not physical-board graphics execution.

L2 completed placement/routing and post-fit internal timing analysis at 10 ns
reports setup slack +1.341 ns and hold slack +0.036 ns, with 14,114 ALMs,
27,268 registers, 129 M20Ks and 161 DSPs. All non-clock inputs and all outputs
are excluded from timing analysis. Thus these results establish internal
virtual-pin timing only; external-interface and asynchronous-reset timing
closure are not established.

Current L3 evidence is exactly `L3_BRIDGE_CONNECTIVITY_PROBE_ONLY`: three
deterministic register-57 reads, with no CRUCIBLE bitstream flash and no depth,
early-Z or perspective workload execution. Graphics workloads were checked in
simulation, not demonstrated on the board. Connectivity does not establish
graphics-workload acceptance or satisfy the mandatory graphics-workload HIL
requirement. All mandatory acceptance requirements above remain unchanged.

The later runtime-authored product report must retain these evidence boundaries
and limitations, with no OS-boot claim. Report creation and independent PDF
approval remain subsequent to engineering acceptance, not prerequisites for
design verification.
