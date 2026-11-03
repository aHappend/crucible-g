module g5_limb_alu #(
    parameter integer WIDTH=192
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [WIDTH-1:0] s_a, s_b,
    input wire s_subtract,
    output wire m_valid,
    input wire m_ready,
    output wire [WIDTH-1:0] m_result,
    output wire m_less, m_equal, m_carry
);
    localparam LEGAL=WIDTH>=16 && WIDTH<=384 && (WIDTH & 15)==0;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_limb_alu WIDTH");
        assign s_ready=0; assign m_valid=0; assign m_result=0;
        assign m_less=0; assign m_equal=0; assign m_carry=0;
    end else begin: implementation
        localparam LIMBS=WIDTH>>4;
        localparam IDLE=0, STEP=1, FINISH=2, HOLD=3;
        reg [1:0] state;
        reg [4:0] limb;
        reg [WIDTH-1:0] a, b, result;
        reg subtract, carry, less, equal, signed_less;
        wire [15:0] al=a[limb*16 +:16], bl=b[limb*16 +:16];
        wire [16:0] sum={1'b0,al}+
            {1'b0,(subtract ? ~bl : bl)}+{16'd0,carry};
        assign s_ready=rst_n && state==IDLE;
        assign m_valid=rst_n && state==HOLD;
        assign m_result=m_valid ? result : {WIDTH{1'b0}};
        assign m_less=m_valid && signed_less;
        assign m_equal=m_valid && equal;
        assign m_carry=m_valid && carry;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; limb<=0; a<=0; b<=0; result<=0;
                subtract<=0; carry<=0; less<=0; equal<=0; signed_less<=0;
            end else begin
                case (state)
                    IDLE: if (s_valid) begin
                        a<=s_a; b<=s_b; subtract<=s_subtract;
                        carry<=s_subtract; limb<=0;
                        less<=0; equal<=1; state<=STEP;
                    end
                    STEP: begin
                        result[limb*16 +:16]<=sum[15:0]; carry<=sum[16];
                        if (al!=bl) begin less<=al<bl; equal<=0; end
                        if (limb==LIMBS-1) state<=FINISH;
                        else limb<=limb+5'd1;
                    end
                    FINISH: begin
                        signed_less<=a[WIDTH-1]!=b[WIDTH-1] ? a[WIDTH-1] : less;
                        state<=HOLD;
                    end
                    HOLD: if (m_ready) state<=IDLE;
                    default: state<=IDLE;
                endcase
            end
        end
    end endgenerate
endmodule
