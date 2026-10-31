# CRUCIBLE-G3 architecture

## Cycle and degenerate-boundary table

All transfers sample **pre-edge** `valid && ready`. Register updates become
visible post-edge and cannot transfer a second beat on that same edge.

| Boundary | Required implementation behavior |
|---|---|
| Reset low | Asynchronous control reset; all public outputs zero, including ready and payload. RAM has no reset loop. |
| First edge after reset release | Top exits BOOT; word zero can first transfer on the following edge. |
| Parser/replay/output | Exactly one word per accepted edge; intake resumes only after terminal last-word consumption. |
| Bilinear input at E0 | Capture E0, horizontal products E1, sums E2, vertical products E3, sum E4, rounded result valid E5. |
| Shader input at E0 | Capture E0, quantize E1, modulation products E2, source/factors E3, blend products E4, sums E5, normalized result valid E6. |
| Leaf output stall | Hold result; no replacement input on result-consumption edge. |
| Framebuffer read at E0 | Capture address E0, synchronous RAM read E1, result valid E2. |
| Framebuffer write at E0 | Capture E0, actual RAM write E1, done valid post-E1. |
| Clear | Completion follows final actual write, not descriptor acceptance. |
| Export | One outstanding request; completion follows final acknowledgement, not request last. |
| 1x1 framebuffer, tile size one | First pixel is also final pixel; one actual clear/write/export; singleton address width is one. |
| Non-power-of-two dimensions | Explicit endpoint comparisons; padded physical RAM rows never exported or sampled. |
| Cropped tile | Wrap local x at min(tile end, width-1), local y at min(tile end, height-1). |
| Coincident operation inputs | Framebuffer clear, read, write, export priority in that order; top only issues mutually exclusive operations. |
| Cache reconfiguration and sample | Configuration wins; sample ready is low while cfg_valid. |
| Reset and any transfer | Reset cancels control, configuration and outstanding logical transactions; bridge must reset its transactions too. |
| Failed texture response | No color write for that fragment, invalidate all lines, drain compatibility, return status 5. |
| Failed DMA acknowledgement | Stop requests, do not count failed write, retain earlier effects. |

This table was fixed before adding G3 RTL.

## Connected datapath and ownership

`crucible_g3_top` buffers one complete command. Exact opcode decoding selects
31 or 49 words, independently of configuration and descriptor data. Parent
commands replay unmodified into `compatibility: crucible_g2_top`; G3 draws replay
there after removing only bit 9. `compatibility.legacy` and
`compatibility.engine`, including their transform, clip, project, raster,
interpolation and depth-store children, are retained. There is only one depth
store and geometry implementation.

For G3, the wrapper gathers each thirteen-word accepted parent fragment before
shading. It samples `texture_cache: g3_texture_cache`, reads the old destination
through `framebuffer_dma: g3_framebuffer_dma`, computes
`shader: g3_shader_pipeline`, writes color, then emits a sixteen-word record.
Backpressure stops compatibility between fragments. Errors drain its output
without further shading so parent Z writes and terminal statistics remain real.

Texture-cache lookups are sequential. Four direct-mapped lines each hold a 4x4
block (256 bytes total). The synchronous single-read datapath gathers four
texels into holding registers, even when subsequent misses replace earlier
lines. A miss invalidates its target before sixteen row-major single-outstanding
reads and marks it valid only after all responses succeed. Full block x/y tags
use six bits per coordinate; the low bit of each selects the line.
`filter: g3_bilinear` performs exact unrounded horizontal sums before vertical
weighting. Its result has the fixed five-cycle leaf latency.

The wrapper maintains a tag-only mirror to count the four lookups without
adding debug/status ports to the fixed cache interface. It updates that mirror
in lookup order after each sample. Successful sixteen-response refill groups
identify the prefix preceding a failed refill, so error accounting stops at
the failed miss and invalidates the mirror along with the cache.

