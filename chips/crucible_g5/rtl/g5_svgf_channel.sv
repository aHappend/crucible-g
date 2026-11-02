module g5_svgf_channel (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [1:0] s_mode,
    input wire [31:0] s_luma, s_variance, s_mean, s_second,
    input wire s_history,
    input wire [16:0] s_normal_weight,
    input wire s_depth_step,
    input wire [5:0] s_kernel,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_luma, m_variance, m_mean, m_second,
    output wire m_error
);
    localparam TEMPORAL=0, CENTER=1, TAP=2, NORMALIZE=3;
    localparam IDLE=0, ISSUE=1, ALU_WAIT=2, MUL_WAIT=3,
        WIDE_WAIT=4, SQRT_WAIT=5, DIV_WAIT=6, SCAN=7, HOLD=8;
    reg [3:0] state, step;
    reg [1:0] mode;
    reg [31:0] luma, variance, previous_mean, previous_second;
    reg [31:0] mean, second, result_luma, result_variance, new_second;
    reg history, error;
    reg [31:0] center_luma, threshold;
    reg [5:0] bandwidth, scan_bit;
    reg [16:0] normal_weight, edge;
    reg depth_step;
    reg [5:0] kernel;
    reg [4:0] shift_amount;
    reg [31:0] weight, difference;
    reg [63:0] weight_square, contribution_luma, denominator_square;
    reg [127:0] contribution_variance, sum_weight, sum_luma, sum_variance, scratch;
    wire alu_ready, alu_valid, alu_less, alu_equal, alu_carry;
    wire [127:0] alu_result;
    reg alu_send, alu_subtract;
    reg [127:0] alu_a, alu_b;
    wire mul_ready, mul_valid;
    wire signed [63:0] mul_product;
    reg mul_send;
    reg [31:0] mul_a, mul_b;
    wire wide_ready, wide_valid;
    wire signed [95:0] wide_product;
    wire signed [111:0] wide_product_full;
    reg wide_send;
    wire sqrt_ready, sqrt_valid;
    wire [23:0] sqrt_root;
    reg sqrt_send;
    wire div_ready, div_valid, div_error;
    wire [95:0] div_quotient, div_remainder;
    reg div_send;
    reg [95:0] div_denominator;
    wire [31:0] scaled_difference=difference>>bandwidth;
    g5_limb_alu #(.WIDTH(128)) accumulator (
        .clk(clk),.rst_n(rst_n),.s_valid(alu_send),.s_ready(alu_ready),
        .s_a(alu_a),.s_b(alu_b),.s_subtract(alu_subtract),
        .m_valid(alu_valid),.m_ready(state==ALU_WAIT),.m_result(alu_result),
        .m_less(alu_less),.m_equal(alu_equal),.m_carry(alu_carry)
    );
    g5_mul #(.A_WIDTH(32),.B_WIDTH(32),.OUT_WIDTH(64)) product (
        .clk(clk),.rst_n(rst_n),.s_valid(mul_send),.s_ready(mul_ready),
        .s_a($signed(mul_a)),.s_b($signed(mul_b)),
        .m_valid(mul_valid),.m_ready(state==MUL_WAIT),.m_product(mul_product)
    );
    // Variance is an unsigned 32-bit moment, so its signed port needs padding.
    g5_mul #(.A_WIDTH(64),.B_WIDTH(48),.OUT_WIDTH(112)) variance_product (
        .clk(clk),.rst_n(rst_n),.s_valid(wide_send),.s_ready(wide_ready),
        .s_a($signed(weight_square)),.s_b($signed({16'd0,variance})),
        .m_valid(wide_valid),.m_ready(state==WIDE_WAIT),.m_product(wide_product_full)
    );
    assign wide_product=wide_product_full[95:0];
    g5_sqrt #(.WIDTH(48)) square_root (
        .clk(clk),.rst_n(rst_n),.s_valid(sqrt_send),.s_ready(sqrt_ready),
        .s_radicand({variance,16'd0}),.m_valid(sqrt_valid),
        .m_ready(state==SQRT_WAIT),.m_root(sqrt_root)
    );
    g5_divider #(.WIDTH(96)) normalization (
        .clk(clk),.rst_n(rst_n),.s_valid(div_send),.s_ready(div_ready),
        .s_numerator(scratch[95:0]),.s_denominator(div_denominator),
        .m_valid(div_valid),.m_ready(state==DIV_WAIT),
        .m_quotient(div_quotient),.m_remainder(div_remainder),.m_error(div_error)
    );
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_luma=m_valid && !error ? result_luma : 32'd0;
    assign m_variance=m_valid && !error ? result_variance : 32'd0;
    assign m_mean=m_valid && !error ? mean : 32'd0;
    assign m_second=m_valid && !error ? second : 32'd0;
    assign m_error=m_valid && error;
    always @* begin
        alu_send=0; alu_subtract=0; alu_a=0; alu_b=0;
        mul_send=0; mul_a=0; mul_b=0; wide_send=0; sqrt_send=0;
        div_send=0; div_denominator=0;
        if (rst_n && state==ISSUE) case (mode)
            TEMPORAL: case (step)
                0: begin mul_send=1; mul_a=luma; mul_b=luma; end
                1: begin
                    alu_send=1; alu_subtract=1;
                    alu_a={93'd0,previous_mean,3'd0}; alu_b={96'd0,previous_mean};
                end
                2: begin alu_send=1; alu_a=scratch; alu_b={96'd0,luma}; end
                3: begin alu_send=1; alu_a=scratch; alu_b=128'd4; end
                4: begin
                    alu_send=1; alu_subtract=1;
                    alu_a={93'd0,previous_second,3'd0}; alu_b={96'd0,previous_second};
                end
                5: begin alu_send=1; alu_a=scratch; alu_b={96'd0,new_second}; end
                6: begin alu_send=1; alu_a=scratch; alu_b=128'd4; end
                7: begin mul_send=1; mul_a=mean; mul_b=mean; end
                8: begin
                    alu_send=1; alu_subtract=1;
                    alu_a={96'd0,second}; alu_b=scratch;
                end
                default: begin end
            endcase
            CENTER: case (step)
                0: sqrt_send=1;
                1: begin alu_send=1; alu_a=scratch; alu_b=128'd256; end
                default: begin end
            endcase
            TAP: case (step)
                0: begin
                    alu_send=1; alu_subtract=1;
                    alu_a={96'd0,center_luma}; alu_b={96'd0,luma};
                end
                1: begin
                    alu_send=1; alu_subtract=scratch[127];
                    alu_a=scratch[127] ? 128'd0 : scratch;
                    alu_b=scratch[127] ? scratch : 128'd0;
                end
                5: begin mul_send=1; mul_a=weight; mul_b=luma; end
                6: begin mul_send=1; mul_a=weight; mul_b=weight; end
                7: wide_send=1;
                8: begin alu_send=1; alu_a=sum_weight; alu_b={96'd0,weight}; end
                9: begin alu_send=1; alu_a=sum_luma; alu_b={64'd0,contribution_luma}; end
                10: begin alu_send=1; alu_a=sum_variance; alu_b=contribution_variance; end
                default: begin end
            endcase
            NORMALIZE: case (step)
                0: begin mul_send=1; mul_a=sum_weight[31:0]; mul_b=sum_weight[31:0]; end
                1: begin alu_send=1; alu_a=sum_luma; alu_b=sum_weight>>1; end
                2: begin div_send=1; div_denominator=sum_weight[95:0]; end
                3: begin
                    alu_send=1; alu_a=sum_variance;
                    alu_b={64'd0,denominator_square}>>1;
                end
                4: begin div_send=1; div_denominator={32'd0,denominator_square}; end
                default: begin end
            endcase
            default: begin end
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; step<=0; mode<=0; luma<=0; variance<=0;
            previous_mean<=0; previous_second<=0; mean<=0; second<=0;
            result_luma<=0; result_variance<=0; new_second<=0;
            history<=0; error<=0; center_luma<=0; threshold<=0;
            bandwidth<=0; scan_bit<=0; normal_weight<=0; edge<=0;
            depth_step<=0; kernel<=0; shift_amount<=0; weight<=0; difference<=0;
            weight_square<=0; contribution_luma<=0; denominator_square<=0;
            contribution_variance<=0; sum_weight<=0; sum_luma<=0;
            sum_variance<=0; scratch<=0;
        end else case (state)
            IDLE: if (s_valid) begin
                mode<=s_mode; luma<=s_luma; variance<=s_variance;
                previous_mean<=s_mean; previous_second<=s_second;
                history<=s_history; normal_weight<=s_normal_weight;
                depth_step<=s_depth_step; kernel<=s_kernel;
                result_luma<=0; result_variance<=0; error<=0; step<=0;
                if (s_mode==CENTER) begin
                    center_luma<=s_luma; sum_weight<=0; sum_luma<=0; sum_variance<=0;
                end
                state<=ISSUE;
            end
            ISSUE: begin
                if (alu_send && alu_ready) state<=ALU_WAIT;
                else if (mul_send && mul_ready) state<=MUL_WAIT;
                else if (wide_send && wide_ready) state<=WIDE_WAIT;
                else if (sqrt_send && sqrt_ready) state<=SQRT_WAIT;
                else if (div_send && div_ready) begin
                    if ((|scratch[127:96]) || div_denominator==0) begin
                        error<=1; state<=HOLD;
                    end else state<=DIV_WAIT;
                end else if (mode==TAP) case (step)
                    2: begin
                        edge<=normal_weight>>depth_step;
                        shift_amount<=(|scaled_difference[31:4]) ?
                            5'd16 : {1'b0,scaled_difference[3:0]};
                        step<=3;
                    end
                    3: begin edge<=edge>>shift_amount; step<=4; end
                    4: begin
                        weight<=edge[16] ? {10'd0,kernel,16'd0} :
                            edge[15:0]*{10'd0,kernel};
                        step<=5;
                    end
                    default: begin end
                endcase
                else if (mode==CENTER && step==2) begin
                    scan_bit<=31; state<=SCAN;
                end
            end
            ALU_WAIT: if (alu_valid) begin
                scratch<=alu_result; step<=step+4'd1; state<=ISSUE;
                case (mode)
                    TEMPORAL: case (step)
                        3: mean<=alu_result[34:3];
                        6: second<=alu_result[34:3];
                        8: begin
                            result_luma<=mean;
                            result_variance<=alu_less ? 32'd0 : alu_result[31:0];
                            if (!alu_less && (|alu_result[127:32])) error<=1;
                            state<=HOLD;
                        end
                        default: begin end
                    endcase
                    CENTER: if (step==1) threshold<=alu_result[31:0];
                    TAP: case (step)
                        1: difference<=alu_result[31:0];
                        8: sum_weight<=alu_result;
                        9: sum_luma<=alu_result;
                        10: begin sum_variance<=alu_result; state<=HOLD; end
                        default: begin end
                    endcase
                    default: begin end
                endcase
            end
            MUL_WAIT: if (mul_valid) begin
                step<=step+4'd1; state<=ISSUE;
                case (mode)
                    TEMPORAL: if (step==0) begin
                        new_second<=mul_product[47:16];
                        if (!history) begin
                            mean<=luma; second<=mul_product[47:16]; step<=7;
                        end
                    end else scratch<={96'd0,mul_product[47:16]};
                    TAP: if (step==5) contribution_luma<=mul_product;
                        else weight_square<=mul_product;
                    NORMALIZE: begin
                        denominator_square<=mul_product;
                        if (sum_weight==0 || (|sum_weight[127:31])) begin
                            error<=1; state<=HOLD;
                        end
                    end
                    default: begin end
                endcase
            end
            WIDE_WAIT: if (wide_valid) begin
                contribution_variance<={32'd0,wide_product};
                if (|wide_product_full[111:96]) error<=1;
                step<=8; state<=ISSUE;
            end
            SQRT_WAIT: if (sqrt_valid) begin
                scratch<={102'd0,sqrt_root,2'd0}; step<=1; state<=ISSUE;
            end
            SCAN: begin
                if (threshold[scan_bit]) begin
                    bandwidth<=scan_bit+
                        ((|(threshold<<(6'd32-scan_bit))) ? 6'd1 : 6'd0);
                    state<=HOLD;
                end else if (scan_bit==0) begin
                    error<=1; state<=HOLD;
                end else scan_bit<=scan_bit-6'd1;
            end
            DIV_WAIT: if (div_valid) begin
                if (div_error || (|div_quotient[95:32])) begin
                    error<=1; state<=HOLD;
                end else if (step==2) begin
                    result_luma<=div_quotient[31:0];
                    if (|div_quotient[31:24]) begin error<=1; state<=HOLD; end
                    else begin step<=3; state<=ISSUE; end
                end else begin
                    result_variance<=div_quotient[31:0]; state<=HOLD;
                end
            end
            HOLD: if (m_ready) state<=IDLE;
            default: begin
                error<=1; state<=HOLD;
`ifndef SYNTHESIS
                $fatal(1,"g5_svgf_channel: invalid control state");
`endif
            end
        endcase
    end
endmodule
