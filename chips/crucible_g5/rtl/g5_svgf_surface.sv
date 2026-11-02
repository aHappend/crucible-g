module g5_svgf_surface (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [95:0] s_normal_a, s_normal_b,
    input wire [31:0] s_depth_a, s_depth_b,
    output wire m_valid,
    input wire m_ready,
    output wire signed [47:0] m_dot_raw,
    output wire [16:0] m_dot,
    output wire m_depth_ok, m_depth_step
);
    localparam IDLE=0, PRODUCT=1, SIGN_SEND=2, SIGN_WAIT=3,
        SUM0_SEND=4, SUM0_WAIT=5, SUM1_SEND=6, SUM1_WAIT=7,
        DEPTH_SEND=8, DEPTH_WAIT=9, HOLD=10;
    reg [3:0] state;
    reg [15:0] a [0:2], b [0:2];
    reg [31:0] product [0:2];
    reg [2:0] negative;
    reg [47:0] signed_product [0:2];
    reg signed [47:0] sum;
    reg [31:0] depth_a, depth_b;
    reg depth_ok, depth_step;
    wire [2:0] sign_ready, sign_valid;
    wire [47:0] sign_result [0:2];
    wire sum_ready, sum_valid, sum_less, sum_equal, sum_carry;
    wire [47:0] sum_result;
    reg [47:0] sum_a, sum_b;
    integer i;
    genvar axis;
    generate for (axis=0; axis<3; axis=axis+1) begin: sign_axes
        wire unused_less, unused_equal, unused_carry;
        g5_limb_alu #(.WIDTH(48)) product_sign (
            .clk(clk),.rst_n(rst_n),.s_valid(state==SIGN_SEND),
            .s_ready(sign_ready[axis]),
            .s_a(negative[axis] ? 48'd0 : {16'd0,product[axis]}),
            .s_b(negative[axis] ? {16'd0,product[axis]} : 48'd0),
            .s_subtract(negative[axis]),.m_valid(sign_valid[axis]),
            .m_ready(state==SIGN_WAIT),.m_result(sign_result[axis]),
            .m_less(unused_less),.m_equal(unused_equal),.m_carry(unused_carry)
        );
    end endgenerate
    g5_limb_alu #(.WIDTH(48)) reduction (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==SUM0_SEND || state==SUM1_SEND || state==DEPTH_SEND),
        .s_ready(sum_ready),.s_a(sum_a),.s_b(sum_b),
        .s_subtract(state==DEPTH_SEND),.m_valid(sum_valid),
        .m_ready(state==SUM0_WAIT || state==SUM1_WAIT || state==DEPTH_WAIT),
        .m_result(sum_result),.m_less(sum_less),.m_equal(sum_equal),.m_carry(sum_carry)
    );
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_dot_raw=m_valid ? sum : 48'sd0;
    assign m_dot=!m_valid || sum[47] ? 17'd0 :
        (|sum[46:30]) ? 17'd65536 : {1'b0,sum[29:14]};
    assign m_depth_ok=m_valid && depth_ok;
    assign m_depth_step=m_valid && depth_step;
    always @* begin
        sum_a=0; sum_b=0;
        case (state)
            SUM0_SEND: begin sum_a=signed_product[0]; sum_b=signed_product[1]; end
            SUM1_SEND: begin sum_a=sum; sum_b=signed_product[2]; end
            DEPTH_SEND: begin sum_a={16'd0,depth_a}; sum_b={16'd0,depth_b}; end
            default: begin end
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; negative<=0; sum<=0; depth_a<=0; depth_b<=0;
            depth_ok<=0; depth_step<=0;
            for (i=0; i<3; i=i+1) begin
                a[i]<=0; b[i]<=0; product[i]<=0; signed_product[i]<=0;
            end
        end else case (state)
            IDLE: if (s_valid) begin
                for (i=0; i<3; i=i+1) begin
                    a[i]<=s_normal_a[i*32+31] ?
                        ~s_normal_a[i*32 +:16]+16'd1 : s_normal_a[i*32 +:16];
                    b[i]<=s_normal_b[i*32+31] ?
                        ~s_normal_b[i*32 +:16]+16'd1 : s_normal_b[i*32 +:16];
                    negative[i]<=s_normal_a[i*32+31]^s_normal_b[i*32+31];
                end
                depth_a<=s_depth_a; depth_b<=s_depth_b; state<=PRODUCT;
            end
            PRODUCT: begin
                for (i=0; i<3; i=i+1) product[i]<=a[i]*b[i];
                state<=SIGN_SEND;
            end
            SIGN_SEND: if (&sign_ready) state<=SIGN_WAIT;
            SIGN_WAIT: if (&sign_valid) begin
                for (i=0; i<3; i=i+1) signed_product[i]<=sign_result[i];
                state<=SUM0_SEND;
            end
            SUM0_SEND: if (sum_ready) state<=SUM0_WAIT;
            SUM0_WAIT: if (sum_valid) begin sum<=sum_result; state<=SUM1_SEND; end
            SUM1_SEND: if (sum_ready) state<=SUM1_WAIT;
            SUM1_WAIT: if (sum_valid) begin sum<=sum_result; state<=DEPTH_SEND; end
            DEPTH_SEND: if (sum_ready) state<=DEPTH_WAIT;
            DEPTH_WAIT: if (sum_valid) begin
                depth_ok<=(!sum_result[47] && sum_result[47:16]==0 &&
                    sum_result[15:0]<=16'd4096) ||
                    (sum_result[47:16]==32'hffffffff &&
                    sum_result[15:0]>=16'hf000);
                depth_step<=sum_result==48'd4096 || sum_result==48'hfffffffff000;
                state<=HOLD;
            end
            HOLD: if (m_ready) state<=IDLE;
            default: begin
                state<=IDLE;
`ifndef SYNTHESIS
                $fatal(1,"g5_svgf_surface: invalid control state");
`endif
            end
        endcase
    end
endmodule
