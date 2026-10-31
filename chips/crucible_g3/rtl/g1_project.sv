module g1_project (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [127:0] s_vertex,
    input wire [8:0] s_width,
    input wire [8:0] s_height,
    output wire m_valid,
    input wire m_ready,
    output wire [33:0] m_vertex
);
    localparam IDLE=3'd0, SUM=3'd1, MULTIPLY=3'd2, DIV_SEND=3'd3,
               DIV_WAIT=3'd4, HOLD=3'd5;
    reg [2:0] state;
    reg axis;
    reg [127:0] vertex;
    reg [8:0] width,height;
    reg signed [32:0] coordinate,denominator;
    reg signed [42:0] product;
    reg [16:0] screen_x,screen_y;
    wire [8:0] dimension = axis ? height : width;
    wire [16:0] limit = {dimension,8'b0};
    wire signed [31:0] vx = vertex[31:0];
    wire signed [31:0] vy = vertex[63:32];
    wire signed [31:0] vw = vertex[127:96];
    wire div_ready,div_valid;
    wire signed [95:0] quotient;
    wire [16:0] clamped =
        quotient<96'sd0 ? 17'd0 :
        quotient>$signed({79'd0,limit}) ? limit : quotient[16:0];

    g1_divider divider (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==DIV_SEND),.s_ready(div_ready),
        .s_numerator({{45{product[42]}},product,8'b0}),
        .s_denominator({{31{denominator[32]}},denominator}),
        .m_valid(div_valid),.m_ready(state==DIV_WAIT),
        .m_quotient(quotient),.m_remainder()
    );
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_vertex = {screen_y,screen_x};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; axis<=0; vertex<=0; width<=0; height<=0;
            coordinate<=0; denominator<=0; product<=0; screen_x<=0; screen_y<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    vertex<=s_vertex; width<=s_width; height<=s_height;
                    axis<=0; state<=SUM;
                end
                SUM: begin
                    if (axis)
                        coordinate<=$signed({vw[31],vw})-$signed({vy[31],vy});
                    else
                        coordinate<=$signed({vx[31],vx})+$signed({vw[31],vw});
                    denominator<=$signed({vw,1'b0});
                    state<=MULTIPLY;
                end
                MULTIPLY: begin
                    product<=coordinate*$signed({1'b0,dimension});
                    state<=DIV_SEND;
                end
                DIV_SEND: if (div_ready) state<=DIV_WAIT;
                DIV_WAIT: if (div_valid) begin
                    if (axis) begin
                        screen_y<=clamped;
                        state<=HOLD;
                    end else begin
                        screen_x<=clamped;
                        axis<=1;
                        state<=SUM;
                    end
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
