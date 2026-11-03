module g5_mul #(
    parameter integer A_WIDTH=128, B_WIDTH=128, OUT_WIDTH=192
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire signed [A_WIDTH-1:0] s_a,
    input wire signed [B_WIDTH-1:0] s_b,
    output wire m_valid,
    input wire m_ready,
    output wire signed [OUT_WIDTH-1:0] m_product
);
    localparam LEGAL=A_WIDTH>=16 && A_WIDTH<=192 &&
        B_WIDTH>=16 && B_WIDTH<=192 &&
        OUT_WIDTH>=A_WIDTH && OUT_WIDTH>=B_WIDTH &&
        OUT_WIDTH<=A_WIDTH+B_WIDTH &&
        (A_WIDTH & 15)==0 && (B_WIDTH & 15)==0 && (OUT_WIDTH & 15)==0;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_mul widths");
        assign s_ready=0; assign m_valid=0; assign m_product=0;
    end else begin: implementation
        localparam AL=A_WIDTH>>4, BL=B_WIDTH>>4, OL=OUT_WIDTH>>4;
        localparam IDLE=0, NORMALIZE=1, PRODUCT=2, LOW_PAIR=3, LOW_SUM=4,
            HIGH_SUM=5, ROW_END=6, NEGATE=7, HOLD=8;
        reg [3:0] state;
        reg [4:0] limb, row, column;
        reg [A_WIDTH-1:0] a;
        reg [B_WIDTH-1:0] b;
        reg [OUT_WIDTH-1:0] result;
        reg sign_a, sign_b, negative, carry_a, carry_b, carry_neg;
        reg [15:0] row_carry;
        reg [31:0] partial;
        reg [16:0] low_pair;
        reg [1:0] low_carry;
        wire [4:0] target=row+column;
        wire [15:0] raw_a=a[limb*16 +:16];
        wire [15:0] raw_b=b[limb*16 +:16];
        wire [16:0] norm_a={1'b0,(sign_a ? ~raw_a : raw_a)}+{16'd0,carry_a};
        wire [16:0] norm_b={1'b0,(sign_b ? ~raw_b : raw_b)}+{16'd0,carry_b};
        wire [16:0] pair_sum={1'b0,partial[15:0]}+
            {1'b0,result[target*16 +:16]};
        wire [16:0] low_sum={1'b0,low_pair[15:0]}+{1'b0,row_carry};
        wire [16:0] high_sum={1'b0,partial[31:16]}+{15'd0,low_carry};
        wire [16:0] negated={1'b0,~result[limb*16 +:16]}+{16'd0,carry_neg};
        assign s_ready=rst_n && state==IDLE;
        assign m_valid=rst_n && state==HOLD;
        assign m_product=m_valid ? $signed(result) : {OUT_WIDTH{1'b0}};
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; limb<=0; row<=0; column<=0; a<=0; b<=0;
                result<=0; sign_a<=0; sign_b<=0; negative<=0;
                carry_a<=0; carry_b<=0; carry_neg<=0; row_carry<=0;
                partial<=0; low_pair<=0; low_carry<=0;
            end else begin
                case (state)
                    IDLE: if (s_valid) begin
                        a<=s_a; b<=s_b; sign_a<=s_a[A_WIDTH-1];
                        sign_b<=s_b[B_WIDTH-1];
                        negative<=s_a[A_WIDTH-1]^s_b[B_WIDTH-1];
                        carry_a<=s_a[A_WIDTH-1]; carry_b<=s_b[B_WIDTH-1];
                        result<=0; limb<=0; row<=0; column<=0;
                        row_carry<=0; state<=NORMALIZE;
                    end
                    NORMALIZE: begin
                        if (limb<AL) begin
                            a[limb*16 +:16]<=norm_a[15:0]; carry_a<=norm_a[16];
                        end
                        if (limb<BL) begin
                            b[limb*16 +:16]<=norm_b[15:0]; carry_b<=norm_b[16];
                        end
                        if (limb==(AL>BL ? AL : BL)-1) state<=PRODUCT;
                        else limb<=limb+5'd1;
                    end
                    PRODUCT: begin
                        partial<=a[row*16 +:16]*b[column*16 +:16];
                        state<=LOW_PAIR;
                    end
                    LOW_PAIR: begin
                        low_pair<=pair_sum; state<=LOW_SUM;
                    end
                    LOW_SUM: begin
                        result[target*16 +:16]<=low_sum[15:0];
                        low_carry<={1'b0,low_pair[16]}+{1'b0,low_sum[16]};
                        state<=HIGH_SUM;
                    end
                    HIGH_SUM: begin
                        row_carry<=high_sum[15:0];
                        if (column==BL-1 || target==OL-1) state<=ROW_END;
                        else begin column<=column+5'd1; state<=PRODUCT; end
                    end
                    ROW_END: begin
                        if (row+BL<OL) result[(row+BL)*16 +:16]<=row_carry;
                        column<=0; row_carry<=0;
                        if (row==AL-1) begin
                            limb<=0; carry_neg<=1;
                            if (negative) state<=NEGATE;
                            else state<=HOLD;
                        end else begin row<=row+5'd1; state<=PRODUCT; end
                    end
                    NEGATE: begin
                        result[limb*16 +:16]<=negated[15:0]; carry_neg<=negated[16];
                        if (limb==OL-1) state<=HOLD;
                        else limb<=limb+5'd1;
                    end
                    HOLD: if (m_ready) state<=IDLE;
                    default: state<=IDLE;
                endcase
            end
        end
    end endgenerate
endmodule
