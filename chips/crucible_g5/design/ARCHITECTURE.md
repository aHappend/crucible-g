# CRUCIBLE-G5 architecture

## Ownership and implementation status

`design/SPEC.md` freezes the admitted numerical and public interface contract.
This is a Designer source handoff, not engineering acceptance.
The currently implemented G5 modules are `g5_morton`, `g5_limb_alu`, `g5_mul`,
`g5_divider`, `g5_sqrt`, `g5_ray_triangle`, `g5_signed_divider`, `g5_slab`,
`g5_lbvh`, `g5_ray_query`, `g5_svgf_surface`, `g5_svgf_channel`, `g5_svgf`
and `crucible_g5_top`. The integrated top wires the builder's real node store
to the query and arbitrates the same triangle solver between standalone and
query commands. The denoiser implements both channels in connected RTL.
Functional correctness, synthesis and physical acceptance remain unmeasured.

The accepted parent inventory is the 31 RTL files under
`crucible_g4_reference/rtl/`. Retain those bytes and inherited hierarchy.
All 31 files have been copied byte-identically into `rtl/`, without modifying
the reference directory. The inherited tops retain their original framing,
state commands, external memory interfaces and literal child hierarchy.
The shipped generational handoff now uses project-relative reference paths and
explicitly distinguishes historical connectivity-only HIL from numerical
validation. No verification-owned source is modified by Designer.

## Registered arithmetic

`g5_limb_alu` captures two same-width operands and an add/subtract control.
It processes one 16-bit limb per clock, low to high, retaining carry between
clocks. Comparison accumulates the most significant unequal limb and corrects
for operand signs in a separate register stage. The result is modular two's
complement arithmetic; callers provision enough width to avoid mathematical
overflow. All outputs are zero outside a held valid response.

`g5_mul` first converts signed operands to unsigned magnitudes using registered
16-bit carry steps, including the most-negative input. A folded 16x16
multiplier registers each partial product. Separate low-pair, low-sum and
high-sum stages accumulate a schoolbook row into the result, so two full
16-bit additions are not cascaded within one clock. A final registered
limb sweep applies the product sign. OUT_WIDTH can truncate a modular product;
the triangle's 192-bit output width exceeds the true mathematical precision
of every accepted intermediate, so it never truncates a significant bit.
The single registered multiplier is shared across triangle cross products,
dot products and interval products.

`g5_divider` is unsigned restoring division. Each quotient-bit iteration has
a registered shift, a full low-to-high subtraction sweep with one 16-bit
borrow dependency per clock, and a registered accept/reject step. Zero
denominators set an explicit held error response. The triangle sends only
nonnegative accepted numerators and strictly positive determinants, so integer
division directly implements mathematical floor without signed correction.

`g5_sqrt` consumes two radicand bits per iteration, MSB first. It registers
the shifted remainder and `(root<<2)|1` candidate, subtracts in 16-bit limbs,
then appends the acceptance bit to the root. The held output is the exact
floor square root. Root and remainder updates use concatenation, not a wide
combinational carry chain.

## Triangle microsequence

The triangle accepts a complete 31-word packed public command. Small register
banks retain six three-component vectors: e1, e2, direction, tv, p and q.
Nine limb-ALU differences preserve signed 33-bit vertex/origin subtraction.
Six cross components each use two shared multiplier calls and one limb
subtraction. Four three-term dot products use the multiplier and a 192-bit
registered accumulator; retained determinants/numerators are signed 128-bit,
which exceeds their full mathematical input-derived precision.

For negative determinant, two-sided processing negates all four retained
numerators with the limb ALU. Culling/degeneracy and sign tests precede the
inclusive barycentric and 192-bit exact-distance comparisons. Accepted hits
make three 192-bit restoring-divider calls for t/u/v; misses and malformed
requests never publish early. The explicit age counter exposes the record
exactly at E+16384 and holds every bit under backpressure. A computation that
does not finish before that boundary is an explicit internal error, not a
success-shaped fallback or implicit timing waiver.

Each 128x128-to-192 multiplication has 58 retained 16x16 partial products,
with four registered steps each, eight magnitude steps, eight row-end steps
and at most twelve sign steps: at most 260 internal steps after capture.
The triangle has 24 cross/dot multiplications and two interval products.
Each 192-bit division has 192*(1+12+1)=2688 internal steps after capture.
Nine differences, six cross subtractions, twelve dot additions, four possible
sign conversions and five range operations use the limb ALU. Including
request/response handshakes and control transitions, this folded schedule
fits the frozen 16384-cycle slot analytically. The additional partial-product
register stage changes internal arithmetic latency only; the public triangle,
builder and denoiser publication schedules remain unchanged. Independent Verifier must
measure every publication boundary; this arithmetic count is not execution
evidence or post-fit timing closure.

