# CRUCIBLE-G1 specification

## Scope and authority

CRUCIBLE-G1 implements homogeneous matrix transformation, quantized homogeneous
clipping, perspective viewport mapping, and top-left triangle rasterization.
The target is Intel Arria 10 GX 10AX115N2F45E1SG, synchronous clock period at most
10.0 ns. This document records the independently admitted contract, not a claim
of completed simulation, synthesis, timing closure, or physical-board testing.
There are no public parameters, framebuffer, depth test, attribute interpolation,
blending, or deduplication. Throughput is deliberately serialized.

## Public interface

Top module: `crucible_g1_top`.

| Port | Direction | Width | Meaning |
|---|---|---|---|
| clk | input | 1 | Rising-edge clock |
| rst_n | input | 1 | Asynchronous active-low reset |
| s_valid | input | 1 | Input word valid |
| s_ready | output | 1 | Input word accepted when also valid |
| s_data | input | 32 | Command word |
| m_valid | output | 1 | Output word valid |
| m_ready | input | 1 | Output word accepted when also valid |
| m_data | output | 32 | Record word |
| m_last | output | 1 | Last word of completion, not of a pixel |

Each command consists of exactly 31 accepted words:

| Word | Contents |
|---|---|
| 0 | Unsigned triangle tag |
| 1 | `{height[15:0],width[15:0]}` |
| 2 | Exactly 0: 3D; exactly 1: 2D |
| 3..18 | Signed Q16.16 row-major 4x4 matrix |
| 19..30 | Three signed Q16.16 vertices, each ordered x,y,z,w |

Width and height are independently legal from 1 through 256 inclusive.
In 2D mode each vertex's supplied z,w are ignored and replaced by 0,65536.
Invalid dimensions or mode still consume the complete packet, then emit only
an invalid-command completion. There is no timeout or implicit resynchronization.
Only one command is in flight.

Every output record consists of six accepted words:

| Word | Pixel | Completion |
|---|---|---|
| 0 | 0 | 1 |
| 1 | Tag | Tag |
| 2 | `{7'b0,fan_index[8:0],y[7:0],x[7:0]}` | Status |
| 3 | Zero-extended 17-bit lambda0 | Total pixel records |
| 4 | Zero-extended 17-bit lambda1 | Nondegenerate projected fan count |
| 5 | Zero-extended 17-bit lambda2 | 0 |

Completion status is 0 if at least one projected fan is nondegenerate (even
with zero covered samples), 1 for an invalid command, 2 for a final clipped
polygon with fewer than three vertices, and 3 if all projected fans degenerate.
Unspecified bits are zero. `m_last` is true only on completion word 5.
Commands, fan indices, then samples ordered by increasing y and x are emitted
in order. Different commands, including overlapping triangles, remain separate.

## Cycle & Degenerate-Boundary Table

| Boundary/event | Pre-edge decision | Post-edge behavior |
|---|---|---|
| Active reset | Reset overrides every transfer and arithmetic operation | s_ready,m_valid,m_data,m_last are zero; all work aborted |
| Reset release | No input acceptance until input-ready state | First rising edge enters input-ready state |
| Input transfer | Only s_valid && s_ready accepts the current word | Captured word and index update; no other input is sampled |
| Word 30 transfer | Last input word is captured, not processed speculatively | s_ready becomes zero; processing begins |
| Output stall | m_valid && !m_ready transfers nothing | Valid, data and last remain unchanged |
| Output transfer | Only pre-edge valid && ready counts | Next word may appear immediately after the edge |
| Completion word 5 | Final handshake ends this command | Output clears; readiness may assert; next command starts no earlier than next edge |
| Invalid output | No transfer | m_data=0 and m_last=0 |
| Reset plus other event | Reset has absolute priority | No completion for aborted command |
| Record retirement plus internal pixel | Internal pixel is accepted only with an empty record register | No overwrite or combinational m_ready-to-s_ready path |
| Dimension 1 | One sample coordinate on that axis, at raw coordinate 128 | Same clipping and coverage rule; no assumed power-of-two wrap |
| Dimension 256 | Endpoint raw coordinate 65536 remains representable | Sample indices remain 0..255 |
| Polygon storage | Each bank has 384 vertices | Explicit counts and comparisons, no modulo wrap |
| Empty final polygon or count 1,2 | No fan exists | Status 2 |
| Zero-area projected fan | No pixel division or output | Fan index still advances; status 3 if all degenerate |
| Empty nondegenerate fan bounds | No sample traversal | Fan counts as nondegenerate; status may be 0 |
| Shared edge / either winding | Normalize negative area by swapping local vertices 1,2 | Top-left ties and barycentric basis use normalized local vertices |

There are no configurable DEPTH/MAX_WORDS parameters, concurrent public packet
read/write operations, or single-word public packets. The fixed six-word
completion has last asserted only on its sixth word, including zero-pixel work.
All sequential state uses nonblocking assignments and asynchronous active-low
reset. Memories are not cleared on reset: invalidated control prevents stale reads.

