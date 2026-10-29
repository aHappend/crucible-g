module g2_divider (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire signed [95:0] s_numerator,
    input wire signed [63:0] s_denominator,
    output wire m_valid,
    input wire m_ready,
    output wire signed [95:0] m_quotient,
    output wire signed [63:0] m_remainder
);
    localparam IDLE=0, NORMALIZE=1, SHIFT=2, SUBTRACT=3,
               DECIDE=4, CORRECT=5, HOLD=6;
    reg [2:0] state;
    reg [2:0] limb;
    reg [6:0] iteration;
    reg [95:0] raw_n, quotient, result_q;
    reg [63:0] raw_d, divisor, remainder, difference, result_r;
    reg [64:0] trial;
    reg negative_n, negative_d, negative_q;
    reg carry_n, carry_d, borrow, carry_q, carry_r, adjust;
    wire [15:0] n_limb = raw_n[limb*16 +:16];
    wire [15:0] d_limb = raw_d[limb[1:0]*16 +:16];
    wire [16:0] norm_n =
        {1'b0,(negative_n ? ~n_limb : n_limb)} + {16'd0,carry_n};
    wire [16:0] norm_d =
        {1'b0,(negative_d ? ~d_limb : d_limb)} + {16'd0,carry_d};
    wire [16:0] sub_limb =
        {1'b0,trial[limb[1:0]*16 +:16]} -
        {1'b0,divisor[limb[1:0]*16 +:16]} - {16'd0,borrow};
    wire accept_subtract = trial[64] || !borrow;
    wire [15:0] q_limb = quotient[limb*16 +:16];
    wire [16:0] corrected_q =
        {1'b0,(negative_q ? ~q_limb : q_limb)} + {16'd0,carry_q};
    wire [15:0] r_limb = remainder[limb[1:0]*16 +:16];
    wire [15:0] v_limb = divisor[limb[1:0]*16 +:16];
    wire [15:0] r_left = adjust ?
        (negative_d ? r_limb : v_limb) : 16'd0;
    wire [15:0] r_right = adjust ?
        (negative_d ? ~v_limb : ~r_limb) :
        (negative_d ? ~r_limb : r_limb);
    wire [16:0] corrected_r =
        {1'b0,r_left}+{1'b0,r_right}+{16'd0,carry_r};

    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_quotient = m_valid ? $signed(result_q) : 96'sd0;
    assign m_remainder = m_valid ? $signed(result_r) : 64'sd0;

`ifndef SYNTHESIS
    always @(posedge clk) begin
        if (rst_n && s_valid && s_ready && s_denominator==0)
            $fatal(1,"g2_divider: zero denominator");
    end
`endif

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; limb<=0; iteration<=0;
            raw_n<=0; raw_d<=0; quotient<=0; divisor<=0;
            remainder<=0; difference<=0; trial<=0;
            result_q<=0; result_r<=0;
            negative_n<=0; negative_d<=0; negative_q<=0;
            carry_n<=0; carry_d<=0; borrow<=0;
            carry_q<=0; carry_r<=0; adjust<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    raw_n<=s_numerator; raw_d<=s_denominator;
                    negative_n<=s_numerator[95];
                    negative_d<=s_denominator[63];
                    negative_q<=s_numerator[95]^s_denominator[63];
                    carry_n<=s_numerator[95];
                    carry_d<=s_denominator[63];
                    remainder<=0; limb<=0; iteration<=0;
                    state<=NORMALIZE;
                end
                NORMALIZE: begin
                    quotient[limb*16 +:16]<=norm_n[15:0];
                    carry_n<=norm_n[16];
                    if (limb<4) begin
                        divisor[limb[1:0]*16 +:16]<=norm_d[15:0];
                        carry_d<=norm_d[16];
                    end
                    if (limb==5) state<=SHIFT;
                    else limb<=limb+3'd1;
                end
                SHIFT: begin
                    trial<={remainder,quotient[95]};
                    limb<=0; borrow<=0;
                    state<=SUBTRACT;
                end
                SUBTRACT: begin
                    difference[limb[1:0]*16 +:16]<=sub_limb[15:0];
                    borrow<=sub_limb[16];
                    if (limb==3) state<=DECIDE;
                    else limb<=limb+3'd1;
                end
                DECIDE: begin
                    quotient<={quotient[94:0],accept_subtract};
                    if (accept_subtract) remainder<=difference;
                    else remainder<=trial[63:0];
                    if (iteration==95) begin
                        adjust<=negative_q &&
                            (accept_subtract ? (difference!=0) : (trial[63:0]!=0));
                        carry_q<=negative_q &&
                            (accept_subtract ? (difference==0) : (trial[63:0]==0));
                        carry_r<=negative_d || (negative_q &&
                            (accept_subtract ? (difference!=0) : (trial[63:0]!=0)));
                        limb<=0; state<=CORRECT;
                    end else begin
                        iteration<=iteration+7'd1; state<=SHIFT;
                    end
                end
                CORRECT: begin
                    result_q[limb*16 +:16]<=corrected_q[15:0];
                    carry_q<=corrected_q[16];
                    if (limb<4) begin
                        result_r[limb[1:0]*16 +:16]<=corrected_r[15:0];
                        carry_r<=corrected_r[16];
                    end
                    if (limb==5) state<=HOLD;
                    else limb<=limb+3'd1;
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
