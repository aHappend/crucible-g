# CRUCIBLE-G2 implementation

## Status and reproduction

Top: `crucible_g2_top`. Sources: `rtl/*.sv`. Immutable comparison inputs:
`crucible_g1_reference/rtl/*.sv`. Defaults are MAX_WIDTH=256,
MAX_HEIGHT=256, TILE_LOG2=3; legal ranges and all numerical/protocol rules
are in `design/SPEC.md`. No external memory image or generated source is needed.

From the delivered root, a syntax/elaboration-only command is:

```sh
iverilog -g2012 -t null -s crucible_g2_top rtl/*.sv
```

Independent L1 entry and partial clean-directory reproduction interface:

```sh
python3 tests/verify.py
python3 tests/verify.py --compact
```

The independent Verifier supplies these test sources. Required available tools
are Python3, Icarus/vvp, Verilator, Yosys, g++ and make. No installation, local
device identifier, runtime transcript or private path is part of reproduction.
The compact command is explicitly partial; it cannot certify the full matrix.
Tool versions and exact executed commands belong in fresh run receipts, not an
assumption about the user's environment.

The design targets 100 MHz or faster on Intel Arria 10 GX
10AX115N2F45E1SG. No functional, synthesis, STA or hardware pass is claimed by
this implementation document. Generic synthesis does not establish frequency.
Runtime-native L1.5 timing lint, L2 Quartus17.1 STA and L3 hardware gates remain
authoritative and mandatory. There is no timing waiver or measured throughput.
The runtime creates and independently reviews the product PDF only after
engineering acceptance.

## Module map and responsibilities

```text
crucible_g2_top
  legacy: crucible_g1_top
    transform: g1_transform -> dot: g1_dot4
    clipper: g1_clipper -> divider: g1_divider
    project: g1_project -> divider: g1_divider
    raster: g1_raster -> g1_edge instances, g1_divider
  engine: g2_engine
    setup: g2_setup
      transform: g1_transform -> g1_dot4
      clipper: g2_clipper -> g2_divider
      project: g2_project -> g2_divider
    area_edge: g1_edge
    raster: g2_raster -> three g1_edge instances, g2_divider
    zbuffer: g2_zbuffer
    interpolator: g2_interpolator -> six parallel g2_divider instances
```

Top invalid-parameter configurations drive zero outputs, accept no traffic
and issue an explicit PARAMETER ERROR. Diagnostic-safe widths inside the
parameterized storage and tile modules keep illegal values elaboratable;
they do not expand the legal configuration set.

| Producer | Consumer dependency | Guarantee |
|---|---|---|
| Stream collector | Legacy replay / engine | Complete header and attributes are stable before dispatch |
| Setup | Engine polygon RAM | Projected vertices transfer in clipper order; done follows all projected transfers |
| Engine fan control | Raster/interpolator | Positive winding and identical geometry/q/depth/attribute permutation |
| Raster | Depth pipeline | Only covered samples, with normalized-winding lambdas |
| Zbuffer | Tile/fragment control | Single outstanding transaction; no read/write scan race; passing write precedes response |
| Interpolator | Record serializer | Exact floor-rounded six attributes; output held under stalls |
| Serializer | Command collector | Completion-last retirement precedes next-command acceptance |

## Collector and record ownership

The top BOOT state prevents input acceptance before the first released edge.
HEADER stores 31 words, decoding the exact mode at word2. Recognized draws
continue through ATTRIBUTES for 18 words. Clears dispatch to engine immediately
after the common header. Other commands replay exactly 31 words to legacy.
Legacy dimensions exceeding the configured G2 limits are rejected by replaying
an invalid mode word to the unmodified legacy command parser; the original tag,
six-word status1 format and absence of depth side effects are preserved.

LEGACY_SEND advances only on legacy readiness, then LEGACY_WAIT forwards the
legacy output. ENGINE_SEND transfers one packed command, then ENGINE_WAIT
forwards engine output. No path accepts a new command while a completion is
pending. Header buffering changes latency, not supported legacy records.

Engine output storage is one 416-bit record and a 4-bit word index.
PIXEL_HOLD and COMPLETE_HOLD alone assert valid. The index advances only on
ready. A last pixel word returns to raster service; a last completion word
returns the engine to IDLE. No partial record can interleave with another.
Completion is assembled only after fan/tile traversal and pixel retirement.

## Transform, clipping and projection

Setup captures command fields, issues the retained transform, and packs each
128-bit transformed geometry with its untouched six input attributes.
The 2D transform selector is base mode bit2 (modes6/7); precision is bit0.

Clipper uses two synchronous 384 by 320-bit banks. It seeds three vertices,
then executes seven ordered planes. PLANE_START issues the last-vertex read,
WAIT_A captures A; READ_B issues each B read, WAIT_B captures B. DISTANCE
registers both signed33 distances and CLASSIFY decides insertion.
Crossings iterate ten components through difference, multiply, divider issue,
divider wait and component-add registers. A separate FIX_PLANE state adjusts
only geometry. WRITE_I and WRITE_B preserve the parent's insertion order.
PLANE_DONE swaps banks only after all writes. OUTPUT_READ/CAPTURE/HOLD provides
a synchronous read and stable streaming output. Empty polygons still advance
through the remaining planes and complete with count0.

