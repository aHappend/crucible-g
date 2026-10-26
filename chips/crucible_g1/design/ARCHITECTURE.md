# CRUCIBLE-G1 architecture

## Hierarchy and scheduling

```
crucible_g1_top
  transform: g1_transform
    dot: g1_dot4
  clipper: g1_clipper
    divider: g1_divider
  project: g1_project
    divider: g1_divider
  raster: g1_raster
    edge0, edge_1, edge_2: g1_edge
    divider: g1_divider
```

The top directly instantiates all four required geometry stages. No arithmetic
is replaced by software or an unconnected placeholder. A single command owns
all storage until its completion retires. Transformation uses one dot unit
sequentially for twelve components. Clipping and projection each share one
divider across components. Rasterization shares one divider across lambda0
and lambda1, with three parallel registered edge engines. These are separate
physical divider instances; no cross-module arbitration or hidden priority
exists. Clipping can prepare the next output vertex while projection divides
the current one; its output register prevents overwriting either vertex.

## Representation and common internal protocol

All internal `clk` and `rst_n` ports are scalar inputs. Every sequential block
uses rising-edge clock and asynchronous active-low reset with nonblocking
updates. Scalar valid/ready inputs and outputs implement the same pre-edge
handshake rule as the public interface. Producers retain valid and payload
until handshake; consumers sample payload only on that handshake. Except for
the top's initial BOOT state, an idle internal consumer is ready immediately
after reset release. All valids and readies are forced low during reset.
Internal payloads are meaningful only while valid; unlike public outputs,
internal inactive payload buses need not be zero.

Packing is little-component-first: a homogeneous vertex `[127:0]` holds
signed x in [31:0], y in [63:32], z in [95:64], w in [127:96].
A `[383:0]` triangle has vertex0 in [127:0], then vertex1, vertex2.
A `[511:0]` matrix has element (row r,column c) in
`[32*(4*r+c) +:32]`. Each element is signed Q16.16 even though the
packed container itself is an unsigned bit vector.
A projected `[33:0]` vertex holds unsigned Q8.8 X in [16:0] and Y in
[33:17]. A `[101:0]` projected triangle packs v0, v1, v2 in increasing
34-bit slices.

There are no supported public RTL parameters. All dimension buses below
are unsigned 9-bit values in [1,256]. Counts and addresses are unsigned;
signedness applies to numerical components, not to their packed containers.

## Internal ports

All names below are actual RTL ports. Direction is relative to the module.
`s_valid` input, `s_ready` output, `m_valid` output and `m_ready` input are
scalar unless explicitly noted otherwise.

### g1_transform

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | Whole-triangle request |
| s_mode_2d | in | scalar | Substitute z=0,w=65536 for every source vertex |
| s_matrix | in | 512 packed | Sixteen signed 32-bit matrix elements |
| s_vertices | in | 384 packed | Three signed homogeneous vertices |
| m_valid,m_ready | out,in | scalar | Whole-triangle result |
| m_vertices | out | 384 packed | Twelve independently saturated transformed components |

The request captures the complete matrix and triangle. `IDLE -> ISSUE ->
WAIT_RESULT` iterates rows 0..3 inside vertices 0..2, then enters `HOLD`.
Each ISSUE sends one row and one mode-adjusted vertex to the dot unit.
The dot result is written to exactly the corresponding 32-bit slice. HOLD
releases ownership only when its complete transformed triangle is accepted
by the clipper. The matrix and vertices remain unchanged while this request
is executing.

### g1_dot4

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | One four-term dot request |
| s_a,s_b | in | 128 packed each | Four signed 32-bit terms, lowest term first |
| m_valid,m_ready | out,in | scalar | Registered result-holding handshake |
| m_result | out | signed 32 | Floor-shifted, saturated Q16.16 result |

At accepted edge e, operands register and state becomes PRODUCT. At e+1,
four signed 64-bit products register and state becomes PAIR. At e+2,
two explicitly sign-extended 65-bit sums register and state becomes SUM.
At e+3, their explicitly extended 66-bit sum registers and state becomes
SATURATE. At e+4, arithmetic shift by 16 and signed saturation register the
result and state becomes HOLD with valid. HOLD returns to IDLE on handshake;
no new request is accepted on that retirement edge.

Each product is exact; four signed 32x32 products require at most 66 bits.
The comparison uses the signed 66-bit shifted value and signed 66-bit
limits before selecting the signed 32-bit result. This preserves negative
floor rounding and cancellation before saturation.

