module g4_slab (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [95:0] s_origin, s_direction,
    input wire [191:0] s_bounds,
    input wire signed [63:0] s_t_min, s_t_max,
    output wire m_valid,
    input wire m_ready,
    output wire m_hit,
    output wire signed [63:0] m_t_enter, m_t_exit
);
    localparam IDLE=0, AXIS=1, DIFFERENCE=2, NUMERATOR=3,
               DIV_SEND=4, DIV_WAIT=5, INTERSECT=6, ADVANCE=7, HOLD=8;
    reg [3:0] state;
    reg [95:0] origin, direction;
    reg [191:0] bounds;
    reg [1:0] axis;
    reg signed [31:0] o, d, lo, hi;
    reg signed [32:0] delta_lo, delta_hi;
    reg signed [63:0] numerator_lo, numerator_hi, entry, exit_t;
    reg signed [63:0] axis_entry, axis_exit;
    reg second, hit;
    wire divider_ready, divider_valid, divider_error;
    wire signed [63:0] quotient_floor, quotient_ceil;
    wire [63:0] unused_remainder;
    wire signed [63:0] denominator={{32{d[31]}},d};
    g4_divider divider (
        .clk(clk),.rst_n(rst_n),.s_valid(state==DIV_SEND),
        .s_ready(divider_ready),
        .s_numerator(second ? numerator_hi : numerator_lo),
        .s_denominator(denominator),.m_valid(divider_valid),
        .m_ready(state==DIV_WAIT),.m_floor(quotient_floor),
        .m_ceil(quotient_ceil),.m_remainder(unused_remainder),
        .m_error(divider_error)
    );
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_hit=m_valid && hit;
    assign m_t_enter=m_hit ? entry : 64'sd0;
    assign m_t_exit=m_hit ? exit_t : 64'sd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; origin<=0; direction<=0; bounds<=0; axis<=0;
            o<=0; d<=0; lo<=0; hi<=0; delta_lo<=0; delta_hi<=0;
            numerator_lo<=0; numerator_hi<=0; entry<=0; exit_t<=0;
            axis_entry<=0; axis_exit<=0; second<=0; hit<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    origin<=s_origin; direction<=s_direction; bounds<=s_bounds;
                    entry<=s_t_min; exit_t<=s_t_max;
                    hit<=s_t_min<=s_t_max; axis<=0; state<=AXIS;
                end
                AXIS: begin
                    o<=origin[axis*32 +:32]; d<=direction[axis*32 +:32];
                    lo<=bounds[axis*32 +:32]; hi<=bounds[96+axis*32 +:32];
                    second<=0; state<=DIFFERENCE;
                end
                DIFFERENCE: begin
                    if (d==0) begin
                        if (o<lo || o>hi) hit<=0;
                        state<=ADVANCE;
                    end else begin
                        delta_lo<=$signed({lo[31],lo})-$signed({o[31],o});
                        delta_hi<=$signed({hi[31],hi})-$signed({o[31],o});
                        state<=NUMERATOR;
                    end
                end
                NUMERATOR: begin
                    numerator_lo<={{15{delta_lo[32]}},delta_lo,16'd0};
                    numerator_hi<={{15{delta_hi[32]}},delta_hi,16'd0};
                    state<=DIV_SEND;
                end
                DIV_SEND: if (divider_ready) state<=DIV_WAIT;
                DIV_WAIT: if (divider_valid) begin
                    if (divider_error) hit<=0;
                    if (!second) begin
                        if (d>0) axis_entry<=quotient_ceil;
                        else axis_exit<=quotient_floor;
                        second<=1; state<=DIV_SEND;
                    end else begin
                        if (d>0) axis_exit<=quotient_floor;
                        else axis_entry<=quotient_ceil;
                        state<=INTERSECT;
                    end
                end
                INTERSECT: begin
                    if (axis_entry>entry) entry<=axis_entry;
                    if (axis_exit<exit_t) exit_t<=axis_exit;
                    state<=ADVANCE;
                end
                ADVANCE: begin
                    if (!hit || entry>exit_t) begin hit<=0; state<=HOLD; end
                    else if (axis==2) state<=HOLD;
                    else begin axis<=axis+2'd1; state<=AXIS; end
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
