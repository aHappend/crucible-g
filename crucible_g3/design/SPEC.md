# CRUCIBLE-G3 interface and numerical specification

## Interface, reset and legal parameters

Top: `crucible_g3_top #(MAX_WIDTH=256, MAX_HEIGHT=256, TILE_LOG2=3)`.
Legal dimensions are every integer 1..256, independently; tile log2 is every
integer 0..4. Illegal parameters use diagnostic-safe internal widths and
simulation terminates nonzero with `PARAMETER ERROR`. Runtime viewport and
framebuffer dimensions are 1..their declared limits; texture dimensions 1..256.

All signals share `clk`. Active-low asynchronous `rst_n` resets control,
configuration, outstanding transactions and cache validity, not RAM contents.
During reset every public output is zero. One BOOT edge follows release;
the first word can transfer on the next edge. The bridge must cancel its
outstanding transactions on reset too. Never use RAM before explicit clear
or successful texture refill.

| Channel | Signals and meaning |
|---|---|
| Commands | input `s_valid`, output `s_ready`, input `s_data[31:0]` |
| Records | output `m_valid`, input `m_ready`, output `m_data[31:0]`, `m_last` |
| Texture request | output `tex_req_valid`, input `tex_req_ready`, output `tex_req_addr[31:0]` |
| Texture response | input `tex_rsp_valid`, output `tex_rsp_ready`, input `tex_rsp_data[31:0]`, `tex_rsp_error` |
| DMA request | output `dma_req_valid`, input `dma_req_ready`, output `dma_req_addr[31:0]`, `dma_req_data[31:0]`, `dma_req_strb[3:0]`, `dma_req_last` |
| DMA response | input `dma_rsp_valid`, output `dma_rsp_ready`, input `dma_rsp_error` |

All unwidth-qualified signals are one bit. Addresses are unsigned byte
addresses. Each memory bus has at most one outstanding transaction; a response
cannot precede the clock following accepted request. No unsolicited responses.
DMA response acknowledges completion of its write. Strobe is 0xf when valid.
All requests and stream output payloads hold while stalled. Inactive new
payload outputs are zero. Commands do not overlap: intake resumes only after
the terminal `m_last` handshake. Arbitrary response delay is legal under
eventual-response/acceptance fairness.

## Exact opcode and framing table

Every command starts with 31 words:
word 0 tag; word 1 `width | height<<16`; word 2 full 32-bit opcode;
words 3..18 row-major signed Q16.16 matrix; words 19..30 three x,y,z,w
signed Q16.16 vertices. Draws with attributes append 18 words, vertex 0..2
each containing six signed Q16.16 lanes u,v,r,g,b,a.

| Decimal | Hex | Operation | Words |
|---|---|---|---|
| 0,1 | 0x000,0x001 | Parent G1 3D,2D | 31 |
| 4,5 | 0x004,0x005 | Parent Z clear, 16/24-bit | 31 |
| 2,3,6,7 | 0x002,0x003,0x006,0x007 | Parent G2 draws, early-Z enabled | 49 |
| 258,259,262,263 | 0x102,0x103,0x106,0x107 | Parent G2 draws, early-Z disabled | 49 |
| 514,515,518,519 | 0x202,0x203,0x206,0x207 | G3 draws, early-Z enabled | 49 |
| 770,771,774,775 | 0x302,0x303,0x306,0x307 | G3 draws, early-Z disabled | 49 |
| 1024 | 0x400 | Texture configuration | 31 |
| 1025 | 0x401 | Shader configuration | 31 |
| 1026 | 0x402 | Color clear/configuration | 31 |
| 1027 | 0x403 | Framebuffer export | 31 |

These are exactly 24 distinct legal encodings, decoded without masks or
payload guesses. Draw bit 0 selects 24-bit rather than 16-bit depth; draw bit 2
selects 2D transform substitution; bit 8 disables early-Z; G3 bit 9 is removed
only for compatibility replay. Opcodes 0x300 and 0x301 remain invalid, not
state-command aliases. Invalid opcodes consume 31 words and use parent invalid
completion behavior. Recognized malformed/unconfigured draws still consume
all 49 words. Parent commands preserve bytes, ordering, records, statuses,
clipping, traversal, six lanes and strict depth behavior, not absolute latency.

## State descriptors and atomic validation

Each state command emits one sixteen-word G3 terminal record. Invalid
descriptors return status 1 and change no configuration or storage.
Missing/mismatched required configuration returns status 4.