### g1_clipper

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | Capture one transformed triangle |
| s_vertices | in | 384 packed | Three signed 32-bit-component vertices |
| m_valid,m_ready | out,in | scalar | Ordered final polygon vertex stream |
| m_vertex | out | 128 packed | One final homogeneous vertex |
| done_valid,done_ready | out,in | scalar | Completion after all vertex handshakes |
| done_count | out | unsigned 9 | Exact final polygon vertex count, including duplicates |

Two banks, each 384 by 128 bits, have exclusive per-plane ownership: `bank`
selects the read bank; all emissions go to the other bank. No array is cleared
on reset. IDLE captures the input triangle; SEED writes its three vertices
to bank0 on three consecutive edges using a single write port. Each bank has
one explicit RTL write site and one shared read-address selection.
PLANE_START initializes
the emission count, reads the last input as A, and selects READ_B. READ_B
registers the next vertex B. DISTANCE registers both signed distances.
CLASSIFY implements the four inside/outside cases exactly. An unchanged
inside B goes to WRITE_B; no emission goes directly to NEXT_EDGE. Crossings
iterate four components:

`DIFFERENCE -> MULTIPLY -> DIV_SEND -> DIV_WAIT -> ADD_COMPONENT`.

DIFFERENCE registers B-A and f(A)-f(B). MULTIPLY registers the exact product
(B-A)*f(A). DIV_SEND waits for divider acceptance; DIV_WAIT consumes its
floor quotient and registers the component offset. ADD_COMPONENT adds A
in widened arithmetic and writes the component. After all four components,
FIX_PLANE overwrites the constrained coordinate exactly. WRITE_I emits the
intersection, optionally followed by WRITE_B for outside/inside.
NEXT_EDGE updates A=B and advances the explicit edge index. PLANE_DONE
swaps banks and sets the new input count. It advances plane 0..6 without
early rejection of polygons with one or two vertices; an empty polygon
also advances all seven planes. After plane 6, OUTPUT_READ registers one
vertex and OUTPUT_HOLD retains it until accepted. DONE holds the final count
until accepted. The separate done event also represents an empty stream.

Capacity is not a heuristic polygon-size limit: at each plane an input edge
emits at most two vertices. Starting with 3 gives bank capacities at most
6,12,24,48,96,192,384. All 9-bit counts represent 384 without wrap; maximum
written/read address is 383. No silent truncation or capacity-based fallback
exists. Distances, including w-1 at the most negative source w, fit signed
33 bits. B-A fits signed 33 bits. Distance subtraction fits signed 34 bits.
The product fits signed 66 bits and is sign-extended to the divider's 96-bit
numerator; the denominator is sign-extended from 34 to 64 bits. A crossing
has opposite classifications, so its denominator is nonzero. Its interpolation
parameter lies in [0,1], so each floor offset fits signed 33 bits. Addition
uses 34 bits and the resulting component stays inside the signed 32-bit
endpoint interval. Forced +/-w is representable after w-plane clipping
because 1<=w<=2147483647. Full components are never saturated during clipping.

### g1_project

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | One clipped homogeneous vertex |
| s_vertex | in | 128 packed | Signed 32-bit homogeneous components |
| s_width,s_height | in | unsigned 9 each | Captured legal viewport dimensions |
| m_valid,m_ready | out,in | scalar | One projected vertex |
| m_vertex | out | 34 packed | Unsigned 17-bit X,Y coordinates |

IDLE captures one vertex and dimensions. SUM registers x+w (X axis) or w-y
(Y axis) and 2*w. MULTIPLY registers the coordinate times the selected
dimension. DIV_SEND offers the numerator with eight low zero bits and the
denominator. DIV_WAIT clamps the accepted signed floor quotient. It stores
X and loops to SUM for Y; after Y it enters HOLD until the result is accepted.

Coordinate sums and 2*w fit signed 33 bits. A dimension is explicitly
zero-extended to signed 10 bits before multiplication. The product is
signed 43 bits, followed by an exact eight-bit left shift into signed 96 bits.
The numerator needs at most 51 bits, denominator at most 33 bits, and the
quotient fits signed 96 bits. Even a quantized vertex slightly outside an
earlier clipping plane cannot overflow these paths. The specified clamp
preserves the full 17-bit dimension*256 endpoint. w>=1 is guaranteed by
the clipper, so the divider never sees a zero denominator.

