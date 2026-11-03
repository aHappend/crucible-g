module g4_conic (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [15:0] s_pixel,
    input wire [47:0] s_mean,
    input wire [71:0] s_conic,
    input wire [16:0] s_opacity,
    output wire m_valid,
    input wire m_ready,
    output wire [16:0] m_alpha
);
    localparam IDLE=0, DELTAS=1, QUADRATICS=2, PARTIALS=3, TERMS=4,
               SUM_AB=5, SUM_ALL=6, ADDRESS=7, ROM_READ=8,
               OPACITY=9, ROUND=10, PUBLISH=11, HOLD=12;
    reg [3:0] state;
    reg [15:0] pixel;
    reg [47:0] mean;
    reg [71:0] coefficients;
    reg [16:0] opacity, alpha;
    reg signed [24:0] dx, dy;
    reg signed [49:0] xx, xy, yy;
    reg [48:0] low_a, low_b, low_c;
    reg signed [48:0] high_a, high_b, high_c;
    reg signed [75:0] term_a, term_b, term_c, sum_ab, nq;
    reg [12:0] address;
    reg cutoff;
    reg [33:0] opacity_product;
    wire [16:0] weight;
    wire signed [23:0] a=coefficients[23:0], b=coefficients[47:24],
        c=coefficients[71:48];
    wire [23:0] abs_a=a[23] ? (~a+24'd1) : a;
    wire [23:0] abs_b=b[23] ? (~b+24'd1) : b;
    wire [23:0] abs_c=c[23] ? (~c+24'd1) : c;
    wire signed [24:0] xx_high=xx[49:25], xy_high=xy[49:25],
        yy_high=yy[49:25];
    wire signed [75:0] signed_low_a=a[23] ? -$signed({27'd0,low_a}) :
        $signed({27'd0,low_a});
    wire signed [75:0] signed_low_b=b[23] ? -$signed({27'd0,low_b}) :
        $signed({27'd0,low_b});
    wire signed [75:0] signed_low_c=c[23] ? -$signed({27'd0,low_c}) :
        $signed({27'd0,low_c});
    wire signed [75:0] extended_high_a={{27{high_a[48]}},high_a};
    wire signed [75:0] extended_high_b={{27{high_b[48]}},high_b};
    wire signed [75:0] extended_high_c={{27{high_c[48]}},high_c};
    wire [75:0] rounded_nq=nq+76'd4294967296;
    wire [34:0] rounded_alpha={1'b0,opacity_product}+35'd32768;
    wire signed [24:0] pixel_x=$signed({5'd0,pixel[7:0],12'd2048});
    wire signed [24:0] pixel_y=$signed({5'd0,pixel[15:8],12'd2048});
    wire signed [24:0] mean_x=$signed({mean[23],mean[23:0]});
    wire signed [24:0] mean_y=$signed({mean[47],mean[47:24]});
    g4_exp_rom exp_rom (.clk(clk),.address(address),.value(weight));
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_alpha=m_valid ? alpha : 17'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; pixel<=0; mean<=0; coefficients<=0; opacity<=0;
            alpha<=0; dx<=0; dy<=0; xx<=0; xy<=0; yy<=0;
            low_a<=0; low_b<=0; low_c<=0;
            high_a<=0; high_b<=0; high_c<=0;
            term_a<=0; term_b<=0; term_c<=0; sum_ab<=0; nq<=0;
            address<=0; cutoff<=0; opacity_product<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    pixel<=s_pixel; mean<=s_mean; coefficients<=s_conic;
                    opacity<=s_opacity; state<=DELTAS;
                end
                DELTAS: begin dx<=pixel_x-mean_x; dy<=pixel_y-mean_y; state<=QUADRATICS; end
                QUADRATICS: begin xx<=dx*dx; xy<=dx*dy; yy<=dy*dy; state<=PARTIALS; end
                PARTIALS: begin
                    low_a<=abs_a*xx[24:0]; high_a<=a*xx_high;
                    low_b<=abs_b*xy[24:0]; high_b<=b*xy_high;
                    low_c<=abs_c*yy[24:0]; high_c<=c*yy_high;
                    state<=TERMS;
                end
                TERMS: begin
                    term_a<=signed_low_a+(extended_high_a<<<25);
                    term_b<=signed_low_b+(extended_high_b<<<25);
                    term_c<=signed_low_c+(extended_high_c<<<25); state<=SUM_AB;
                end
                SUM_AB: begin sum_ab<=term_a+(term_b<<<1); state<=SUM_ALL; end
                SUM_ALL: begin nq<=sum_ab+term_c; state<=ADDRESS; end
                ADDRESS: begin
                    cutoff<=nq>=76'sd35184372088832;
                    if (nq>=76'sd35184372088832) address<=0;
                    else if (rounded_nq[75:33]>76'd4096) address<=13'd4096;
                    else address<=rounded_nq[45:33];
                    state<=ROM_READ;
                end
                ROM_READ: state<=OPACITY;
                OPACITY: begin
                    opacity_product<=cutoff ? 34'd0 : opacity*weight; state<=ROUND;
                end
                ROUND: begin
                    if (rounded_alpha[34:16]>19'd65536) alpha<=17'd65536;
                    else alpha<=rounded_alpha[32:16];
                    state<=PUBLISH;
                end
                PUBLISH: state<=HOLD;
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
