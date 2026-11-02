# CRUCIBLE-G5 admitted implementation contract

This document describes the admitted product, not a passing result. The
Designer owns `rtl/*.sv` and `design/*.md`; the independent Verifier owns
`tests/*`. Historical G4 results in `design/GENERATIONAL_HANDOFF.md` do not
certify G5. The product PDF is a subsequent shared-runtime deliverable.

## Scope, hierarchy and parameters

Target Intel Arria 10 GX `10AX115N2F45E1SG`, synchronous 100 MHz or faster,
with a clock period at most 10.0 ns. Retain the supplied G4 hierarchy and
numerical/protocol behavior, including its inward-rounded slab operation.
The source of that compatibility contract is `crucible_g4_reference/rtl/`;
the reference directory remains read-only.

`crucible_g5_top` retains every G4 stream, texture and framebuffer DMA port,
with identical names, widths, directions and signedness. Literal children are
`crucible_g4_top compatibility`, `g5_lbvh builder`, `g5_ray_triangle triangle`,
`g5_ray_query ray_query`, and `g5_svgf denoiser`. The builder instantiates
`g5_morton morton`; the query reads the builder's actual store and uses the
same triangle instance as standalone commands.

| Parameter | Default | Legal range |
|---|---:|---:|
| MAX_WIDTH, MAX_HEIGHT | 256 | 1..256 |
| TILE_LOG2 | 3 | 0..4 |
| MAX_NODES, MAX_SPLATS | 64 | 1..256 |
| STACK_DEPTH | 16 | 1..64 |
| MAX_PRIMITIVES | 64 | 1..128 |
| SVGF_MAX_WIDTH, SVGF_MAX_HEIGHT | 32 | 1..64 |

Illegal values select a diagnostic-only generate branch with an explicit
`PARAMETER ERROR` fatal. Diagnostic port widths have minimum width one.
G5 capacity is independent of inherited node and traversal-stack capacities.
Tree storage has `2*MAX_PRIMITIVES-1` entries and construction storage supports
at least 39 simultaneous radix intervals.

## Cycle and degenerate-boundary table

All transfers sample **pre-edge** valid and ready. The following table gives
**post-edge** observations; E accepts a child request, F accepts the last
stream command word.

| Boundary | Required behavior |
|---|---|
| Active reset | Asynchronous active-low control reset; all public outputs zero; invalidate metadata, not large data RAM |
| First clock after reset release | Wrapper leaves BOOT and enables intake post-edge |
| Input bubble | No packet-index advance |
| Final command word F | Enter DISPATCH |
| F+1, F+2 | Select SEND, then ready child captures |
| First child record at F+2+L | Wrapper captures at F+3+L and exposes word 0 |
| Continuous output readiness | Consume word 0 at F+4+L and word 15 at F+19+L |
| Stalled valid output | Hold valid and every response field unchanged |
| Accepted terminal word | Return to intake post-edge; no input acceptance on consuming edge |
| Morton input E | Capture xyz; interleaved registered result valid at E+1 |
| Triangle input E | First record valid exactly at E+16384, including errors and misses |
| Primitive write, SVGF begin/write/clear | First record at E+64 |
| Node read | First record at E+4 |
| Builder read port | Capture index at E; registered response at E+2; hold until accepted |
| Empty build | Completion at E+64; root `0xffffffff`; no node records |
| Build N>0 | First node at E+B(N), B(N)=64+38*(8*N+16)+128*(2*N-1) |
| Following build records | Ascending node IDs; at least one full separation cycle after acceptance; completion last |
| Denoise P pixels | First pixel at E+R(P), R(P)=64+1024*P+3*8192*P |
| Singleton tree | Node 0 is leaf; both children and parent are `0xffffffff` |
| Non-power-of-two capacities | Explicit range/wrap comparisons, not binary masks |
| Singleton image | Positive self tap; omitted other taps; denominator remains nonzero |
| Reset with pending arithmetic/output | Cancel packet, computation and records; invalidate tree and temporal history |
| Invalid write/build/frame request | No scene, completed-tree or temporal-history mutation |
| Sample rewrite | Latest successfully accepted write replaces that coordinate before run |
| Memory ownership | One command outstanding; query/read does not coincide with builder mutation |
| History commit | Once after successful computation, never repeated by output stalls |

Arithmetic completion must precede fixed publication boundaries. Padding is
not evidence of timing closure. New arithmetic uses registered DSP-sized
partial products and at most 16-bit carry/borrow dependencies per limb step.
No executable `/` or `%` operators or mixed sequential assignment styles are
permitted. Large RAM data arrays are never asynchronously reset; registered
RAM ports and reset-invalidated metadata protect uninitialized contents.
Large byte-enabled memories use explicit unpacked byte-lane arrays.

## Packet and record ABI

Packets are little-word-order: word 0 tag, word 1 metadata, word 2 opcode.
Every new command is exactly 31 accepted 32-bit words. Retain inherited
49-word draw opcodes
`2,3,6,7,258,259,262,263,514,515,518,519,770,771,774,775`;
replay these and all other inherited commands byte-for-byte to compatibility.
Unknown non-G5 commands retain inherited rejection behavior.