## Canonical builder and node store

`g5_lbvh` captures the public packed command. Primitive replacement compares
the signed high and unsigned low 16-bit vertex halves in registered parallel
stages, then selects the exact componentwise extrema. Three 48-bit limb
adders form the signed midpoint sums without overflow. Morton quantization
selects the shifted midpoint bits directly; the literal `morton` child
computes the interleave. A successful write updates the primitive RAM and
its initialization bit, invalidates the completed tree, and waits for the
64-cycle publication boundary.

The primitive RAM stores 288 vertex bits, 192 bound bits, a 30-bit Morton
code and the 32-bit primitive ID per insertion slot. Stable least-significant
bit radix sorting uses two 38-bit key banks. Each radix bit has an
`8*N+16` cycle slot: a count-zero sweep precedes a stable scatter sweep.
The first slot also loads keys and validates initialization. Invalid builds
do not modify the completed node store. A 64-cycle prefix and the 38 fixed
sorting slots leave the admitted `128*(2*N-1)` construction budget.

Construction maintains up to 39 interval frames, independent of inherited
`STACK_DEPTH`. Endpoint keys locate the highest differing composite-key bit;
a bounded binary search finds the first one-bit key. For interval [lo,hi]
split after s, left ID is parent ID+1 and right ID is parent ID+2*(s-lo+1).
These interval cardinalities produce canonical preorder IDs without a
median-split approximation. Children complete recursively before registered
16-bit-half comparisons select their exact union. Parent metadata is retained
in every node. The fixed publication counter uses separate 16-bit carry
steps; for N>0 the algebraically equivalent deadline is B(N)=544+560*N.
Finishing arithmetic early does not publish early.

Each node-RAM entry is 832 bits: the 512-bit public node record, 288 leaf
vertex bits (zero for internals), and a 32-bit parent. Both internal reads
and external query reads are synchronous. Packing vertices alongside the
node avoids a dependent primitive-RAM access on the fixed E+2 read path.
Reset invalidates metadata and cancels outstanding reads without resetting
these RAM arrays. A retained root record permits exact first-publication
timing without an asynchronous node-RAM read. Subsequent build records use
registered reads in ascending ID order, with a separation state after each
acceptance, then a terminal completion.

The query interface is `tree_valid/tree_count/tree_nodes`, plus
`rd_valid/rd_ready/rd_index` and
`rd_rsp_valid/rd_rsp_ready/rd_node/rd_vertices/rd_parent`.
Counts and indices are 32-bit public internal-interface fields, including
singleton capacity. A read response is captured at E+2 and holds until
accepted. Invalid indices return status 1 and zero vertices/parent.

## Stackless built-tree query

`g5_ray_query` captures the original interval and culling flag, validates
them with a limb comparison, then reads the actual node/vertex/parent port.
First arrivals validate parent linkage and unique visitation before invoking
the G5 slab engine and incrementing the node count. A surviving internal
node descends left; a completed/rejected leaf or subtree ascends by its
stored parent. Parent-return reads identify the completed child, visit the
right sibling after the left, and otherwise continue ascending. Returns do
not invoke slab or increment node counts. A visited bitmap, node-field
checks and the `3*node_count+1` transition budget detect repeated nodes,
broken links and cycles rather than looping. Leaf calls are bounded by N.

The explicit `tri_valid/tri_ready/tri_command` and
`tri_rsp_valid/tri_rsp_ready/tri_record` ports connect to the shared top-level
`triangle` instance. Every generated triangle command restores opcode 0x910,
the original query origin/direction/flag and exact requested t_min/t_max,
then supplies the leaf's stored vertices. It never uses the slab interval
or current best distance as triangle bounds. Successful candidates compare
quantized t, unsigned primitive ID and insertion slot using the limb ALU.
The best quantized t is used only as the inclusive upper bound for subsequent
outward-rounded slab tests. Public counters increment at first box-test
arrival and accepted leaf-solver request, respectively.

## Integration dependencies

| Producer | Consumer | Required guarantee |
|---|---|---|
| Stream wrapper | New command children | Exactly 31 accepted words, unchanged tag and reserved fields |
| Compatibility wrapper | G4 hierarchy | Byte-identical inherited 31/49-word replay and external side effects |
| Morton child | Builder | Registered x/y/z bit interleave at E+1 |
| Builder | Query | Actual canonical nodes, original vertices and parents; E+2 held read response |
| Query | Shared triangle | Original exact interval and cull flag, never pruning bounds |
| Triangle | Query | Fixed-latency exact t/u/v; quantized t/ID/slot tie ordering belongs to query |
| Temporal stage | Spatial stages | Valid moments plus original current surface attributes |
| Spatial pass | Next spatial pass | Complete ping-pong plane; no in-place filtering |
| Successful frame | Next temporal frame | Commit temporal moments once, independent of output stalls |
| All RAM metadata | Public interfaces | Reset invalidation prevents uninitialized data exposure |