## Exact numerical rules

All source words represent signed two's-complement Q16.16. Each transformed
component is the exact signed sum of four 32x32 products in 66 bits, arithmetic
floor-shifted by 16, then saturated to [-2147483648,2147483647]. No intermediate
rounding or saturation is permitted.

Clip in order against:

1. w >= 1 raw unit
2. x+w >= 0
3. w-x >= 0
4. y+w >= 0
5. w-y >= 0
6. z >= 0
7. w-z >= 0

Use Sutherland-Hodgman, visiting directed edges A->B cyclically from last->first.
Inside is distance >=0. Inside/inside emits B; inside/outside emits I;
outside/inside emits I then B; outside/outside emits nothing.
For every crossing and component c:

`I_c = A_c + floor((B_c-A_c)*f(A)/(f(A)-f(B)))`.

Use full precision, then enforce the current plane coordinate exactly as
w=1, x=-w, x=w, y=-w, y=w, z=0, or z=w, respectively. Retain duplicates.
Both polygon banks hold 384 vertices, the conservative `3*2^7` bound. All
seven planes run, even when an intermediate polygon has fewer than 3 vertices.
This is a quantized clipping rule, not a claim of exact real-number clipping.

For each final vertex, form unsigned 17-bit Q8.8 screen coordinates:

`X = clamp(floor((x+w)*width*256/(2*w)),0,width*256)`

`Y = clamp(floor((w-y)*height*256/(2*w)),0,height*256)`.

Final w>=1 guarantees a nonzero denominator. Endpoint 65536 is retained.
Clamping is part of the specified projection, not an exceptional fallback.

Fans are (v0,vi,vi+1), i=1..n-2, with fan_index=i-1 before rejection.
Define `E(a,b,p)=(b.x-a.x)*(p.y-a.y)-(b.y-a.y)*(p.x-a.x)`.
If area E(v0,v1,v2)<0, swap local v1,v2; if zero, reject the fan.
Coordinates increase rightward and downward. Sample (x,y) is
`p=(256*x+128,256*y+128)`, within the requested viewport.
Every opposite-edge E must be positive, or zero with an edge satisfying
`dy<0 || (dy==0 && dx>0)`. Bounding-box traversal is conservative and does not
alter these tests.

For covered samples:

`lambda0=floor(E(v1,v2,p)*65536/area)`

`lambda1=floor(E(v2,v0,p)*65536/area)`

`lambda2=65536-lambda0-lambda1`.

These unsigned Q0.16 weights lie in [0,65536] and sum exactly to 65536.
They are affine screen-space weights for the winding-normalized clipped fan,
not perspective-correct attributes or original-unclipped-vertex weights.

## Primitive timing

For `g1_dot4`, operands accepted at edge e are captured at e; four products
register at e+1, widened pair sums at e+2, their 66-bit sum at e+3, and the
floor-shifted saturated result with valid at e+4.

For `g1_divider`, signed 96-bit numerator and signed nonzero 64-bit denominator
are captured at e; normalized magnitudes register at e+1; exactly one restoring
quotient bit is processed at each edge e+2..e+97; signed floor quotient and
remainder become valid at e+98. Remainder obeys n=d*q+r and has the denominator's
sign unless zero. Clients only issue operands with representable results.

For `g1_edge`, widened signed differences register at e, full products at e+1,
and their widened difference with valid at e+2. Each primitive holds its result
until handshake and does not accept another request while busy. Primitive
latencies exclude downstream stalls. Overall command latency is data-dependent;
there is no one-pixel-per-cycle claim.

## Reproduction, acceptance, and limitations

Source inputs are `rtl/*.sv`, `design/SPEC.md`, `design/ARCHITECTURE.md`,
and independently authored `tests/*.py`. Generated outputs are not source inputs.
The independent Verifier owns `tests/verify.py`. Its required portable entry is:

```
python3 tests/verify.py
```

Dependencies are Python3, Icarus Verilog (`iverilog`, `vvp`) and Yosys.
No dependency is installed by the design. Tool versions and actual outcomes
belong in retained execution receipts, not unmeasured version claims here.

L1 must compare exact outputs and handshake behavior against an independent
arbitrary-precision Python reference, establish the admitted exhaustive,
seeded, directed, reset, backpressure and numerical coverage, reject at least
five independent RTL defects, perform real synthesis/zero-latch checks, and
reproduce a bounded subset in a clean product-only directory. Each invocation
allocates a fresh `evidence/l1/run-<unique>/` and retains commands, hashes,
versions, times, logs, numerical comparisons and measured coverage.

