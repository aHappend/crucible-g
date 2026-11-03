module g1_divider (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire signed [95:0] s_numerator,
    input wire signed [63:0] s_denominator,
    output wire m_valid,
    input wire m_ready,
    output wire signed [95:0] m_quotient,
    output wire signed [63:0] m_remainder
);
    localparam IDLE=3'd0, NORMALIZE=3'd1, ITERATE=3'd2,
               CORRECT=3'd3, HOLD=3'd4;
    reg [2:0] state;
    reg signed [95:0] numerator;
    reg signed [63:0] denominator;
    reg [95:0] quotient;
    reg [63:0] divisor;
    reg [63:0] remainder;
    reg [6:0] iteration;
    reg negative_q,negative_d;
    reg signed [95:0] result_q;
    reg signed [63:0] result_r;
    wire [64:0] trial = {remainder,quotient[95]};
    wire [64:0] trial_difference = trial-{1'b0,divisor};
    wire subtract_ok = trial>={1'b0,divisor};
    wire adjust_floor = negative_q && remainder!=0;
    wire [95:0] negative_quotient = (~quotient)+96'd1;
    wire [63:0] negative_remainder = (~remainder)+64'd1;
    wire [63:0] positive_floor_remainder = divisor-remainder;
    wire [63:0] negative_floor_remainder = remainder-divisor;

    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_quotient = m_valid ? result_q : 96'sd0;
    assign m_remainder = m_valid ? result_r : 64'sd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;
            numerator<=0; denominator<=0;
            quotient<=0; divisor<=0; remainder<=0; iteration<=0;
            negative_q<=0; negative_d<=0; result_q<=0; result_r<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    numerator<=s_numerator;
                    denominator<=s_denominator;
                    state<=NORMALIZE;
                end
                NORMALIZE: begin
                    quotient<=numerator[95] ? (~numerator)+96'd1 : numerator;
                    divisor<=denominator[63] ? (~denominator)+64'd1 : denominator;
                    negative_q<=numerator[95]^denominator[63];
                    negative_d<=denominator[63];
                    remainder<=0;
                    iteration<=0;
                    state<=ITERATE;
                end
                ITERATE: begin
                    quotient<={quotient[94:0],subtract_ok};
                    if (subtract_ok) remainder<=trial_difference[63:0];
                    else remainder<=trial[63:0];
                    if (iteration==7'd95) state<=CORRECT;
                    else iteration<=iteration+7'd1;
                end
                CORRECT: begin
                    if (negative_q) begin
                        if (adjust_floor) result_q<= ~quotient;
                        else result_q<=negative_quotient;
                    end else result_q<=quotient;
                    if (negative_d) begin
                        if (adjust_floor) result_r<=negative_floor_remainder;
                        else result_r<=negative_remainder;
                    end else begin
                        if (adjust_floor) result_r<=positive_floor_remainder;
                        else result_r<=remainder;
                    end
                    state<=HOLD;
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