### g1_raster

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | One fan triangle request |
| s_vertices | in | 102 packed | Three projected X,Y pairs |
| s_width,s_height | in | unsigned 9 each | Legal viewport dimensions |
| m_valid,m_ready | out,in | scalar | One covered sample with all weights |
| m_x,m_y | out | unsigned 8 each | Sample indices |
| m_lambda0,m_lambda1,m_lambda2 | out | unsigned 17 each | Q0.16 weights summing to 65536 |
| done_valid,done_ready | out,in | scalar | Fan completion, including zero-sample fans |
| done_nondegenerate | out | scalar | Nonzero projected area before sampling |

IDLE captures the triangle. AREA_SEND uses edge0 for E(v0,v1,v2).
AREA_WAIT consumes that result; area zero goes straight to DONE. Negative
area swaps v1,v2 and negates the area register. All later edges and weights
use this normalized basis. BOUNDS chooses a conservative integer box:
lower bounds are floor(minimum raw coordinate/256), upper bounds are
min(floor(maximum raw coordinate/256), dimension-1). A lower bound beyond
the viewport produces no samples but retains nondegenerate status.
Divisions by 256 in this description are literal bit selections in RTL.

PIXEL_SEND atomically issues the three opposite-edge requests only when
all engines are ready. PIXEL_WAIT consumes their outputs only when all are
valid. An uncovered sample advances to NEXT_PIXEL. A covered sample stores
edge1 and the numerator edge0<<16, then follows DIV0_SEND/DIV0_WAIT to store
lambda0. DIV1_PREP registers edge1<<16; DIV1_SEND/DIV1_WAIT compute lambda1
and the residual lambda2. PIXEL_HOLD retains the complete sample until
accepted. NEXT_PIXEL uses explicit x/y comparisons and increments, x first,
then y; after the final sample it enters DONE. DONE waits for acceptance
before returning to IDLE. A new fan cannot disturb a pending pixel.

Projected differences fit signed 18 bits, products signed 36 bits and
subtractions signed 37 bits. Actual nonnegative area is at most 2^32, since
the vertices lie in the 65536-square. For covered points, every opposite-edge
value is between zero and area, and their sum equals area. Shifting a covered
edge by 16 therefore needs at most 49 nonnegative bits. It is sign-extended
to the 96-bit numerator; positive area is extended from 37 to 64 bits.
Denominator is nonzero, quotients are in [0,65536], and the two floors sum
to at most 65536. Lambda2's residual is computed in 18 bits then stored
in 17 bits, retaining the legal endpoint 65536.

### g1_edge

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | One edge request |
| s_a,s_b,s_p | in | 34 packed each | Unsigned 17-bit projected coordinates |
| m_valid,m_ready | out,in | scalar | Registered edge result |
| m_edge | out | signed 37 | Exact E(a,b,p) |

IDLE captures explicitly zero-extended signed 18-bit dx,dy,px,py at accepted
edge e. PRODUCT registers the full signed 36-bit products at e+1.
DIFFERENCE registers their signed 37-bit difference and enters HOLD with valid
at e+2. HOLD retains the result until acceptance. Thus the actual pipeline,
not merely the enclosing controller, provides the admitted two-cycle latency.

### g1_divider

| Port | Direction | Width/type | Contract |
|---|---|---|---|
| s_valid,s_ready | in,out | scalar | One division request |
| s_numerator | in | signed 96 | Captured dividend |
| s_denominator | in | signed 64 | Nonzero divisor guaranteed by clients |
| m_valid,m_ready | out,in | scalar | Registered result-holding handshake |
| m_quotient | out | signed 96 | Floor quotient, representable for all client requests |
| m_remainder | out | signed 64 | n-d*q, zero or sign of denominator |

IDLE captures signed operands at e. NORMALIZE registers unsigned magnitudes,
quotient sign and denominator sign at e+1. ITERATE executes exactly 96
restoring iterations, numbered 0..95, at e+2..e+97. Each iteration forms
the 65-bit trial `{remainder,quotient[95]}`, conditionally subtracts the
64-bit divisor, and shifts one quotient bit into the 96-bit register.
Because remainder<divisor, the retained remainder fits 64 bits.
CORRECT publishes at e+98: when signs differ, negate the magnitude quotient
and subtract one iff remainder is nonzero. For that floor correction the
remainder magnitude becomes divisor-remainder. Its sign is the denominator's.
HOLD preserves both results until accepted.

Magnitude extraction handles the most negative encoded input without signed
absolute-value overflow by using unsigned bit vectors. The generic primitive
requires a nonzero divisor and a representable floor quotient; it does not
invent a valid result for illegal requests. The three connected clients'
proofs above satisfy both requirements for every legal input command.

## Top-level ownership and transitions

