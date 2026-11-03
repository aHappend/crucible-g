module g1_dot4 (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [127:0] s_a,
    input wire [127:0] s_b,
    output wire m_valid,
    input wire m_ready,
    output wire signed [31:0] m_result
);
    localparam IDLE=3'd0, PRODUCT=3'd1, PAIR=3'd2, SUM=3'd3,
               SATURATE=3'd4, HOLD=3'd5;
    reg [2:0] state;
    reg signed [31:0] a0,a1,a2,a3,b0,b1,b2,b3;
    reg signed [63:0] p0,p1,p2,p3;
    reg signed [64:0] pair0,pair1;
    reg signed [65:0] total;
    reg signed [31:0] result;
    wire signed [65:0] scaled = total >>> 16;

    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_result = m_valid ? result : 32'sd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;
            a0<=0; a1<=0; a2<=0; a3<=0;
            b0<=0; b1<=0; b2<=0; b3<=0;
            p0<=0; p1<=0; p2<=0; p3<=0;
            pair0<=0; pair1<=0; total<=0; result<=0;
        end else begin
            // Common arithmetic enables avoid incompatible Quartus DSP chains.
            p0<=a0*b0; p1<=a1*b1; p2<=a2*b2; p3<=a3*b3;
            pair0<=$signed({p0[63],p0})+$signed({p1[63],p1});
            pair1<=$signed({p2[63],p2})+$signed({p3[63],p3});
            total<=$signed({pair0[64],pair0})+
                   $signed({pair1[64],pair1});
            case (state)
                IDLE: if (s_valid) begin
                    a0<=s_a[31:0]; a1<=s_a[63:32];
                    a2<=s_a[95:64]; a3<=s_a[127:96];
                    b0<=s_b[31:0]; b1<=s_b[63:32];
                    b2<=s_b[95:64]; b3<=s_b[127:96];
                    state<=PRODUCT;
                end
                PRODUCT: state<=PAIR;
                PAIR: state<=SUM;
                SUM: state<=SATURATE;
                SATURATE: begin
                    if (scaled>66'sd2147483647) result<=32'sh7fffffff;
                    else if (scaled< -66'sd2147483648) result<=32'sh80000000;
                    else result<=scaled[31:0];
                    state<=HOLD;
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
