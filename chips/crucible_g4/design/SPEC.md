# CRUCIBLE-G4 implementation contract

## Scope and provenance

Top: `crucible_g4_top`. Target: Intel Arria 10 GX
`10AX115N2F45E1SG`, synchronous 100 MHz, clock period at most 10 ns.
The 22 files supplied in `crucible_g3_reference/rtl/` are copied unchanged
into `rtl/`. Historical acceptance is not current G4 verification.
No intake source index was supplied. `design/GENERATIONAL_HANDOFF.md` was
not supplied; historical Quartus timing/PPA cannot be claimed.

Designer owns RTL and design documentation. Independent Verifier owns
`tests/*`, the numerical models, simulation and synthesis checks.
The shared runtime owns timing lint, Quartus STA, hardware acceptance and
the final independently approved product PDF. None is claimed here.

## Cycle and degenerate-boundary table

| Event | Pre-edge condition | Post-edge effect |
| --- | --- | --- |
| Asynchronous reset | `rst_n=0` | All top outputs zero; pending work aborted; G4 scene validity cleared |
| First released clock | BOOT, ready zero | INTAKE, ready one; no beat accepted at this edge |
| Intake beat | valid and ready | Store this word and advance index; gaps do not advance |
| Final intake beat L | valid and ready | Complete buffer; dispatch/replay valid first appears after L |
| Child acceptance | child valid and ready | Earliest L+1; no same-edge use of the last incoming word |
| Child record publication R | registered record becomes valid | Frontend capture earliest R+1; top transfer earliest R+2 |
| Stalled output | valid and not ready | Payload, valid and last unchanged |
| Terminal final word | valid, ready, word 15 for G4 | Return to intake; next command transfer on the following edge |
| Reset concurrent with transfer | reset asserted | Reset wins; no surviving transfer |
| Capacity one | legal singleton | No zero-width select; root leaf uses no pending stack; sorter emits one pair |
| Odd capacities | explicit count comparisons | No power-of-two mask assumption for wrapping |
| Capacity 256 | 9-bit counts/indices | Capacity itself is representable |
| Rejected write | invalid fields | Previous entry remains atomically unchanged |
| Compositor finish and sample | both offered | Finish takes priority; sample is not accepted |

All G4 payloads are zero when their valid is zero. Parent leaf conventions
are retained behind reset masking. RAM contents need not reset; valid
metadata does. One command remains outstanding through its terminal transfer.

## Parameters and stream ABI

Parameters `(MAX_WIDTH,MAX_HEIGHT,TILE_LOG2,MAX_NODES,MAX_SPLATS,STACK_DEPTH)`
default to `(256,256,3,64,64,16)`. Legal ranges respectively are
`1..256`, `1..256`, `0..4`, `1..256`, `1..256`, `1..64`.
Illegal configurations elaborate an inactive diagnostic branch and simulation
terminates with nonzero `PARAMETER ERROR`.

The top retains the parent 32-bit ready/valid command and response streams,
`m_last`, texture request/response and framebuffer DMA request/response ports.
The physical hardware bridge must drive exactly these streams; no board-specific
JTAG cable or PCIe address is part of the product ABI.
Command word 0 is tag, word 1 is height[31:16]/width[15:0], word 2 opcode.
Draw opcodes `2,3,6,7,258,259,262,263,514,515,518,519,770,771,774,775`
consume 49 words. All other opcodes consume 31 words.
All non-G4 commands, including unknown opcodes, replay unchanged to
`compatibility:crucible_g3_top`.

Words below are unsigned unless a signed representation is specified.
All unlisted command words and reserved bits must be zero.

| Opcode | Assigned words after opcode |
| --- | --- |
| `0x800 BVH_WRITE` | 1=0; 3=slot; 4=leaf bit; 5/6=children; 7=primitive; 8..10=min XYZ; 11..13=max XYZ |
| `0x801 RAY_QUERY` | 1=0; 3=root or `0xffffffff` empty; 4=any-hit bit; 5..7=origin; 8..10=direction; 11/12=t_min low/high; 13/14=t_max low/high |
| `0x810 SPLAT_WRITE` | 1=0; 3=slot; 4=depth; 5/6=mean XY; 7/8/9=a,b,c; 10=opacity; 11=RGB |
| `0x811 SPLAT_RENDER` | 1=viewport; 3=N; 4=epsilon; 5=background RGB |