Every G5 record is 16 words: words 0,1,2 are type, tag, status. Only word 15
of a terminal record asserts stream `m_last`. All unspecified fields and
reserved input bits/words are zero. Reject nonzero reserved fields, never
truncate them silently. Status: 0 success, 1 malformed/range invalid,
2 unavailable/uninitialized, 3 capacity violation, 4 internal topology
inconsistency. Error payload is zero except specified index/sentinel fields.

| Opcode | Operation | Input fields beyond tag/opcode |
|---|---|---|
| 0x900 | Primitive write | word 3 slot; 4 ID; 5..13 v0,v1,v2 xyz |
| 0x901 | Build | word 3 primitive count N |
| 0x902 | Node read | word 3 node ID |
| 0x903 | Built-tree query | 3 cull flag; 4..6 origin; 7..9 direction; 10..11 t_min; 12..13 t_max |
| 0x910 | Triangle | 3 cull flag; 4..6 origin; 7..9 direction; 10..18 vertices; 19..20 t_min; 21..22 t_max |
| 0x920 | Begin frame | word 1 width low16/height high16; word 3 history-reset flag |
| 0x921 | Sample | 3 x; 4 y; 5 shadow; 6 reflection; 7 depth; 8..10 normal; 11 dx; 12 dy |
| 0x922 | Run frame | No metadata/payload |
| 0x923 | Clear history | No metadata/payload |

Only bit 0 of cull/history-reset flags is defined. All metadata words except
begin-frame dimensions are zero.

Completion/ack type `0x50000000`: word 3 opcode, word 4 operation count.
Build completion additionally has word 5 node count, word 6 root.
Run completion additionally has word 5 spatial passes (3), word 6 accepted
history count.

Node type `0x50000001`: word 3 node ID, 4 leaf flag, 5 left, 6 right,
7 primitive ID, 8 original slot, 9 Morton code, 10..12 min.xyz,
13..15 max.xyz. Leaf children are `0xffffffff`; internal ID/slot are
`0xffffffff`, code zero. Parent is retained separately in the builder
read-port response. An invalid read-port index returns status 1 in
`rd_node`, with zero vertices and parent.

Triangle/query type `0x50000010`: word 3 hit, 4..5 t, 6 u, 7 v.
Query adds word 8 ID, 9 slot (both `0xffffffff` on miss), 10 nodes tested,
11 triangles tested. Successful misses have zero t/u/v.

Pixel type `0x50000020`: word 3 x, 4 y, 5 filtered shadow, 6 filtered
reflection, 7 shadow variance, 8 reflection variance, 9 history accepted.
Pixels are row-major, followed by terminal completion.

## Morton and canonical LBVH

Coordinates are signed 32-bit Q15.16. Primitive boxes are exact componentwise
vertex min/max. Form each midpoint with signed 33-bit min+max, then arithmetic
right shift one (floor, including negative odd sums). Flip the midpoint sign
bit and take bits 31:22 for ten-bit grid coordinates. Morton input packs x
in 9:0, y in 19:10, z in 29:20. For i=0..9, code bits 3i,3i+1,3i+2 are
x[i],y[i],z[i]. No host-computed keys or scene-dependent normalization.

Build requires initialized slots 0..N-1 and N within capacity. Stable hardware
radix sort ascending composite key `(code<<8)|slot` (38 bits). Duplicate IDs
and codes are legal. For sorted interval [lo,hi], split at the highest
differing endpoint-key bit, immediately before the first one-bit key.
Singletons are leaves. Allocate nodes in preorder, root 0. Compute internal
boxes by exact min/max unions only after both children finish, in postorder.
Emit each of exactly 2N-1 nodes once, in node-ID order. Successful primitive
replacement invalidates the completed tree; rejected write/build preserves it.

## Exact triangle arithmetic and conservative G5 traversal

Use full-precision integer Moller-Trumbore:
`e1=v1-v0`, `e2=v2-v0`, `p=cross(d,e2)`, `det=dot(e1,p)`,
`tv=o-v0`, `un=dot(tv,p)`, `q=cross(tv,e1)`,
`vn=dot(d,q)`, `tn=dot(e2,q)`.
Differences are signed 33-bit; determinant/numerator storage is at least
signed 128-bit. No intermediate Q16 rounding/saturation. Require signed
64-bit Q47.16 `0<=t_min<=t_max`. det=0 misses. Culling rejects det<=0;
otherwise negate det/un/vn/tn together for negative det.

Hit iff un>=0, vn>=0, un+vn<=det, and
`t_min*det <= tn*65536 <= t_max*det`, with signed 192-bit-or-wider
distance comparisons. Boundaries are closed. Output mathematical floors
`t=(tn*65536)/det`, `u=(un*65536)/det`, `v=(vn*65536)/det`;
t is signed 64-bit, u/v unsigned Q16 in 0..65536. Registered iterative
division implements these ratios; quotients must not wrap.