The implemented `g5_slab` uses outward floor-entry/ceil-exit rounding without
modifying `g4_slab`. Its full-precision signed differences and interval
comparisons use a 64-bit limb ALU. `g5_signed_divider` wraps the unsigned
64-bit restoring engine with registered magnitude conversion, sign
application and floor/ceil correction. Negative nonintegral ratios produce
floor=-magnitude_quotient-1 and ceil=-magnitude_quotient; positive ones produce
floor=magnitude_quotient and ceil=magnitude_quotient+1. Zero directions use
closed signed slab membership without division. Bad intervals, inverted
bounds and division errors are explicit held errors. Parent pointers provide bounded stackless
left-first traversal. Inclusive current-best quantized-t pruning preserves
the complete equal-distance bin; triangles always use the original interval.

## Stream integration and inherited behavior

`crucible_g5_top` has the exact inherited public ports and retained parameter
defaults, plus the three admitted G5 capacity parameters. Its diagnostic-only
generate branch excludes the complete datapath for illegal parameters. This
applies the boundary-diagnostic principle of advisory lesson
`exp-6d5cc92e6f5a86894eaae275`, without treating that lesson as acceptance.

The wrapper buffers 49 words of storage but accepts exactly 31 words for
each G5 operation and for short inherited operations. Opcode word 2 selects
the inherited 49-word draw list verbatim. Every non-G5 command replays its
accepted words unchanged to the literal `compatibility` child. New packed
records are captured once, serialized in little-word order, and retain the
terminal flag through word 15. Only the selected response child sees ready.
Terminal acceptance returns to intake without accepting a new word on that
edge. Input bubbles, output stalls and reset do not alter packet boundaries.

The query owns the triangle solver only during QUERY_WAIT. Its packed
command, ready and response handshakes are muxed directly to `triangle`;
standalone 0x910 commands use that same instance. The builder mutation and
read/query operations are serialized, so a query cannot observe a partial
construction or concurrent primitive replacement.

Inherited-source review includes the parent inventory, all four top-level
routers, arithmetic/clipping/raster/setup/Z-buffer modules, texture/filter/
shader/DMA modules, BVH/slab/division modules and splat/sort/conic/compositor
modules. The ROM declaration, registered read and table endpoints were
inspected; its complete literal table is preserved rather than regenerated.
G1 uses saturating Q16 transform dots, seven closed clip planes, screen Q8
projection and top-left pixel coverage. G2 adds reciprocal-w perspective
attributes, 16/24-bit depth, strict-less fragment updates and tile rejection
at zmin >= tile maximum. G3 retains four direct-mapped texture block slots,
clamped bilinear sampling, integer shader/blend rounding and acknowledged
tile-order framebuffer DMA. G4 retains stable splat ordering, its supplied
conic ROM and alpha/transmittance arithmetic, and externally programmed BVH
nodes with its original inward-rounded slabs. G1, G2 and G3 retain their
respective 6-, 13- and 16-word output records; they are not repacked into G5
records. These are source-derived preservation requirements, not inferred
passing parent tests. No inherited datapath was changed.

## Connected two-channel SVGF

`g5_svgf` owns a 208-bit current sample RAM, two 256-bit temporal-history
banks and two complete 128-bit luminance/variance planes. All data RAM ports
are synchronous and writes replace entire entries, without byte enables or
bulk array reset. Each history entry contains two 32-bit means, two unsigned
32-bit second moments, original depth and original normal. One history bank
is the previous completed frame; the other receives pending temporal moments.
Current initialization and history-accept decisions are separate metadata
bitmaps. An initialized-pixel count permits constant-time run validation,
including non-power-of-two dimensions and the full 4096-pixel geometry.

Begin clears sample initialization and invalidates history on dimension
change or explicit reset. Sample validation checks all reserved fields,
radiance/depth/component/motion ranges and exact squared normal length
before writing RAM or initialization metadata. Invalid operations leave
previous samples/history intact. The surface engine captures three pairs of
16-bit unsigned normal magnitudes and their independent signs, including
both representations of magnitude 32768. Three registered 16x16 products
feed parallel 48-bit limb sign conversions and a folded exact 48-bit
reduction. It returns the raw dot for length validation, the clamped Q16
normal dot for edge stopping and a full-precision depth-difference decision.
For an eligible depth tap the dyadic depth shift is only 0 or 1: the hard
4096 threshold leaves the shift-one case exactly at absolute delta 4096.