The shader is programmable fixed-function, not an instruction processor.
Registered stages separate quantization, texture products, factor selection,
blend products and summation. Division by 255 uses an exact bounded integer
identity, not a division operator. All modes retain six-cycle leaf latency.
The wrapper obtains the source-record value by a shader pass with blending
disabled, then performs the configured pass against the same captured old
destination. This shares the numerical implementation without adding ports.

RGBA framebuffer capacity is `4 * 2^ceil(log2(MAX_WIDTH)) *
2^ceil(log2(MAX_HEIGHT))` bytes (262144 at maximum). Padding is internal only.
RAM writes and registered reads occupy a synchronous process without array
reset. Tile export walks increasing tile y, tile x, local y, local x; explicit
wrap counters handle singleton and cropped boundaries. Row address arithmetic
is registered; only acknowledged successful DMA writes increment its count.

## Timing intent and tradeoffs

Target: Intel Arria 10 GX 10AX115N2F45E1SG, 100 MHz or faster, clock period
at most 10.0 ns. No combinational division/modulo operators are permitted.
Parent signed division uses limb-based registered restoring arithmetic in the
delivered copy, preserving numerical behavior while changing absolute latency.
Specifically, `g1_divider` delegates to `g2_divider` rather than the original
wide single-cycle correction/subtraction path. `g2_interpolator` accumulates
each signed96 numerator as six registered 16-bit limbs, preserving the same
two's-complement result and low32 quotient storage. These are the only changes
to the standalone copies of the seventeen parent modules; the supplied parent
directory remains unchanged.
Multipliers and adders are separated by registers; the G3 path introduces no
single-cycle 96-bit carry chain. Texture/export address generation separates
row multiplication and address addition.

Single-in-flight arithmetic and single-outstanding memory buses favor bounded
logic depth, explicit recovery and small memories over throughput. No fixed
command latency is claimed. Four hits need no external reads; each successful
miss requires exactly sixteen accepted reads, including repeated edge addresses.
The texture backing store is immutable between configurations. The environment
must eventually accept requests and supply responses. No physical bandwidth or
timing-closure result is asserted by this architecture.

## Source dependencies and reproduction

Deliverable design inputs are `rtl/*.sv` and `design/*.md`. All required parent
modules are copied under `rtl/`; `crucible_g2_reference/rtl/` is unchanged
provenance and a supplemental differential-verification input, not a product
dependency. Verification inputs under `tests/` are independently owned.

From the delivered root, using Python 3, Icarus (`iverilog`, `vvp`), Verilator,
GNU make, a C++ compiler, and Yosys:

```
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite defects
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite reproduce
```

These are the admitted Verifier entry points, not Designer execution claims.
The Verifier records actual tool versions and source-bound receipts in fresh
`evidence/<suite>-<timestamp_or_hash>/` directories. Interpreted simulation is
restricted to compact smoke; seeded sweeps and compiling mutants use compiled
Verilator. Reproduction copies only declared deliverables into a fresh root.
No local hardware identifiers, credentials or runtime-state inputs are needed.

## Claim-to-evidence map and delivery limitations

| Claim | Required independent evidence (pending at initial Designer handoff) |
|---|---|
| Geometry, framing, filtering, shader and DMA semantics | behavior suite: independent bit-exact models, all-opcode accepted-beat accounting, seeds 17/89/233, directed boundary and recovery bins |
| Tests detect real RTL defects | defects suite: six compiling isolated mutants, specific numerical mismatches |
| Connected synthesizable storage and logic; no latches/division | synthesis suite: real Yosys checks for (13,11,3) and (1,1,0) |
| Standalone portable package | reproduce suite: fresh-root real smoke, numerical and structural checks |
| 100 MHz target implementation | Shared-runtime native L1.5 timing lint and Quartus 17.1 STA, WNS >= 0 at <= 10 ns |
| Physical integration | Shared-runtime native Arria 10 GX PCIe Gen3x8 bridge HIL, >= 3 consecutive deterministic passes |
| Final product PDF | Runtime authors/reviews/renders after engineering acceptance |

Source implementation and static elaboration do not certify any of these
acceptance claims. No timing waiver is admitted. Report rendering is not a
prerequisite to engineering verification.