Query walks the actual built tree left-first, using parent pointers without
an inherited-stack-depth limit. Count a node only at first box-test arrival
and a triangle only when invoking a surviving leaf. Parent returns do not
retest. Bound node-state transitions by `3*(2*N-1)+1` and triangle calls
by N; detect inconsistent topology instead of looping. Select smallest
quantized t, then smallest primitive ID, then smallest slot.

For each nonzero direction axis compute exact scaled signed differences.
Positive d: entry=(lo-o)*65536/d, exit=(hi-o)*65536/d; negative d swaps
the endpoints. Round entry **down** (floor), exit **up** (ceil), including
negative rational values. Zero d rejects only if o is outside [lo,hi].
Intersect entries with original t_min by max and exits with original t_max
and current best quantized t by min. Reject only E>X; equality survives.
Every invoked triangle receives the **original exact interval**, not slab
bounds or current-best t. Never form T+1 in signed 64-bit storage.

The public zero-thickness witness at raw z=1, direction z=3, origin z=0,
xy=(16384,16384), triangle xy legs 65536, interval [0,65536], requires
t=21845, u=v=16384, nodes=triangles=1. Outward z bounds are [21845,21846].
Its origin z=2/direction z=-3 counterpart has the same result. With two
identical-code triangles at z=1/ID9/slot0 and z=2/ID3/slot1 and direction
z=262144, both t values floor to zero; ID3/slot1 must win, nodes=3,
triangles=2. Equal IDs require slot tie-breaking.

## Two-channel SVGF

Radiance is unsigned Q8.16 in 0..0x00ffffff; depth is unsigned nonnegative
Q15.16. Normal words are signed components in -32768..32768, with squared
length sum in `2^30 +/- 2^24`. Reject invalid normals, never normalize them
silently. Motion is sign-extended signed 16-bit integer dx/dy.
Begin validates dimensions, invalidates current-sample metadata and preserves
history only if dimensions match and the explicit reset flag is clear.
Sample writes require active frame/in-range coordinates. Run requires all
current samples initialized. Clear invalidates temporal history only.

Q=65536. Reproject to (x+dx,y+dy). Accept valid, in-bounds matching-dimension
history iff depth difference<=4096 and normal dot>=58982; dot is
clamp(floor(sum(n_current*n_previous)/2^14),0,Q).
Without history M=L, S=floor(L*L/Q). With history,
M=floor((7*M_prev+L+4)/8),
S=floor((7*S_prev+floor(L*L/Q)+4)/8).
V=max(S-floor(M*M/Q),0). Retain full products and temporal moments/surface
attributes; spatial outputs do not replace temporal history.

Run exactly three non-in-place 5x5 passes at steps 1,2,4, with outer-product
kernel [1,4,6,4,1]. Omit out-of-image taps and renormalize. Guides are
original current normals/depth and pass-input luminance/variance.
For each channel, sigma=floor_isqrt(V_center<<16);
b=ceil_log2(max(256,4*sigma+256)).
Self Wn=Q. Other taps with normal dot D<32768 or depth difference>4096
have zero weight; otherwise three repeated floor(a*a/Q) squarings of D
produce Wn. Wz=Q>>min(16,abs(depth difference)>>12);
Wl=Q>>min(16,abs(luminance difference)>>b).
Edge weight=floor(floor(Wn*Wz/Q)*Wl/Q);
w=edge weight*integer kernel coefficient.

Output L=floor((sum(w*L)+floor(sum(w)/2))/sum(w)).
Output V=floor((sum(w*w*V)+floor(sum(w)^2/2))/sum(w)^2).
Use full intermediates and at least 128-bit accumulators where needed.
Positive self weight guarantees nonzero denominators; a zero denominator is
an explicit internal error. Square root and normalization division use
registered iterative engines. Commit next temporal history once only after
successful computation. Reset in ingestion, arithmetic, filtering or output
invalidates pending frame and history.

## Independent acceptance and reproduction

The mandatory portable L1 entrypoint, authored/executed by Verifier, is
`python3 tests/verify.py --output-root evidence/l1`. Each invocation allocates
a fresh run-UUID directory and preserves success/failure receipts, raw logs,
source hashes, actual measured coverage and complete synthesis artifacts.
Required existing tools are Python 3, Icarus/vvp, Verilator, C++ compiler,
make and Yosys; do not install them. No private host paths, local cable/BDF
identifiers, hidden runtime files or final product report are L1 inputs.

The admitted independent oracle, five-cell legal matrix, seeds 17/41/89,
boundary/invalid-parameter tests, compatibility sequences, cycle/stall/reset
checks, seven executable mutants, exact numerical thresholds, zero-latch
synthesis and bounded clean-directory reproduction remain mandatory.
Compact Icarus behavior is limited to at most 500000 cycles per process;
large/multi-seed/mutation work uses compiled Verilator. No simulation,
synthesis, timing or hardware result is claimed by this document.

Native L1.5 timing lint, L2 Quartus 17.1 post-fit setup/hold WNS>=0 at
<=10.0 ns, and L3 hardware-bridge gate with at least three consecutive
deterministic passes remain shared-runtime gates. No timing waiver is
preapproved. A connectivity-only HIL result is never numerical validation.