* **0x400 texture:** word 1 texture dimensions, word 3 base, word 4 byte
  row stride, words 5..30 zero. Base/stride aligned to four bytes,
  stride >= 4*width. Check `base+(height-1)*stride+4*width-1 <= 0xffffffff`
  with full precision. Successful configuration invalidates all cache lines,
  even for an identical descriptor.
* **0x401 shader:** word 1 zero, word 3 program, words 4..30 zero.
  Program bit 0 enables texture, bit 1 selects modulation instead of
  replacement, bit 2 enables blending; bits 5:3 RGB source factor,
  8:6 RGB destination factor, 11:9 alpha source factor,
  14:12 alpha destination factor. Bits 31:15 zero. Each factor is
  0 ZERO, 1 ONE, 2 SRC_ALPHA, 3 ONE_MINUS_SRC_ALPHA,
  4 DST_ALPHA, 5 ONE_MINUS_DST_ALPHA. Encodings 6/7 are always invalid,
  including with blending disabled.
* **0x402 color:** word 1 framebuffer dimensions, word 3 RGBA8 clear color,
  words 4..30 zero. Successful clear configures color dimensions only,
  never implicitly clears Z.
* **0x403 export:** word 1 must match configured color dimensions, word 3
  destination base, word 4 byte row stride, words 5..30 zero.
  Apply the texture alignment, minimum-stride and full-precision
  last-byte check.

G3 draws require successfully configured shader and matching initialized color
dimensions; texture-enabled draws also require texture configuration. Check
these before replay so rejection cannot modify color or depth. Z configuration
is independently governed by the parent clear commands and their precision.

## Parent mathematical rules and fixed-width boundaries

Division denotes mathematical floor, including negative values; all operations
below are integer operations, never floating-point approximations.

Transform: each row sums four signed 32x32 products in signed 66 bits, shifts
arithmetically by 16, then saturates to signed32. For 2D replace input z with
zero and w with 65536 before the same matrix transform.

Clip in order against w>=1, x>=-w, x<=w, y>=-w, y<=w, z>=0, z<=w.
Signed33 plane distances are w-1,x+w,w-x,y+w,w-y,z,w-z.
For crossing edge A to B and distances fa,fb, interpolate every component by
`A + floor((B-A)*fa/(fa-fb))`. Differences are signed33, denominator signed34,
product signed66. The divider takes sign-extended signed96 numerator and
signed64 denominator. Its quotient is narrowed to signed33 offset; addition
uses signed34 and stores low32. Then correct the active coordinate exactly:
w=1, x=-w, x=w, y=-w, y=w, z=0, or z=w, respectively, in signed32 storage.
G2 clips all ten components (xyzw plus six attributes); G1 clips four.
Each plane traverses the closed polygon from its last vertex to vertex zero,
emitting intersections then inside endpoints. This determines fan order.

Projection uses
`floor((x+w)*width*256/(2*w))` and
`floor((w-y)*height*256/(2*w))`, clamped to [0,dimension*256].
Coordinates before dimension multiplication are signed33; product signed43,
then shift-by-eight is sign-extended into signed96 numerator. Screen x/y
store unsigned17. Reciprocal is `floor(2^40/w)`, stored unsigned41.
Depth is `floor(z*depth_limit/w)`, clamped to [0,depth_limit] and stored
unsigned24, where limit is 65535 or 16777215. Depth product uses signed57.

For each fan, edge area uses signed18 coordinate differences, signed36
products and signed37 subtraction. Normalize negative orientation by swapping
vertices 1 and 2, with their attributes. Zero-area fans emit no pixels.
Sample centers are `(x*256+128,y*256+128)`. An edge owns its boundary iff
`dy<0 || (dy==0 && dx>0)`; test all three nonnegative edges with that
top-left tie rule. The bounding range is floor(min/max screen coordinate/256),
clipped to viewport. G1 scans rows. G2/G3 traverse tile y then tile x,
and row-major samples inside cropped bounding tiles.

`lambda0=floor(edge0*65536/area)`, likewise lambda1; lambda2 is
`65536-lambda0-lambda1`; all store unsigned17. Pixel depth is
`floor(sum(lambda_i*z_i)/65536)` (three unsigned41 products, unsigned42 pair,
unsigned43 total, bits39:16 stored). Pass iff new depth **strictly less**
than stored depth, then write depth. Z clear stores the selected depth limit.
Early tile reject is `triangle_min_depth >= maximum_stored_tile_depth`;
bit 8 skips only this optimization, not fragment Z testing.

