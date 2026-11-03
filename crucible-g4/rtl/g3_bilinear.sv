module g3_bilinear (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [127:0] s_texels,
    input wire [15:0] s_fx, s_fy,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_rgba
);
    localparam IDLE=0, H_PRODUCT=1, H_SUM=2, V_PRODUCT=3,
               V_SUM=4, ROUND=5, HOLD=6;
    reg [2:0] state;
    reg [127:0] texels;
    reg [16:0] wx0,wx1,wy0,wy1;
    reg [31:0] result;
    genvar c;
    generate for (c=0;c<4;c=c+1) begin: channel
        reg [24:0] hp00,hp10,hp01,hp11;
        reg [25:0] hs0,hs1;
        reg [42:0] vp0,vp1;
        reg [43:0] total;
        wire [8:0] rounded = {1'b0,total[39:32]}+{8'd0,total[31]};
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                hp00<=0; hp10<=0; hp01<=0; hp11<=0;
                hs0<=0; hs1<=0; vp0<=0; vp1<=0; total<=0;
                result[c*8 +:8]<=0;
            end else begin
                hp00<=texels[c*8 +:8]*wx0;
                hp10<=texels[32+c*8 +:8]*wx1;
                hp01<=texels[64+c*8 +:8]*wx0;
                hp11<=texels[96+c*8 +:8]*wx1;
                hs0<={1'b0,hp00}+{1'b0,hp10};
                hs1<={1'b0,hp01}+{1'b0,hp11};
                vp0<=hs0*wy0; vp1<=hs1*wy1;
                total<={1'b0,vp0}+{1'b0,vp1};
                if (state==ROUND) result[c*8 +:8]<=rounded[7:0];
            end
        end
    end endgenerate
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_rgba=m_valid ? result : 32'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; texels<=0; wx0<=0; wx1<=0; wy0<=0; wy1<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    texels<=s_texels;
                    wx0<=17'd65536-{1'b0,s_fx}; wx1<={1'b0,s_fx};
                    wy0<=17'd65536-{1'b0,s_fy}; wy1<={1'b0,s_fy};
                    state<=H_PRODUCT;
                end
                H_PRODUCT: state<=H_SUM;
                H_SUM: state<=V_PRODUCT;
                V_PRODUCT: state<=V_SUM;
                V_SUM: state<=ROUND;
                ROUND: state<=HOLD;
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
