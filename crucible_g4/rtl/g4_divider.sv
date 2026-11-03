module g4_divider (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire signed [63:0] s_numerator, s_denominator,
    output wire m_valid,
    input wire m_ready,
    output wire signed [63:0] m_floor, m_ceil,
    output wire [63:0] m_remainder,
    output wire m_error
);
    localparam IDLE=0, PREP=1, STEP=2, TRUNCATE=3, CORRECT=4,
               PUBLISH=5, HOLD=6;
    reg [2:0] state;
    reg signed [63:0] numerator, denominator, truncation;
    reg negative, error;
    reg [63:0] dividend, divisor, quotient, remainder;
    reg [5:0] step;
    reg signed [63:0] floor_result, ceil_result;
    wire [64:0] shifted={remainder,dividend[63]};
    wire subtract=shifted>={1'b0,divisor};
    wire [64:0] difference=shifted-{1'b0,divisor};
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_floor=m_valid && !error ? floor_result : 64'sd0;
    assign m_ceil=m_valid && !error ? ceil_result : 64'sd0;
    assign m_remainder=m_valid && !error ? remainder : 64'd0;
    assign m_error=m_valid && error;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; numerator<=0; denominator<=0; truncation<=0;
            negative<=0; error<=0; dividend<=0; divisor<=0;
            quotient<=0; remainder<=0; step<=0;
            floor_result<=0; ceil_result<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    numerator<=s_numerator; denominator<=s_denominator;
                    error<=s_denominator==0 ||
                        (s_numerator==64'sh8000000000000000 &&
                         s_denominator==-64'sd1);
                    state<=PREP;
                end
                PREP: begin
                    dividend<=numerator[63] ? (~numerator+64'd1) : numerator;
                    divisor<=denominator[63] ? (~denominator+64'd1) : denominator;
                    negative<=numerator[63]^denominator[63];
                    quotient<=0; remainder<=0; step<=0; state<=STEP;
                end
                STEP: begin
                    dividend<={dividend[62:0],1'b0};
                    quotient<={quotient[62:0],subtract};
                    if (subtract) remainder<=difference[63:0];
                    else remainder<=shifted[63:0];
                    if (step==63) state<=TRUNCATE;
                    else step<=step+6'd1;
                end
                TRUNCATE: begin
                    truncation<=negative ? (~quotient+64'd1) : quotient;
                    state<=CORRECT;
                end
                CORRECT: begin
                    floor_result<=negative && remainder!=0 ?
                        truncation-64'sd1 : truncation;
                    ceil_result<=!negative && remainder!=0 ?
                        truncation+64'sd1 : truncation;
                    state<=PUBLISH;
                end
                PUBLISH: state<=HOLD;
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