Perspective attribute for each lane is
`floor(sum(lambda_i*q_i*a_i)/sum(lambda_i*q_i))`.
Weights store unsigned58; pair unsigned59 and denominator unsigned64.
Each weight is extended positive signed59 before multiplication by signed32;
products and numerator accumulation store signed96. The quotient stores low32
as the parent signed representation, not saturation. Raw interpolated lanes
are preserved in output records even when shader clamps their color use.

Parent statuses are 0 success, 1 invalid, 2 clipped away, 3 degenerate,
4 missing/mismatched Z configuration. G1 records are six words:
fragment `[0,tag,packed_xy_fan,lambda0,lambda1,lambda2]`,
terminal `[1,tag,status,pixels,fan_count,0]`. G2 records are thirteen words:
fragment `[0,tag,packed_xy_fan,lambda0,lambda1,lambda2,depth,u,v,r,g,b,a]`;
terminal `[1,tag,status,pixels,fan_count,tiles_tested,tiles_rejected,
fragments_tested,fragments_passed,fragments_failed,0,0,0]`.
Packed xy/fan is x[7:0], y[15:8], fan[24:16], high seven bits zero.
Only the final terminal word asserts `m_last`.

## Cache and bilinear arithmetic

RGBA8 packs R in bits7:0, G15:8, B23:16, A31:24. u,v are signed Q16.16
texel coordinates, not normalized. Clamp each to
`[0,(dimension-1)*65536]`, take floor integer and unsigned16 fraction,
clamp the +1 neighbor. Four lookups occur in T00,T10,T01,T11 order,
including duplicated edge samples. Count every lookup as hit or miss.

A line contains sixteen texels of a 4x4 block. Four direct-mapped lines use
index `{block_y[0],block_x[0]}` and full block-coordinate tags. Misses issue
exactly sixteen reads in row-major block order, independently clamping each
refill coordinate to the edge (repeated addresses remain real requests).
Do not validate a partial refill or assume asynchronous multiport RAM.
Preserve already gathered footprint samples across replacements. Hits issue
no memory reads. Backing texture memory must be immutable until reconfigured.

For each channel, with fx,fy unsigned16 and weights (65536-fx),fx and
(65536-fy),fy, compute
`floor((T00*(65536-fx)*(65536-fy) + T10*fx*(65536-fy)
+ T01*(65536-fx)*fy + T11*fx*fy + 2^31)/2^32)`.
No horizontal rounding. Horizontal products/sums use 25/26 bits,
vertical products 43 bits and total 44 bits, preserving full precision.
Endpoint texels, singleton axes and odd texture sizes use the same formula.

Literal `g3_bilinear` accepts packed128 texels (T00 least-significant),
fx/fy16 and ready/valid; returns RGBA32. Literal `g3_texture_cache` accepts
validated base/stride32, dimensions9 via cfg_valid/cfg_ready, sample u/v
signed32 via s_valid/s_ready, returns RGBA32 and error with m_valid/m_ready,
and exposes the top texture bus. Its literal child is named `filter`.

## Shader arithmetic

Quantize each signed Q16.16 color:
`floor((clamp(a,0,65536)*255+32768)/65536)`.
Texture disabled selects vertex RGBA. Texture enabled replaces with filtered
RGBA unless modulation selected:
`floor((vertex_channel*texture_channel+127)/255)`.
With blending disabled write source. Otherwise independently select RGB and
alpha factors from unmodified source alpha and old destination alpha;
ONE=255, complements=255-alpha, then
`min(255,floor((src*src_factor+dst*dst_factor+127)/255))`.
Use old destination for every channel including alpha. Equation is saturated
ADD, with no alpha test/discard, premultiplied inference or deferred-Z change.

For bounded nonnegative integer n<=130177, set t=n+1. Exact floor(n/255)
equals `(t+(t>>8)+(t>>16))>>8`. To see this, write t=256h+l.
For h<256, h+l lies in 1..510; the quotient is
h+floor((h+l)/256). For 256<=h<=508, the quotient is
h+floor((h+l+1)/256). These are precisely the carry corrections in the
identity. The implementation uses bounded 19-bit additions; no division
cell is required.

Literal `g3_shader_pipeline` accepts vertex RGBA128 (four signed32 lanes,
R least-significant), texture32, destination32 and program15 through
s_valid/s_ready, and returns RGBA32 through m_valid/m_ready. Fixed six-cycle
latency and no same-edge replacement are defined in ARCHITECTURE.md.