No polygon RAM is reset. A bank is read only after its current-command writes.
Uninitialized RAM read-register values never form a valid output.
Plane-distance functions are evaluated on combinational wires before capture,
not expanded as stateful automatic-function temporaries.

Projection serializes x, y, reciprocal q and quantized depth through one
g2_divider. PREPARE registers coordinate and denominator; MULTIPLY registers
screen/depth products; FORM_NUMERATOR widens and shifts exactly; ISSUE/WAIT
execute the division. q uses numerator 2^40 directly. Separate output registers
hold clamped x/y, exact reciprocal and clamped depth until transfer.
Setup counts projected retirements and waits for clipper done and equal count
before asserting its own done channel, including a last projection in flight.

## Fan and tile schedule

Engine stores projected vertices in synchronous 384 by 291-bit RAM, caching
vertex0 as the fan origin. FAN_READ1/CAPTURE1 and FAN_READ2/CAPTURE2 fetch the
other two vertices. AREA_SEND/WAIT uses g1_edge; a negative result swaps the
entire two 291-bit vertices. A zero result skips traversal; every nonzero fan
increments fan_total even if its bounds contain no viewport samples.

BOUNDS derives inclusive parent-style pixel bounds from projected Q9.8 extrema
and aligns first/last tile origins with constant masks. Explicit 9-bit
coordinate comparisons handle endpoint256, singleton and ragged viewports.
TILE_START counts the candidate. Enabled early-Z uses TILE_SEND/WAIT to scan
the current committed buffer. Rejected tiles go directly to NEXT_TILE.
Disabled early-Z skips the scan, not the candidate count or fragment depth test.
Surviving tiles issue one raster request. NEXT_TILE wraps x explicitly and
increments y by the fixed tile size; NEXT_FAN preserves original fan indices.

The G2 raster is the parent's edge/sample arithmetic with tile-clipped bounds,
g2_divider barycentrics and zero-invalid outputs. It never swaps vertex identity:
the engine has already normalized the complete payload. It computes the area,
then each sample's three registered edges. Only an included sample performs
the two exact floor divisions. Residual lambda2 is formed after lambda0 and
lambda1; the output sample holds until engine acceptance. Traversal is
tile-row, tile-column, pixel-y, pixel-x within each fan.

## Persistent depth and early-Z

The buffer has one 24-bit physical word per padded coordinate. For depth16 the
upper eight bits are zero, including clear words and all accepted writes.
The physical row stride is `1 << clog2(MAX_WIDTH)`; address formation is
shift/bitwise OR, not a division or modulo expression. Storage depth is the
product of power-of-two padded width/height. Padding is never scanned or exposed.
Width1 uses a zero-bit logical x shift and a safe minimum one-bit address vector.

All memory writes and registered reads use a dedicated posedge-only block.
Control resets asynchronously, but neither depth nor polygon RAM is reset.
RAM write enables are gated off during reset. Engine configuration validity
resets false, preventing any public transaction from observing old RAM.

Clear accepts dimensions/precision, visits x then y, and writes all active
pixels to maximum depth. CLEAR_DONE becomes valid only after the final write.
Engine then commits configuration. Invalid headers/configuration mismatches
never reach the buffer. A configuration mismatch leaves the old configuration
available for a subsequent correctly matching draw.

Tile scan reads every viewport pixel in the tile, including pixels outside the
triangle, through TILE_READ/ACCUMULATE. The last sample participates in the
maximum before the `zmin >= maximum` decision. The response is stable until
consumed. A scan is serialized with all fragment writes and recomputed per fan.
This rejects only tiles that cannot contain a strict-LESS passing fragment.

After raster acceptance, DEPTH_PRODUCT, DEPTH_PAIR and DEPTH_SUM register a
41-bit product per vertex, a 42-bit pair and an exact 43-bit sum; bits39:16
form depth. FRAG_READ issues a synchronous RAM read, FRAG_COMPARE tests unsigned
LESS. Failed results become visible without a write. Passing results go through
FRAG_WRITE; only after that write edge does FRAG_RESULT become valid.
No following scan or fragment can bypass this visibility point.

Engine increments fragment counters on result transfers, not request-valid
cycles. Only passing results invoke perspective interpolation. A stalled pixel
record can delay later service but cannot undo or duplicate its committed write.

## Divider and interpolation pipeline

The floor divider normalizes magnitude using six serial 16-bit limbs.
Each quotient bit consumes six cycles: shift into a 65-bit trial register;
four serial 16-bit subtraction/borrow limbs; decision/commit. The final borrow
and explicit trial top bit decide subtraction; there is no parallel wide
divisor comparison. Signed correction is another six-limb pass.
For opposite signs and a nonzero magnitude remainder, floor quotient is
one below truncation and the remainder is corrected toward denominator sign.
Outputs are masked invalid and held in HOLD. A simulation assertion rejects
an accepted zero denominator; internal legal callers supply nonzero values.
The fixed first-valid edge is E588, including all signs and zero numerators.

