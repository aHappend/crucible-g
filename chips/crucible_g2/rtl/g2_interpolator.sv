module g2_interpolator (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [16:0] s_lambda0, s_lambda1, s_lambda2,
    input wire [122:0] s_q,
    input wire [575:0] s_attributes,
    output wire m_valid,
    input wire m_ready,
    output wire [191:0] m_attributes
);
    localparam IDLE=0, WEIGHT=1, PAIR_WEIGHT=2, DENOMINATOR=3,
               PRODUCT=4, PAIR_PRODUCT=5, NUMERATOR=6,
               ISSUE=7, WAIT_RESULT=8, HOLD=9;
    reg [3:0] state;
    reg [16:0] lambda [0:2];
    reg [40:0] q [0:2];
    reg [575:0] attributes;
    reg [57:0] weight [0:2];
    reg [58:0] weight_pair;
    reg [63:0] denominator;
    reg signed [95:0] product [0:17];
    reg signed [95:0] pair_sum [0:5];
    reg signed [95:0] numerator [0:5];
    reg [191:0] result;
    wire [5:0] div_ready, div_valid;
    wire signed [95:0] quotient [0:5];
    genvar a,v;
    generate
        for (a=0;a<6;a=a+1) begin: attribute_lane
            g2_divider divider (
                .clk(clk),.rst_n(rst_n),
                .s_valid(state==ISSUE),.s_ready(div_ready[a]),
                .s_numerator(numerator[a]),
                .s_denominator($signed(denominator)),
                .m_valid(div_valid[a]),.m_ready(state==WAIT_RESULT),
                .m_quotient(quotient[a]),.m_remainder()
            );
            for (v=0;v<3;v=v+1) begin: vertex_lane
                wire signed [31:0] attribute_value =
                    attributes[(v*6+a)*32 +:32];
                wire signed [58:0] positive_weight = {1'b0,weight[v]};
                always @(posedge clk or negedge rst_n) begin
                    if (!rst_n) product[v*6+a]<=0;
                    else if (state==PRODUCT)
                        product[v*6+a]<=positive_weight*attribute_value;
                end
            end
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    pair_sum[a]<=0; numerator[a]<=0;
                    result[a*32 +:32]<=0;
                end else begin
                    if (state==PAIR_PRODUCT)
                        pair_sum[a]<=product[a]+product[6+a];
                    if (state==NUMERATOR)
                        numerator[a]<=pair_sum[a]+product[12+a];
                    if (state==WAIT_RESULT && (&div_valid))
                        result[a*32 +:32]<=quotient[a][31:0];
                end
            end
        end
        for (v=0;v<3;v=v+1) begin: weights
            wire [16:0] input_lambda = v==0 ? s_lambda0 :
                v==1 ? s_lambda1 : s_lambda2;
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin lambda[v]<=0; q[v]<=0; weight[v]<=0; end
                else begin
                    if (state==IDLE && s_valid) begin
                        lambda[v]<=input_lambda; q[v]<=s_q[v*41 +:41];
                    end
                    if (state==WEIGHT) weight[v]<=lambda[v]*q[v];
                end
            end
        end
    endgenerate
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_attributes = m_valid ? result : 192'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; attributes<=0; weight_pair<=0; denominator<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin attributes<=s_attributes; state<=WEIGHT; end
                WEIGHT: state<=PAIR_WEIGHT;
                PAIR_WEIGHT: begin
                    weight_pair<={1'b0,weight[0]}+{1'b0,weight[1]};
                    state<=DENOMINATOR;
                end
                DENOMINATOR: begin
                    denominator<={5'd0,weight_pair}+{6'd0,weight[2]};
                    state<=PRODUCT;
                end
                PRODUCT: state<=PAIR_PRODUCT;
                PAIR_PRODUCT: state<=NUMERATOR;
                NUMERATOR: state<=ISSUE;
                ISSUE: if (&div_ready) state<=WAIT_RESULT;
                WAIT_RESULT: if (&div_valid) state<=HOLD;
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
