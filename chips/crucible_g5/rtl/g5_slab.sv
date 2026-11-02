module g5_slab (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [95:0] s_origin, s_direction,
    input wire [191:0] s_bounds,
    input wire signed [63:0] s_t_min, s_t_max,
    output wire m_valid,
    input wire m_ready,
    output wire m_hit, m_error,
    output wire signed [63:0] m_t_enter, m_t_exit
);
    localparam IDLE=0, RANGE_SEND=1, RANGE_WAIT=2, AXIS=3,
        BOUNDS_SEND=4, BOUNDS_WAIT=5, LO_SEND=6, LO_WAIT=7,
        HI_SEND=8, HI_WAIT=9, DIV_SEND=10, DIV_WAIT=11,
        ENTRY_SEND=12, ENTRY_WAIT=13, EXIT_SEND=14, EXIT_WAIT=15,
        VERIFY_SEND=16, VERIFY_WAIT=17, HOLD=18;
    reg [4:0] state;
    reg [95:0] origin, direction;
    reg [191:0] bounds;
    reg [1:0] axis;
    reg signed [31:0] o, d, lo, hi;
    reg signed [63:0] numerator_lo, numerator_hi, axis_entry, axis_exit;
    reg signed [63:0] entry, exit_t;
    reg second, hit, error;
    reg [63:0] alu_a, alu_b;
    wire alu_ready, alu_valid, alu_less, alu_equal, alu_carry;
    wire [63:0] alu_result;
    wire div_ready, div_valid, div_error;
    wire signed [63:0] div_floor, div_ceil;
    wire [63:0] div_remainder;
    wire alu_send=state==RANGE_SEND || state==BOUNDS_SEND ||
        state==LO_SEND || state==HI_SEND || state==ENTRY_SEND ||
        state==EXIT_SEND || state==VERIFY_SEND;
    wire alu_wait=state==RANGE_WAIT || state==BOUNDS_WAIT ||
        state==LO_WAIT || state==HI_WAIT || state==ENTRY_WAIT ||
        state==EXIT_WAIT || state==VERIFY_WAIT;
    g5_limb_alu #(.WIDTH(64)) slab_arithmetic (
        .clk(clk),.rst_n(rst_n),.s_valid(alu_send),.s_ready(alu_ready),
        .s_a(alu_a),.s_b(alu_b),.s_subtract(1'b1),
        .m_valid(alu_valid),.m_ready(alu_wait),.m_result(alu_result),
        .m_less(alu_less),.m_equal(alu_equal),.m_carry(alu_carry)
    );
    g5_signed_divider divider (
        .clk(clk),.rst_n(rst_n),.s_valid(state==DIV_SEND),.s_ready(div_ready),
        .s_numerator(second ? numerator_hi : numerator_lo),
        .s_denominator({{32{d[31]}},d}),.m_valid(div_valid),
        .m_ready(state==DIV_WAIT),.m_floor(div_floor),.m_ceil(div_ceil),
        .m_remainder(div_remainder),.m_error(div_error)
    );
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_hit=m_valid && hit && !error;
    assign m_error=m_valid && error;
    assign m_t_enter=m_hit ? entry : 64'sd0;
    assign m_t_exit=m_hit ? exit_t : 64'sd0;
    always @* begin
        alu_a=0; alu_b=0;
        case (state)
            RANGE_SEND, VERIFY_SEND: begin alu_a=entry; alu_b=exit_t; end
            BOUNDS_SEND: begin alu_a={{32{lo[31]}},lo}; alu_b={{32{hi[31]}},hi}; end
            LO_SEND: begin alu_a={{32{lo[31]}},lo}; alu_b={{32{o[31]}},o}; end
            HI_SEND: begin alu_a={{32{hi[31]}},hi}; alu_b={{32{o[31]}},o}; end
            ENTRY_SEND: begin alu_a=axis_entry; alu_b=entry; end
            EXIT_SEND: begin alu_a=axis_exit; alu_b=exit_t; end
            default: begin end
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; origin<=0; direction<=0; bounds<=0; axis<=0;
            o<=0; d<=0; lo<=0; hi<=0; numerator_lo<=0; numerator_hi<=0;
            axis_entry<=0; axis_exit<=0; entry<=0; exit_t<=0;
            second<=0; hit<=0; error<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    origin<=s_origin; direction<=s_direction; bounds<=s_bounds;
                    entry<=s_t_min; exit_t<=s_t_max; axis<=0;
                    hit<=1; error<=0; state<=RANGE_SEND;
                end
                RANGE_SEND: if (alu_ready) state<=RANGE_WAIT;
                RANGE_WAIT: if (alu_valid) begin
                    if (alu_less || alu_equal) state<=AXIS;
                    else begin hit<=0; error<=1; state<=HOLD; end
                end
                AXIS: begin
                    o<=origin[axis*32 +:32]; d<=direction[axis*32 +:32];
                    lo<=bounds[axis*32 +:32]; hi<=bounds[96+axis*32 +:32];
                    second<=0; state<=BOUNDS_SEND;
                end
                BOUNDS_SEND: if (alu_ready) state<=BOUNDS_WAIT;
                BOUNDS_WAIT: if (alu_valid) begin
                    if (alu_less || alu_equal) state<=LO_SEND;
                    else begin hit<=0; error<=1; state<=HOLD; end
                end
                LO_SEND: if (alu_ready) state<=LO_WAIT;
                LO_WAIT: if (alu_valid) begin
                    numerator_lo<={alu_result[47:0],16'd0};
                    if (d==0 && !alu_less && !alu_equal) begin hit<=0; state<=HOLD; end
                    else state<=HI_SEND;
                end
                HI_SEND: if (alu_ready) state<=HI_WAIT;
                HI_WAIT: if (alu_valid) begin
                    numerator_hi<={alu_result[47:0],16'd0};
                    if (d==0) begin
                        if (alu_less) begin hit<=0; state<=HOLD; end
                        else if (axis==2) state<=HOLD;
                        else begin axis<=axis+2'd1; state<=AXIS; end
                    end else state<=DIV_SEND;
                end
                DIV_SEND: if (div_ready) state<=DIV_WAIT;
                DIV_WAIT: if (div_valid) begin
                    if (div_error) begin hit<=0; error<=1; state<=HOLD; end
                    else if (!second) begin
                        if (!d[31]) axis_entry<=div_floor;
                        else axis_exit<=div_ceil;
                        second<=1; state<=DIV_SEND;
                    end else begin
                        if (!d[31]) axis_exit<=div_ceil;
                        else axis_entry<=div_floor;
                        state<=ENTRY_SEND;
                    end
                end
                ENTRY_SEND: if (alu_ready) state<=ENTRY_WAIT;
                ENTRY_WAIT: if (alu_valid) begin
                    if (!alu_less && !alu_equal) entry<=axis_entry;
                    state<=EXIT_SEND;
                end
                EXIT_SEND: if (alu_ready) state<=EXIT_WAIT;
                EXIT_WAIT: if (alu_valid) begin
                    if (alu_less) exit_t<=axis_exit;
                    state<=VERIFY_SEND;
                end
                VERIFY_SEND: if (alu_ready) state<=VERIFY_WAIT;
                VERIFY_WAIT: if (alu_valid) begin
                    if (!alu_less && !alu_equal) begin hit<=0; state<=HOLD; end
                    else if (axis==2) state<=HOLD;
                    else begin axis<=axis+2'd1; state<=AXIS; end
                end
                HOLD: if (m_ready) state<=IDLE;
                default: begin
                    hit<=0; error<=1; state<=HOLD;
`ifndef SYNTHESIS
                    $fatal(1,"g5_slab: invalid state");
`endif
                end
            endcase
        end
    end
endmodule