Interpolation keeps three exact 58-bit lambda*q products, a 59-bit pair
and 64-bit denominator. Signed weighted attributes are carried as 96-bit
products, pairs and numerators without truncation. Six parallel floor dividers
consume the same exact denominator. The state schedule is:

| Edge after acceptance | Registered work |
|---|---|
| E0 | Capture lambdas, reciprocals and all attributes |
| E1 | Three lambda*q products |
| E2 | Weight pair |
| E3 | Denominator |
| E4 | Eighteen signed weight*attribute products |
| E5 | Six signed pairs |
| E6 | Six signed numerators |
| E7 | All six divider inputs accepted |
| E595 | All six divider results first valid |
| E596 | Six signed32 results captured, output first valid |

State registers separate multiplier, pair sum, total and division boundaries.
No approximate reciprocal, float, combinational division/modulo, or simulation
replacement datapath is used. Physical multiplier mapping and actual timing
closure still require the admitted native gates.

### Quartus DSP clock-enable recovery

The retained mapping failure is
`evidence/preparation/verifier-coordinator-quartus-map-20261029T155314Z-45cc74aa/receipt.json`.
Quartus17.1 exited2 in DSP chain-adder inference with an incompatible
clock-enable assertion, before producing a mapped netlist. The diagnostic
does not identify the triggering module; the unsupported FAST FIT warning
is separate from that terminal assertion.

The deliverable `g1_dot4` and `g2_interpolator` now refresh their registered
multiply/add trees on every released clock edge instead of giving successive
arithmetic registers different state-decoded enables. Multipliers remain
eligible for DSP inference; no global or local DSP-disable assignment is used.
Widths, signedness, arithmetic expressions, asynchronous resets and register
boundaries are unchanged. Operand capture remains handshake-controlled, and
public result capture remains state-controlled, so intermediate refreshes
cannot change a stalled result or accept another transaction.

For the dot product, operands captured at E0 propagate through products at E1,
pairs at E2 and total at E3; saturation still captures at E4. For interpolation,
weights are correct at E1, the denominator at E3, and weighted products,
pairs and numerators are correct by their scheduled E4/E5/E6 edges.
The third-vertex product stays numerically stable while the pair propagates
because captured attributes and weights remain unchanged for the transaction.
All six dividers still accept at E7, with public output first valid after E596.
Earlier or repeated internal computations are not additional valid transactions.

This is the admitted inference repair, not evidence that Quartus mapping or
timing now passes. Independent behavioral/synthesis regression, fresh mapping
linked to the retained failure, and all mandatory native timing/hardware gates
remain required. Existing failed receipts must not be overwritten.

## Parent preservation and timing-oriented memory changes

All eight parent-named modules are present. Five are exact copies:
g1_divider, g1_edge, g1_project, g1_raster and g1_transform.
The deliverable g1_dot4 has the arithmetic-enable repair described above.
The deliverable g1_clipper and crucible_g1_top make only numerically neutral
synchronous-memory scheduling changes:

* Clipper bank reads gain explicit issue/capture states. RAM writes move to a
  non-resetting posedge-only process, with RAM inference attributes. Distance
  functions move to combinational wires before their existing capture.
* Top projected-polygon reads become one synchronous read port with two
  issue/capture pairs per fan; writes move to a posedge-only RAM process.

The memory changes avoid large asynchronous RAM muxes and reset-process memory
expansion while retaining every arithmetic operation, clip insertion order,
record, status, fan/sample order and handshake stability. They do not claim
cycle-for-cycle top latency. Retained leaf schedules are unchanged:
edge first valid E2, dot E4, parent divider E98. Independent legacy regression
against the mathematical model and immutable parent remains mandatory; these
edits are not certified by syntax elaboration.

## Capacity, serialization and limitations

At default parameters, depth RAM is 65536 by24 = 1,572,864 bits.
The G2 clip banks use 245,760 bits; G2 projected polygon 111,744 bits.
Legacy clip banks use 98,304 bits and legacy projected polygon 13,056 bits.
Total declared bulk storage is 2,041,728 bits before implementation rounding,
small control registers and arithmetic state. Padding can increase capacity
above the active viewport for non-power-of-two maxima, but never changes
the public coordinate domain. These are source-level capacities, not a fitted
block count or utilization measurement.

Each tile scan costs two service clocks per active tile pixel before response.
Each covered sample needs two serialized 588-cycle divider transactions for
barycentrics; passing samples additionally use the E596 interpolator contract
and thirteen output words. Setup cost depends on clipping intersections.
The single-command/single-fragment ownership intentionally prioritizes exact
numerics, bounded state transitions and provable visibility over throughput.
Backpressure adds unbounded wait by protocol; absent stalls every loop has an
explicit finite coordinate, component, vertex or quotient-bit bound.

The independent Verifier must exercise every numerical/coverage clause in
SPEC, preserve original failing receipts, detect the seven specified mutations,
and report regressions separately from pre-existing failures. Native STA/HIL
and final report approval remain pending until actually executed; neither a
parent intake nor this implementation is a passing baseline.
