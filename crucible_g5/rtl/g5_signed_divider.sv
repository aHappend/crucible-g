module g5_signed_divider (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire signed [63:0] s_numerator, s_denominator,
    output wire m_valid,
    input wire m_ready,
    output wire signed [63:0] m_floor, m_ceil,
    output wire [63:0] m_remainder,
    output wire m_error
);
    localparam IDLE=0, NORM_N_SEND=1, NORM_N_WAIT=2,
        NORM_D_SEND=3, NORM_D_WAIT=4, DIV_SEND=5, DIV_WAIT=6,
        SIGN_SEND=7, SIGN_WAIT=8, CEIL_SEND=9, CEIL_WAIT=10, HOLD=11;
    reg [3:0] state;
    reg [63:0] numerator, denominator, magnitude_n, magnitude_d;
    reg [63:0] quotient, remainder, truncation, floor_result, ceil_result;
    reg negative, error;
    reg [63:0] alu_a, alu_b;
    reg alu_subtract;
    wire alu_ready, alu_valid, alu_less, alu_equal, alu_carry;
    wire [63:0] alu_result;
    wire div_ready, div_valid, div_error;
    wire [63:0] div_quotient, div_remainder;
    wire alu_send=state==NORM_N_SEND || state==NORM_D_SEND ||
        state==SIGN_SEND || state==CEIL_SEND;
    wire alu_wait=state==NORM_N_WAIT || state==NORM_D_WAIT ||
        state==SIGN_WAIT || state==CEIL_WAIT;
    g5_limb_alu #(.WIDTH(64)) sign_arithmetic (
        .clk(clk),.rst_n(rst_n),.s_valid(alu_send),.s_ready(alu_ready),
        .s_a(alu_a),.s_b(alu_b),.s_subtract(alu_subtract),
        .m_valid(alu_valid),.m_ready(alu_wait),.m_result(alu_result),
        .m_less(alu_less),.m_equal(alu_equal),.m_carry(alu_carry)
    );
    g5_divider #(.WIDTH(64)) magnitude_divider (
        .clk(clk),.rst_n(rst_n),.s_valid(state==DIV_SEND),.s_ready(div_ready),
        .s_numerator(magnitude_n),.s_denominator(magnitude_d),
        .m_valid(div_valid),.m_ready(state==DIV_WAIT),
        .m_quotient(div_quotient),.m_remainder(div_remainder),.m_error(div_error)
    );
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_floor=m_valid && !error ? $signed(floor_result) : 64'sd0;
    assign m_ceil=m_valid && !error ? $signed(ceil_result) : 64'sd0;
    assign m_remainder=m_valid && !error ? remainder : 64'd0;
    assign m_error=m_valid && error;
    always @* begin
        alu_a=0; alu_b=0; alu_subtract=0;
        case (state)
            NORM_N_SEND: begin
                if (numerator[63]) begin alu_b=numerator; alu_subtract=1; end
                else alu_a=numerator;
            end
            NORM_D_SEND: begin
                if (denominator[63]) begin alu_b=denominator; alu_subtract=1; end
                else alu_a=denominator;
            end
            SIGN_SEND: begin
                if (negative) begin alu_b=quotient; alu_subtract=1; end
                else alu_a=quotient;
            end
            CEIL_SEND: begin alu_a=truncation; alu_b=64'd1; end
            default: begin end
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; numerator<=0; denominator<=0;
            magnitude_n<=0; magnitude_d<=0; quotient<=0; remainder<=0;
            truncation<=0; floor_result<=0; ceil_result<=0; negative<=0; error<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    numerator<=s_numerator; denominator<=s_denominator;
                    negative<=s_numerator[63]^s_denominator[63];
                    error<=s_denominator==0 ||
                        (s_numerator==64'sh8000000000000000 && s_denominator==-64'sd1);
                    state<=NORM_N_SEND;
                end
                NORM_N_SEND: if (alu_ready) state<=NORM_N_WAIT;
                NORM_N_WAIT: if (alu_valid) begin magnitude_n<=alu_result; state<=NORM_D_SEND; end
                NORM_D_SEND: if (alu_ready) state<=NORM_D_WAIT;
                NORM_D_WAIT: if (alu_valid) begin magnitude_d<=alu_result; state<=DIV_SEND; end
                DIV_SEND: if (div_ready) state<=DIV_WAIT;
                DIV_WAIT: if (div_valid) begin
                    quotient<=div_quotient; remainder<=div_remainder;
                    if (div_error) error<=1;
                    state<=SIGN_SEND;
                end
                SIGN_SEND: if (alu_ready) state<=SIGN_WAIT;
                SIGN_WAIT: if (alu_valid) begin
                    truncation<=alu_result;
                    floor_result<=negative && remainder!=0 ? ~quotient : alu_result;
                    ceil_result<=alu_result;
                    if (!negative && remainder!=0) state<=CEIL_SEND;
                    else state<=HOLD;
                end
                CEIL_SEND: if (alu_ready) state<=CEIL_WAIT;
                CEIL_WAIT: if (alu_valid) begin ceil_result<=alu_result; state<=HOLD; end
                HOLD: if (m_ready) state<=IDLE;
                default: begin
                    error<=1; state<=HOLD;
`ifndef SYNTHESIS
                    $fatal(1,"g5_signed_divider: invalid state");
`endif
                end
            endcase
        end
    end
endmodule
