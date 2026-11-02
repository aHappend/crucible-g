# CRUCIBLE-G5 architecture

## Ownership and implementation status

`design/SPEC.md` freezes the admitted numerical and public interface contract.
This is an incremental Designer source handoff, not engineering acceptance.
The currently implemented G5 modules are `g5_morton`, `g5_limb_alu`, `g5_mul`,
`g5_divider`, `g5_sqrt`, `g5_ray_triangle`, `g5_signed_divider` and `g5_slab`.
Integrated builder, query,
denoiser and stream-wrapper implementation remains pending. Do not treat these
standalone arithmetic sources as a completed G5 subsystem.

The accepted parent inventory is the 31 RTL files under
`crucible_g4_reference/rtl/`. Retain those bytes and inherited hierarchy.
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

## Planned integration dependencies

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
bounds and division errors are explicit held errors. Query integration
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