Temporal reprojection uses registered 32-bit limb additions of integer
motion to x/y, then registered row-product and address stages. Out-of-bounds
or invalid history is never fed into accepted-history accumulation. Surface
depth/normal checks decide acceptance. Two literal channel lanes process
shadow and reflection independently; common attribute work is shared.
Each lane forms L squared with a full 32x32-to-64 folded product, applies
the specified seven-eighths rounded temporal recurrence with a 128-bit limb
ALU, and forms variance by exact subtraction with a zero lower bound.
Pending temporal moments and attributes are written to the inactive history
bank, independently of spatial filtering.

Each spatial pass completes every destination pixel before swapping planes.
The center stage uses a literal 48-bit iterative square-root child on
V<<16, then a registered limb addition and bounded leading-bit scan for
ceil_log2(4*sigma+256). Tap coordinates implement steps 1,2,4; invalid taps
are omitted rather than repeated/clamped. Hard normal/depth failures skip
the tap. Eligible normal weights undergo three registered 16x16 Q16
squarings; the exact value 65536 is handled as the identity rather than
truncated to 16 bits. Self taps explicitly use 65536. Depth/luminance
power-of-two factors are shifts, preserving each prescribed floor.

Per channel, registered kernel products produce w. Folded 32x32 products
form w*L and w*w; a 64x48-to-112 product zero-pads the **unsigned** variance
before using the signed multiplier port. Significant products fit within
96 bits and upper discarded bits are checked explicitly. Three 128-bit
accumulators hold sum(w), sum(w*L) and sum(w*w*V). The largest legal variance
numerator needs fewer than 96 bits: w <= 36*65536, V < 2^32 and at most
25 taps imply sum(w*w*V) < 2^82. Normalization therefore uses a literal
96-bit restoring divider after a checked narrowing of the 128-bit rounded
numerator. The full sum(w)^2 denominator is retained in 64 bits. Zero
denominator or unexpected quotient width produces status 4, never an
identity-output fallback.

Begin/write/clear acknowledgments publish at E+64. Valid runs allocate a
64-cycle prefix, exactly 1024 clocks per temporal pixel and exactly 8192
clocks per pixel in each of the three spatial passes. Parallel channel
handshakes consume both results only when both are valid, allowing unequal
arithmetic completion times without losing a lane. A slot-overrun detector
produces an explicit internal error (and a simulation diagnostic); padding
never masquerades as completed arithmetic. The last slot prefetches final
pixel 0 through synchronous RAM, permitting first publication exactly at
E+R(P). Later pixels are row-major, followed by one terminal completion.

Only successful completion of all slots swaps the temporal-history bank
and commits dimensions/validity, before exposing the first pixel. Output
backpressure therefore cannot duplicate temporal updates. Reset invalidates
both metadata epochs and cancels engines/output without resetting RAM data.
Clear history does not modify samples, scene primitives or the completed
tree. A completed run retains the active begin and current initialized
samples; a subsequent valid begin establishes fresh sample initialization.

## Analytical storage and schedule bounds

New denoiser data storage is 976*P bits, or 122*P bytes: 124928 bytes at
32x32 and 499712 bytes at 64x64, plus metadata and arithmetic registers.
The builder's primitive, node and two sort-key banks total
`542*N + 832*(2*N-1) + 76*N` bits at capacity N. No timing, inferred block
count or device-fit result is implied by these source-level capacity counts.

For the denoiser the surface handshake has approximately 32 clocks including
its caller's result capture. A worst eligible tap uses that shared surface
work, six normal-squaring clocks, two parallel channel sequences and bounded
coordinate/control overhead. Each channel tap uses two 128-bit absolute-
difference ALU calls, three accumulation ALU calls, two 32x32 products and
one 64x48 product. With the existing folded engines these are bounded by
200 clocks per channel/caller tap; sharing the surface and computing both
channels in parallel keeps all 25 taps below 6250 clocks. Center square root,
bandwidth selection and two 96-bit normalization divisions add fewer than
1900 clocks, within the fixed 8192 slot. Temporal accumulation and normal
validation fit their separate 1024/64 slots. These are conservative
microsequence counts, not measured simulation coverage or STA results.

## Evidence boundary

Designer may run only fast static syntax/elaboration. Functional simulation,
the independent mathematical oracle, mutation sensitivity, synthesis,
resource measurements and portable clean-directory reproduction belong to
Verifier. Native L1.5/L2/L3 belong to the shared runtime. No passing result,
physical metric or independent approval is asserted here.