BVH coordinates and directions are signed 32-bit Q16.16, with ordered
closed bounds. Leaves require zero children. Internals require zero primitive
and in-range children, which can be uploaded later.
Ray endpoints are signed 64-bit Q47.16; require `0<=t_min<=t_max`.
Zero direction, including the zero vector, is legal.
Mean fields are sign-extended signed 24-bit Q11.12, conics sign-extended
signed 24-bit Q7.16. Require `a>0,c>0,a*c-b*b>0` exactly.
Opacity and epsilon are integers `0..65536`; RGB is low-byte R,G,B,
upper byte zero. Render dimensions are positive and bounded, N may be zero,
and slots `0..N-1` must be initialized.

## Response ABI

Every G4 record has 16 words, tag in word 1 and status in word 2.
Unspecified words are zero. Statuses: OK=0, BAD_COMMAND=1,
UNINITIALIZED=2, STACK_OVERFLOW=3, MALFORMED_TREE=4.

| Type (word 0) | Additional words | Terminal |
| --- | --- | --- |
| `0x40000000 ACK` | 3=opcode, 4=slot | yes |
| `0x40000001 RAY_RESULT` | 3=hit,4=primitive,5=leaf,6/7=t low/high,8=nodes tested,9=max pending occupancy | yes |
| `0x40000002 SPLAT_PIXEL` | 3=x,4=y,5=RGBA,6=T,7=evaluated,8=N | no |
| `0x40000003 SPLAT_DONE` | 3=pixels,4=N,5=sum evaluated,6=early-terminated pixels | yes |

RGBA alpha is 255. Miss/error rays suppress tentative hits, use primitive
and leaf `0xffffffff`, t=0, and retain bounded diagnostic counts.
Invalid render emits only an error DONE with zero pixel/evaluation counts.
`m_last` is set only on word 15 of a terminal record, never on pixels.

## Ray arithmetic and traversal

For nonzero direction form signed 33-bit `(bound-origin)`, widen and shift
left 16 without truncation. Axis entry is the mathematical ceiling of the
smaller exact rational quotient; exit is the floor of the larger.
Intersect integer intervals and the supplied closed t range. A parallel axis
accepts iff origin is inside its closed bounds; never divide by zero.
The iterative divider returns magnitude remainder and directed floor/ceil.
Denominator zero and INT64_MIN/-1 produce explicit error and zero payload.

Traversal uses a real STACK_DEPTH pending-node stack, pushes right, visits
left, then pops LIFO. Any-hit chooses first DFS leaf; closest-hit minimizes
entry t, then unsigned primitive, then leaf slot. Best-t pruning is inclusive.
Visited metadata detects repeated reached nodes, with at most MAX_NODES unique
tests. Reached uninitialized entries error. Full-stack push errors without
overwriting. Empty and root-leaf queries use no pending stack.

Divider acceptance E0: magnitude E1; restoring steps E2..E65; signed truncation
E66; directed correction E67; valid E68, including errors.
Slab completes in <=1024 unstalled cycles. BVH completes in
`2048*MAX_NODES+128` unstalled cycles from acceptance.

## Gaussian arithmetic

Sort ascending unsigned depth, stable by original slot, with 32 genuine
radix-2 LSD passes and sequential count/scatter through ping-pong storage.
Counts 0 and 1 are explicit paths.
Sorter bound after last key: `32*(8*N+16)+4*N+32` unstalled cycles.

At pixel center `px=4096*x+2048,py=4096*y+2048`, signed 25-bit deltas,
compute exact signed wide
`Nq=a*dx*dx+2*b*dx*dy+c*dy*dy`.
Physical q is `Nq/2^41`. If q>=16, W=0. Otherwise
`k=min(4096,(Nq+2^32)>>33)`;
`W[k]=floor(65536*exp(-k/256)+0.5)`.
Committed synchronous `g4_exp_rom.sv` contains all 4097 constants; addresses
above 4096 return zero. No external runtime initialization file is required.
Scaled absolute error against unquantized exp must be <=129.

`alpha=min(65536,(opacity*W+32768)>>16)`.
Start T=65536,C=0. Before each sample stop iff `T<epsilon`.
`w=(T*alpha+32768)>>16`; `C+=w*RGB`; `T-=w`.
Zero opacity counts as evaluated. Epsilon zero disables early termination,
including at T=0; equality does not terminate.
Finish RGB is `min(255,(C+T*background+32768)>>16)`.
No independent rounding of `T*(1-alpha)` is allowed.

