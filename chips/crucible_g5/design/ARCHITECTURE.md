# CRUCIBLE-G5 architecture

## Ownership and implementation status

`design/SPEC.md` freezes the admitted numerical and public interface contract.
This is an incremental Designer source handoff, not engineering acceptance.
The currently implemented G5 modules are `g5_morton`, `g5_limb_alu`, `g5_mul`,
`g5_divider`, `g5_sqrt`, `g5_ray_triangle`, `g5_signed_divider`, `g5_slab`,
`g5_lbvh` and `g5_ray_query`. The denoiser and stream-wrapper implementation
remain pending. Builder/query connections are exposed as explicit internal
handshake ports, but are not yet wired by an integrated top. Do not treat this
partial source handoff as a completed G5 subsystem.

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
multiplier registers each partial product. Separate low-sum and high-sum
stages accumulate a schoolbook row into the result. A final registered
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
with three registered steps each, eight magnitude steps, eight row-end steps
and at most twelve sign steps: at most 202 internal steps after capture.
The triangle has 24 cross/dot multiplications and two interval products.
Each 192-bit division has 192*(1+12+1)=2688 internal steps after capture.
Nine differences, six cross subtractions, twelve dot additions, four possible
sign conversions and five range operations use the limb ALU. Including
request/response handshakes and control transitions, this folded schedule
fits the frozen 16384-cycle slot analytically. Independent Verifier must
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
bounds and division errors are explicit held errors. Top-level query wiring
still remains to be implemented. Parent pointers provide bounded stackless
left-first traversal. Inclusive current-best quantized-t pruning preserves
the complete equal-distance bin; triangles always use the original interval.

SVGF owns current attributes/samples, temporal history and two complete
ping-pong radiance/variance planes. Begin/write/clear operations and each
temporal/spatial pixel slot follow the frozen schedule. The positive self tap
keeps both normalization denominators nonzero. Memory ports must be synchronous
and large data arrays must not be bulk reset.

## Evidence boundary

Designer may run only fast static syntax/elaboration. Functional simulation,
the independent mathematical oracle, mutation sensitivity, synthesis,
resource measurements and portable clean-directory reproduction belong to
Verifier. Native L1.5/L2/L3 belong to the shared runtime. No passing result,
physical metric or independent approval is asserted here.