The top has a fixed 31-word command receiver, 384 by 34-bit projected-vertex
store, and one 192-bit output record register. Matrix/vertex packets require
896 bits; projected storage requires 13056 bits. Clipping storage is
98304 bits (12288 bytes) across two banks; it is not replaced by a smaller
unproven convex-polygon bound. Arrays are addressed only within their
initialized active counts. Reset invalidates counts and state, rather than
clearing large memories. No host memory, DMA, PCIe device identity or clock
domain crossing exists inside this streaming core.

BOOT enters RECEIVE on the first rising edge after reset release. RECEIVE
captures one word for each valid/ready handshake. Tags, dimensions and mode
are decoded in place; the complete payload is consumed even if illegal.
At word30, a valid command enters TRANSFORM_SEND, otherwise COMPLETE_SEND.
TRANSFORM_SEND waits for request acceptance. TRANSFORM_WAIT forwards the
transform result directly into the clipper with a single common handshake.
PROJECT_WAIT connects clipper vertices to projection and records projected
outputs in order. Clipper DONE latches the final polygon count; the top also
waits for projected_count to equal that count, so the last divider output
cannot be mistaken for completion of projection. Fewer than three vertices
select status2; otherwise fan_i starts at 1 and fan_index at 0.

The first projected vertex is also retained in the fan-origin register.
FAN_READ registers projected vertices fan_i,fan_i+1 and that origin into a
102-bit fan request register, separating storage selection from request
acceptance. RASTER_SEND accepts that registered request. RASTER_WAIT admits
pixel or done events only while the output record
register is empty. A pixel event packs a zero-filled six-word record and
increments pixel_total. A done event increments fan_total only when
nondegenerate, then selects the next fan or completion. Fan indices advance
even for degenerate fans. At the final done, status is selected using both
the previous count and the current fan's nondegenerate bit. The subsequent
COMPLETE_SEND packs the updated counts, never the previous cycle's count.
COMPLETE_WAIT keeps the command occupied through completion word5's handshake.

The serializer selects a word using a 0..5 counter. On any stall, its register,
index, valid and kind remain unchanged. On pixel word5 it clears the record;
the next internal pixel cannot overwrite a just-retiring record because
internal readiness depends on pre-edge record emptiness. On completion word5
it clears the record and enters RECEIVE; a new command cannot transfer on
that same edge. Invalid cycles explicitly produce data=0,last=0. Public
s_ready is decoded only from registered state and reset, never m_ready.
Reset has absolute priority over serializer, command and all child work.

## Timing intent and limitations

All nonconstant division uses fixed-iteration restoring hardware. RTL contains
no arithmetic division or modulo operators. Multiply, add, saturation, clipping
distance and component-add phases are separated by registers; raster edge
differences, full products and final subtraction are separately registered.
No sequential block mixes blocking and nonblocking signal assignments.
The design uses no clocks other than clk, no floating point, no inferred
combinational state and no simulation-only data path.

These properties bound the logical arithmetic phases; they do not prove a
10.0 ns routed path. In particular, inferred multiplier mapping, carry chains,
large polygon bank addressing and fan-storage muxes require actual target
implementation analysis. Quartus 17.1 and the native timing gate must
establish timing on 10AX115N2F45E1SG. A lint waiver is not a Designer decision.
No STA or HIL result is asserted here.

Command service time depends on packet gaps, output stalls, crossings, polygon
size, fan bounding boxes and covered samples. Per crossing, four component
divisions are needed; per projected vertex, two; per covered sample, two.
Bounds reduce traversal on small footprints in 256x256 viewports. There is no
fixed command latency or sustained pixel-rate guarantee.

## Reproduction and evidence boundaries

Run commands from the delivered project root. The complete required RTL
inventory is:

```
rtl/crucible_g1_top.sv
rtl/g1_transform.sv
rtl/g1_dot4.sv
rtl/g1_clipper.sv
rtl/g1_project.sv
rtl/g1_raster.sv
rtl/g1_edge.sv
rtl/g1_divider.sv
```

A static syntax/elaboration command is:

```
iverilog -g2012 -t null -s crucible_g1_top rtl/*.sv
```

This is not functional verification. The independently owned portable L1
entry is `python3 tests/verify.py`. It must retain fresh, project-relative
evidence under `evidence/l1/`, including failing attempts and exact tool
versions. Native timing lint, Quartus STA and physical-board bridge gates
are executed separately by the shared runtime. No shipped command depends on
developer metadata, private state, an old generated binary, a local JTAG cable
or a local PCIe BDF. The final product PDF is a post-acceptance runtime artifact,
not a prerequisite source or evidence substitute.