Conic acceptance E0: deltas E1; quadratic products E2; <=25x25 partial
coefficient products E3; exact terms E4; first sum E5; full sum E6;
clamp/round address E7; synchronous ROM E8; opacity product E9;
rounded alpha E10; valid E11.
Compositor sample E0: capture; T*alpha E1; w E2; RGB products and T E3;
accumulation E4; readiness/termination post-E4.
Finish F0: capture; background products F1; sums F2; quantize F3; valid F4.
Render bound: sorter bound plus
`width*height*(256*N+128)+256` unstalled cycles.

## Parent numerical compatibility

The copied RTL, not historical scripts, defines inherited arithmetic.
`g3_bilinear` uses 17-bit weights summing to 65536, retains horizontal and
vertical products, and rounds once from Q32 using bit 31.
`g3_shader_pipeline` clamps vertex Q16 colors to [0,65536], quantizes with
`(v*255+32768)>>16`, modulates using normalize255 after adding 127,
and blends using the sum of source/destination products plus 127.
normalize255 computes `t=n+1; (t+(t>>8)+(t>>16))>>8` in its documented
bounded range. Blend factors are zero, one, source alpha, one-minus-source
alpha, destination alpha, one-minus-destination alpha; color and alpha select
independently. Final blends saturate to 255.
`g1_dot4` retains four signed 64-bit products, 65-bit pair sums and a 66-bit
total, arithmetic-shifts the total by 16 (negative values round toward minus
infinity), and saturates to signed 32-bit endpoints.
G1/G2 integer dividers use signed magnitude restoring division followed by
floor correction: negative nonintegral quotients are complemented without
adding one, while negative integral quotients receive the two's-complement
carry. Their remainder has the denominator's sign and satisfies
`numerator=quotient*denominator+remainder`. G1 screen projection clamps floored
`(x+w)*width*256/(2*w)` and `(w-y)*height*256/(2*w)` to the viewport.
G2 additionally computes reciprocal `2^40/w`, and clamps floored
`z*depth_limit/w` to [0,depth_limit], with limit 65535 or 16777215.
These inherited division expressions describe mathematics, not combinational
division operators in RTL.
G2 clip planes, in order, are `w>=1`, `x+w>=0`, `w-x>=0`, `y+w>=0`,
`w-y>=0`, `z>=0`, `w-z>=0`. Crossing component offsets floor
`(B-A)*f(A)/(f(A)-f(B))`, add to A and retain low 32 bits,
then fix the clipped coordinate exactly to its plane.
Raster sampling uses Q8 centers `(256*x+128,256*y+128)`, positive edge values
or zero on top-left edges (`dy<0 || (dy==0 && dx>0)`).
Barycentric lambda0/lambda1 floor edge*65536/area; lambda2 is the residual.
Perspective attributes use integer weights `lambda_i*q_i`, retain complete
weighted numerators and floor division by their sum, retaining low 32 bits.
Depth tests use strict-less; equality rejects. Tile early-Z rejects when
incoming tile minimum is greater than or equal to the stored tile maximum.
G4 does not modify parent framebuffer storage or texture/DMA addressing.

## Reproduction and evidence responsibilities

Declared inputs are `rtl/*.sv`, `design/*.md`, `tests/*` and immutable
`crucible_g3_reference/rtl/*.sv`; exclude runtime metadata from selection.
From the delivered root, independent verification commands are:

```
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite defects
python3 tests/verify.py --suite portable
```

Verifier supplies the script and its dependencies: Python 3, Icarus/vvp,
Verilator and Yosys. Exact executed versions and source hashes belong in
fresh `evidence/<suite>-<timestamp_or_hash>/receipt.json` and raw logs.
Behavior evidence establishes records/numerics/reset/backpressure and observed
coverage; defects establish independent scoreboard sensitivity; synthesis
establishes hierarchy/connectivity/zero-latch/zero-divider structure;
portable establishes clean-directory reproduction. Native timing lint,
Quartus 17.1 STA and three consecutive hardware bridge HIL passes remain
separate mandatory shared-runtime gates. A parse check is not any of these.
