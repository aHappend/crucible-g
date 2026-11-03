module g5_ray_triangle (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [991:0] s_command,
    output wire m_valid,
    input wire m_ready,
    output wire [511:0] m_record,
    output wire m_terminal
);
    localparam IDLE=0, DIFFERENCE_SEND=1, DIFFERENCE_WAIT=2,
        CROSS_FIRST_SEND=3, CROSS_FIRST_WAIT=4,
        CROSS_SECOND_SEND=5, CROSS_SECOND_WAIT=6,
        CROSS_SUB_SEND=7, CROSS_SUB_WAIT=8,
        DOT_MUL_SEND=9, DOT_MUL_WAIT=10, DOT_ADD_SEND=11, DOT_ADD_WAIT=12,
        DET_CHECK=13, NEGATE_SEND=14, NEGATE_WAIT=15, BARY_CHECK=16,
        BARY_ADD_SEND=17, BARY_ADD_WAIT=18, BARY_CMP_SEND=19, BARY_CMP_WAIT=20,
        LOWER_MUL_SEND=21, LOWER_MUL_WAIT=22, LOWER_CMP_SEND=23, LOWER_CMP_WAIT=24,
        UPPER_MUL_SEND=25, UPPER_MUL_WAIT=26, UPPER_CMP_SEND=27, UPPER_CMP_WAIT=28,
        DIV_SEND=29, DIV_WAIT=30, PAD=31, HOLD=32,
        INTERVAL_SEND=33, INTERVAL_WAIT=34;
    reg [5:0] state;
    reg [14:0] age;
    reg [991:0] command;
    reg [511:0] record;
    reg [3:0] difference_index;
    reg [2:0] cross_index;
    reg [1:0] dot_index, dot_axis, negate_index, divide_index;
    reg signed [127:0] vectors [0:17];
    reg signed [127:0] numerators [0:3];
    reg signed [191:0] first_product, second_product, accumulator;
    reg [191:0] alu_a, alu_b;
    reg alu_subtract;
    reg signed [127:0] mul_a, mul_b;
    wire alu_ready, alu_valid, alu_less, alu_equal, alu_carry;
    wire [191:0] alu_result;
    wire mul_ready, mul_valid;
    wire signed [191:0] mul_product;
    wire div_ready, div_valid, div_error;
    wire [191:0] div_quotient, div_remainder;
    wire signed [63:0] incoming_min=s_command[608 +:64];
    wire signed [63:0] incoming_max=s_command[672 +:64];
    wire malformed=s_command[32 +:32]!=0 || s_command[64 +:32]!=32'h910 ||
        (|s_command[127:97]) || (|s_command[991:736]) ||
        incoming_min[63] || incoming_max[63];
    wire signed [63:0] t_min=command[608 +:64], t_max=command[672 +:64];
    wire [1:0] difference_axis=difference_index<3 ? difference_index[1:0] :
        difference_index<6 ? difference_index-4'd3 : difference_index-4'd6;
    wire [4:0] difference_word=difference_index<3 ? 5'd13+difference_axis :
        difference_index<6 ? 5'd16+difference_axis : 5'd4+difference_axis;
    wire [31:0] difference_left=command[difference_word*32 +:32];
    wire [31:0] difference_right=command[(5'd10+difference_axis)*32 +:32];
    wire [1:0] cross_axis=cross_index<3 ? cross_index[1:0] : cross_index-3'd3;
    wire [1:0] next_axis=cross_axis==0 ? 2'd1 : cross_axis==1 ? 2'd2 : 2'd0;
    wire [1:0] last_axis=cross_axis==0 ? 2'd2 : cross_axis==1 ? 2'd0 : 2'd1;
    wire [4:0] cross_a_base=cross_index<3 ? 5'd6 : 5'd9;
    wire [4:0] cross_b_base=cross_index<3 ? 5'd3 : 5'd0;
    wire [4:0] cross_destination=cross_index<3 ?
        5'd12+cross_axis : 5'd15+cross_axis;
    wire [4:0] dot_a_base=dot_index==0 ? 5'd0 : dot_index==1 ? 5'd9 :
        dot_index==2 ? 5'd6 : 5'd3;
    wire [4:0] dot_b_base=dot_index<2 ? 5'd12 : 5'd15;
    wire [191:0] positive_det={{64{numerators[0][127]}},numerators[0]};
    wire [191:0] scaled_t={{48{numerators[3][127]}},numerators[3],16'd0};
    wire [127:0] divide_numerator=divide_index==0 ? numerators[3] :
        divide_index==1 ? numerators[1] : numerators[2];
    wire [191:0] scaled_dividend={48'd0,divide_numerator,16'd0};
    wire alu_send=state==DIFFERENCE_SEND || state==CROSS_SUB_SEND ||
        state==DOT_ADD_SEND || state==NEGATE_SEND || state==BARY_ADD_SEND ||
        state==BARY_CMP_SEND || state==LOWER_CMP_SEND || state==UPPER_CMP_SEND ||
        state==INTERVAL_SEND;
    wire alu_wait=state==DIFFERENCE_WAIT || state==CROSS_SUB_WAIT ||
        state==DOT_ADD_WAIT || state==NEGATE_WAIT || state==BARY_ADD_WAIT ||
        state==BARY_CMP_WAIT || state==LOWER_CMP_WAIT || state==UPPER_CMP_WAIT ||
        state==INTERVAL_WAIT;
    wire mul_send=state==CROSS_FIRST_SEND || state==CROSS_SECOND_SEND ||
        state==DOT_MUL_SEND || state==LOWER_MUL_SEND || state==UPPER_MUL_SEND;
    wire mul_wait=state==CROSS_FIRST_WAIT || state==CROSS_SECOND_WAIT ||
        state==DOT_MUL_WAIT || state==LOWER_MUL_WAIT || state==UPPER_MUL_WAIT;
    integer i;

    g5_limb_alu arithmetic (
        .clk(clk),.rst_n(rst_n),.s_valid(alu_send),.s_ready(alu_ready),
        .s_a(alu_a),.s_b(alu_b),.s_subtract(alu_subtract),
        .m_valid(alu_valid),.m_ready(alu_wait),.m_result(alu_result),
        .m_less(alu_less),.m_equal(alu_equal),.m_carry(alu_carry)
    );
    g5_mul multiplier (
        .clk(clk),.rst_n(rst_n),.s_valid(mul_send),.s_ready(mul_ready),
        .s_a(mul_a),.s_b(mul_b),.m_valid(mul_valid),.m_ready(mul_wait),
        .m_product(mul_product)
    );
    g5_divider divider (
        .clk(clk),.rst_n(rst_n),.s_valid(state==DIV_SEND),.s_ready(div_ready),
        .s_numerator(scaled_dividend),.s_denominator(positive_det),
        .m_valid(div_valid),.m_ready(state==DIV_WAIT),
        .m_quotient(div_quotient),.m_remainder(div_remainder),.m_error(div_error)
    );
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_record=m_valid ? record : 512'd0;
    assign m_terminal=m_valid;

    always @* begin
        alu_a=0; alu_b=0; alu_subtract=0; mul_a=0; mul_b=0;
        case (state)
            INTERVAL_SEND: begin
                alu_a={{128{t_min[63]}},t_min};
                alu_b={{128{t_max[63]}},t_max}; alu_subtract=1;
            end
            DIFFERENCE_SEND: begin
                alu_a={{160{difference_left[31]}},difference_left};
                alu_b={{160{difference_right[31]}},difference_right};
                alu_subtract=1;
            end
            CROSS_FIRST_SEND: begin
                mul_a=vectors[cross_a_base+next_axis];
                mul_b=vectors[cross_b_base+last_axis];
            end
            CROSS_SECOND_SEND: begin
                mul_a=vectors[cross_a_base+last_axis];
                mul_b=vectors[cross_b_base+next_axis];
            end
            CROSS_SUB_SEND: begin
                alu_a=first_product; alu_b=second_product; alu_subtract=1;
            end
            DOT_MUL_SEND: begin
                mul_a=vectors[dot_a_base+dot_axis];
                mul_b=vectors[dot_b_base+dot_axis];
            end
            DOT_ADD_SEND: begin alu_a=accumulator; alu_b=first_product; end
            NEGATE_SEND: begin
                alu_b={{64{numerators[negate_index][127]}},numerators[negate_index]};
                alu_subtract=1;
            end
            BARY_ADD_SEND: begin
                alu_a={{64{numerators[1][127]}},numerators[1]};
                alu_b={{64{numerators[2][127]}},numerators[2]};
            end
            BARY_CMP_SEND: begin
                alu_a=accumulator; alu_b=positive_det; alu_subtract=1;
            end
            LOWER_MUL_SEND: begin
                mul_a={{64{t_min[63]}},t_min}; mul_b=numerators[0];
            end
            LOWER_CMP_SEND: begin
                alu_a=first_product; alu_b=scaled_t; alu_subtract=1;
            end
            UPPER_MUL_SEND: begin
                mul_a={{64{t_max[63]}},t_max}; mul_b=numerators[0];
            end
            UPPER_CMP_SEND: begin
                alu_a=scaled_t; alu_b=first_product; alu_subtract=1;
            end
            default: begin end
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; age<=0; command<=0; record<=0;
            difference_index<=0; cross_index<=0; dot_index<=0; dot_axis<=0;
            negate_index<=0; divide_index<=0;
            first_product<=0; second_product<=0; accumulator<=0;
            for (i=0; i<18; i=i+1) vectors[i]<=0;
            for (i=0; i<4; i=i+1) numerators[i]<=0;
        end else begin
            if (state!=IDLE && state!=HOLD) age<=age+15'd1;
            case (state)
                IDLE: if (s_valid) begin
                    command<=s_command; age<=0; record<=0;
                    record[0 +:32]<=32'h50000010;
                    record[32 +:32]<=s_command[0 +:32];
                    record[64 +:32]<=malformed ? 32'd1 : 32'd0;
                    for (i=0; i<3; i=i+1)
                        vectors[6+i]<={{96{s_command[(7+i)*32+31]}},
                            s_command[(7+i)*32 +:32]};
                    difference_index<=0;
                    if (malformed) state<=PAD;
                    else state<=INTERVAL_SEND;
                end
                INTERVAL_SEND: if (alu_ready) state<=INTERVAL_WAIT;
                INTERVAL_WAIT: if (alu_valid) begin
                    if (alu_less || alu_equal) state<=DIFFERENCE_SEND;
                    else begin record[64 +:32]<=32'd1; state<=PAD; end
                end
                DIFFERENCE_SEND: if (alu_ready) state<=DIFFERENCE_WAIT;
                DIFFERENCE_WAIT: if (alu_valid) begin
                    if (difference_index<6) vectors[difference_index]<=alu_result[127:0];
                    else vectors[difference_index+4'd3]<=alu_result[127:0];
                    if (difference_index==8) begin cross_index<=0; state<=CROSS_FIRST_SEND; end
                    else begin difference_index<=difference_index+4'd1; state<=DIFFERENCE_SEND; end
                end
                CROSS_FIRST_SEND: if (mul_ready) state<=CROSS_FIRST_WAIT;
                CROSS_FIRST_WAIT: if (mul_valid) begin
                    first_product<=mul_product; state<=CROSS_SECOND_SEND;
                end
                CROSS_SECOND_SEND: if (mul_ready) state<=CROSS_SECOND_WAIT;
                CROSS_SECOND_WAIT: if (mul_valid) begin
                    second_product<=mul_product; state<=CROSS_SUB_SEND;
                end
                CROSS_SUB_SEND: if (alu_ready) state<=CROSS_SUB_WAIT;
                CROSS_SUB_WAIT: if (alu_valid) begin
                    vectors[cross_destination]<=alu_result[127:0];
                    if (cross_index==5) begin
                        dot_index<=0; dot_axis<=0; accumulator<=0; state<=DOT_MUL_SEND;
                    end else begin cross_index<=cross_index+3'd1; state<=CROSS_FIRST_SEND; end
                end
                DOT_MUL_SEND: if (mul_ready) state<=DOT_MUL_WAIT;
                DOT_MUL_WAIT: if (mul_valid) begin
                    first_product<=mul_product; state<=DOT_ADD_SEND;
                end
                DOT_ADD_SEND: if (alu_ready) state<=DOT_ADD_WAIT;
                DOT_ADD_WAIT: if (alu_valid) begin
                    accumulator<=alu_result;
                    if (dot_axis==2) begin
                        numerators[dot_index]<=alu_result[127:0];
                        if (dot_index==3) state<=DET_CHECK;
                        else begin
                            dot_index<=dot_index+2'd1; dot_axis<=0;
                            accumulator<=0; state<=DOT_MUL_SEND;
                        end
                    end else begin dot_axis<=dot_axis+2'd1; state<=DOT_MUL_SEND; end
                end
                DET_CHECK: begin
                    if (numerators[0]==0 || (command[96] && numerators[0][127]))
                        state<=PAD;
                    else if (numerators[0][127]) begin negate_index<=0; state<=NEGATE_SEND; end
                    else state<=BARY_CHECK;
                end
                NEGATE_SEND: if (alu_ready) state<=NEGATE_WAIT;
                NEGATE_WAIT: if (alu_valid) begin
                    numerators[negate_index]<=alu_result[127:0];
                    if (negate_index==3) state<=BARY_CHECK;
                    else begin negate_index<=negate_index+2'd1; state<=NEGATE_SEND; end
                end
                BARY_CHECK: begin
                    if (numerators[1][127] || numerators[2][127] || numerators[3][127])
                        state<=PAD;
                    else state<=BARY_ADD_SEND;
                end
                BARY_ADD_SEND: if (alu_ready) state<=BARY_ADD_WAIT;
                BARY_ADD_WAIT: if (alu_valid) begin accumulator<=alu_result; state<=BARY_CMP_SEND; end
                BARY_CMP_SEND: if (alu_ready) state<=BARY_CMP_WAIT;
                BARY_CMP_WAIT: if (alu_valid) begin
                    if (alu_less || alu_equal) state<=LOWER_MUL_SEND;
                    else state<=PAD;
                end
                LOWER_MUL_SEND: if (mul_ready) state<=LOWER_MUL_WAIT;
                LOWER_MUL_WAIT: if (mul_valid) begin first_product<=mul_product; state<=LOWER_CMP_SEND; end
                LOWER_CMP_SEND: if (alu_ready) state<=LOWER_CMP_WAIT;
                LOWER_CMP_WAIT: if (alu_valid) begin
                    if (alu_less || alu_equal) state<=UPPER_MUL_SEND;
                    else state<=PAD;
                end
                UPPER_MUL_SEND: if (mul_ready) state<=UPPER_MUL_WAIT;
                UPPER_MUL_WAIT: if (mul_valid) begin first_product<=mul_product; state<=UPPER_CMP_SEND; end
                UPPER_CMP_SEND: if (alu_ready) state<=UPPER_CMP_WAIT;
                UPPER_CMP_WAIT: if (alu_valid) begin
                    if (alu_less || alu_equal) begin divide_index<=0; state<=DIV_SEND; end
                    else state<=PAD;
                end
                DIV_SEND: if (div_ready) state<=DIV_WAIT;
                DIV_WAIT: if (div_valid) begin
                    if (div_error ||
                        (divide_index==0 && ((|div_quotient[191:63]))) ||
                        (divide_index!=0 && ((|div_quotient[191:17]) ||
                            (div_quotient[16] && (|div_quotient[15:0]))))) begin
                        record[64 +:32]<=32'd4; record[511:96]<=0; state<=PAD;
`ifndef SYNTHESIS
                        $fatal(1,"g5_ray_triangle: accepted ratio overflow or zero divisor");
`endif
                    end else begin
                        if (divide_index==0) record[128 +:64]<=div_quotient[63:0];
                        else if (divide_index==1) record[192 +:32]<=div_quotient[31:0];
                        else record[224 +:32]<=div_quotient[31:0];
                        if (divide_index==2) begin record[96 +:32]<=32'd1; state<=PAD; end
                        else begin divide_index<=divide_index+2'd1; state<=DIV_SEND; end
                    end
                end
                PAD: begin end
                HOLD: if (m_ready) state<=IDLE;
                default: begin
                    record[64 +:32]<=32'd4; record[511:96]<=0; state<=PAD;
`ifndef SYNTHESIS
                    $fatal(1,"g5_ray_triangle: invalid arithmetic state");
`endif
                end
            endcase
            if (state!=IDLE && state!=HOLD && age==15'd16383) begin
                state<=HOLD;
                if (state!=PAD) begin
                    record[64 +:32]<=32'd4; record[511:96]<=0;
`ifndef SYNTHESIS
                    $fatal(1,"g5_ray_triangle: fixed publication slot overrun");
`endif
                end
            end
        end
    end
endmodule