## Framebuffer, export, records and errors

Literal `g3_framebuffer_dma` shares top parameters. Clear dimensions9/color32,
read xy8, write xy8/color32 and export base/stride32 each have request
valid/ready and completion valid/ready (read returns color32; export returns
error and successful words32). Top arbitrates mutually exclusive operations.
Read is synchronous; read-before-write guarantees old-destination blending.
No reset-loop initialization is inferred.

Export tile order is increasing tile_y, then tile_x; inside a cropped tile
increasing local_y then local_x. Exactly width*height requests at
base+y*stride+4*x, no padding/offscreen writes. Strobes=0xf.
Last marks only the final request and holds under stalls. The final
acknowledgement completes export; storage is not cleared, so repeats are
deterministic.

G3 fragment records contain sixteen words:
`[2,tag,packed_parent_xy_fan,lambda0,lambda1,lambda2,depth,u,v,r,g,b,a,
filtered_texture_rgba,source_rgba,final_framebuffer_rgba]`.
Filtered texture field is zero when disabled. Terminal:
`[3,tag,status,pixels_written,fan_count,tiles_tested,tiles_rejected,
fragments_tested,fragments_passed,fragments_failed,texture_hits,
texture_misses,dma_words,0,0,0]`.
All counters are unsigned32, reset per command; non-applicable fields zero.
Only terminal word15 asserts last.

Status5 indicates texture/DMA response error. Texture error invalidates all
cache lines; failed fragment produces no color write or pixel record, then
compatibility drains without more shading. Earlier color and all depth writes
remain; no rollback. DMA error stops new requests after the failed
acknowledgement and counts only successful acknowledgements; earlier external
writes remain. Explicit clear/reconfiguration performs recovery.

## Verification contract

Independent checks must reject active X/Z, numerical mismatch, unstable stalled
payloads, malformed/duplicate/reordered records, bad last, unexpected requests
and error-shaped success. Main configurations: (1,1,0), (13,11,0), (13,11,3),
(19,17,4), (256,256,3). Static elaborations cover all legal tile logs and
representative non-powers of two; illegal widths/heights 0/257 and tile logs
-1/5 must explicitly reject.

Per seed 17,89,233: >=48 legacy/G2 draws, >=48 G3 draws, >=256 filter samples,
>=256 shader vectors. Exercise every mode, depth precision, early-Z setting,
nonidentity/perspective/clipping, all seven planes, windings, degenerates,
shared edges, equal/pass/fail Z, signed lanes, alpha/color endpoints/interiors,
all six factors in each position and saturation. Include explicit 6x6 RGB
and 6x6 alpha-factor matrices. Observe cold/hit/replacement/four-block cache
crossings, odd edges, identical reconfiguration, >=8 same-block repetitions
with no reads after initial refill, exact sixteen reads per successful miss.
Exercise framebuffer/export 1x1,1x17,19x1,13x11,256x256, corner writes and
cropped tiles. Compare every exported address/data/strobe/last and final bytes.
Assert directed coverage bins, not just stimulus labels.

Exercise every legal opcode with complete correctly sized distinct-tag frame
and independently checked response/effects. Immediately follow each terminal
consumption with a checked valid command at the first allowed intake edge;
account accepted beats and completions. Include 0x302/0x303 successful G3
draws with nontrivial attributes; invalid prerequisites and invalid
0x300/0x301; stalled header/attribute/terminal boundaries; no premature intake.
Malformed descriptors include dimensions, alignment, short stride, overflow,
reserved bits and factors; assert unchanged state. Stall every public channel
and reset during input/output/refill/export. Error responses require recovery.

Six isolated compiling mutants must yield specific independent numerical
mismatches: filter, cache tag/validity, shader factor/complement, depth compare,
perspective interpolation, DMA address/tile edge. Compilation failure or
generic timeout does not kill a mutant. Yosys must find connected rendering,
cache, shader, framebuffer/DMA state, zero latches, unresolved black boxes,
multiple drivers, undriven problems and division/modulo cells at (13,11,3)
and (1,1,0). Portable reproduction must execute fresh-root real Icarus smoke,
numerical comparisons and Yosys checks without parent/runtime dependencies.
Every suite is self-contained and retains immutable source-bound receipts.
Native timing and hardware gates remain mandatory, not replaced by L1.
