module g1_edge (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [33:0] s_a,
    input wire [33:0] s_b,
    input wire [33:0] s_p,
    output wire m_valid,
    input wire m_ready,
    output wire signed [36:0] m_edge
);
    localparam IDLE=2'd0, PRODUCT=2'd1, DIFFERENCE=2'd2, HOLD=2'd3;
    reg [1:0] state;
    reg signed [17:0] dx,dy,px,py;
    reg signed [35:0] product0,product1;
    reg signed [36:0] result;
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_edge = m_valid ? result : 37'sd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; dx<=0; dy<=0; px<=0; py<=0;
            product0<=0; product1<=0; result<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    dx<=$signed({1'b0,s_b[16:0]})-$signed({1'b0,s_a[16:0]});
                    dy<=$signed({1'b0,s_b[33:17]})-$signed({1'b0,s_a[33:17]});
                    px<=$signed({1'b0,s_p[16:0]})-$signed({1'b0,s_a[16:0]});
                    py<=$signed({1'b0,s_p[33:17]})-$signed({1'b0,s_a[33:17]});
                    state<=PRODUCT;
                end
                PRODUCT: begin
                    product0<=dx*py;
                    product1<=dy*px;
                    state<=DIFFERENCE;
                end
                DIFFERENCE: begin
                    result<=$signed({product0[35],product0})-
                            $signed({product1[35],product1});
                    state<=HOLD;
                end
                HOLD: if (m_ready) state<=IDLE;
            endcase
        end
    end
endmodule