Mandatory native gates are L1.5 timing lint, L2 Quartus 17.1 STA at <=10.0 ns
on the exact target with nonnegative WNS and no unconstrained synchronous
paths, and L3 PCIe Gen3x8 physical HIL with three consecutive deterministic
numerically compared passes. They are shared-runtime gates, not local device
identities embedded in L1. Generic synthesis or simulation cannot establish
physical timing or hardware acceptance. Missing tools/board access remain
unresolved, not waived.

Claim-to-evidence links: source semantics map to the modules and state/width
tables in `design/ARCHITECTURE.md`; functional, coverage, mutation, structural
and portability claims require the fresh L1 result directory; timing and HIL
claims require the shared runtime's native gate receipts. No passing gate
is asserted by these design documents. The independently approved product PDF
is authored by the shared runtime only after engineering acceptance.

### Packet example

An identity matrix is the 16-word row-major sequence
`00010000 00000000 00000000 00000000`,
`00000000 00010000 00000000 00000000`,
`00000000 00000000 00010000 00000000`,
`00000000 00000000 00000000 00010000` (hexadecimal words).
For tag 7, a 2x2 viewport and 3D mode, prepend
`00000007 00020002 00000000`, then append vertices
`ffff0000 ffff0000 00008000 00010000`,
`00010000 ffff0000 00008000 00010000`,
`ffff0000 00010000 00008000 00010000`.
Hold each valid word until an actual pre-edge handshake. Start by asserting
reset, release it, wait for readiness, and consume all six-word records through
the completion's last-word handshake before sending another command.

## Frozen independent verification thresholds

The following are required measured acceptance criteria, not a Designer
execution report. They supplement, and never replace, the native gates.

| Category | Required coverage/check |
|---|---|
| Exhaustive | All 729 ordered triangles from the 3x3 NDC xy grid {-1,0,1} squared, identity, 3D, z=1/2,w=1, viewport 2x2 |
| Seeded | At least 100 independently seeded random commands for each seed 17,89,271; each run has at least 20 nonempty covered triangles and nonidentity matrices |
| Modes and clipping | Both modes; all seven planes each with at least two partially surviving cases and fully clipped cases; mixed planes; negative, zero and tiny-positive source w; multiple nondegenerate clipped fans |
| Degeneracy | All winding permutations; at least 20 degenerates including identical, collinear and projectively collapsed vertices |
| Numerics | Both signs of matrix saturation; negative floor remainders; every viewport boundary; nontrivial fractional barycentrics |
| Dimensions | 1x1,3x5,16x16,32x24,256x256; retain the full endpoint and use small footprints at maximum dimensions |
| Interactions | At least 12 overlapping triangle pairs and 16 shared-edge pairs, including horizontal, vertical and diagonal ties |
| Pixel comparison | At least 2000 actual pixel records; complete exact coverage, order, multiplicity, tag, fan basis, each weight and exact sum |
| Stalls | Input gaps and output backpressure; stalls of at least 64 cycles at each of six record-word positions; earliest legal back-to-back commands |
| Reset | Actual reset transition during partial input, arithmetic and stalled output; recovery with no stale pixel or completion |
| Observation | Separate pre-edge transfers from post-edge outputs; reject active X/Z, extra/missing/malformed records; do not mask unknowns |
| Defect sensitivity | At least five independently injected RTL defects in disposable copies: top-left, weight normalization, transform signedness/rounding, clip plane, output stall/order |
| Mutation verdict | Unchanged independent checker rejects each numerically/procedurally; compile/syntax failure or timeout alone is not sensitivity; preserve passing baseline, edits, copies, logs and rejection reasons |
| Structure | Actual Yosys hierarchy/process/synthesis/check, required connected hierarchy, real sequential state, driven outputs, zero lowered latches, no division/modulo cells or black boxes |
| Clean reproduction | Product-source-only copy; real representative simulation/reference and Yosys run with fresh outputs; both modes, clipped multi-fan command, shared-edge pair and backpressure |

Reference expectations must derive from the mathematical rules using Python
arbitrary-precision integers, not DUT intermediate signals, RTL FSM translation
or generated expected tables. Every output word and public handshake must be
checked. Coverage categories must derive from actual stimuli, reference geometry
and observed transfers rather than scenario labels. Simulation child wall
timeouts are at least 3600 seconds; finite-workload/FSM-derived cycle bounds,
not short wall-clock guesses, determine functional progress limits.

`tests/verify.py` resolves sources relative to its own location, handles local
imports explicitly, fails nonzero on missing prerequisites or acceptance
failures, creates an exclusively allocated fresh evidence directory, and
prints its relative result path. Evidence retains exact argv/cwd, source
hashes, tool versions, actual start/end times, exit/timeout status, raw
stdout/stderr, configuration/seeds, measured coverage and machine-readable
comparisons. No broad exception swallowing or success-shaped default is legal.
The clean-directory subset must not recursively invoke the full portability
test or access original generated outputs, runtime metadata or private state.
