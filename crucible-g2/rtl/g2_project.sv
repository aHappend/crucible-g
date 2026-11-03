module g2_project (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [319:0] s_vertex,
    input wire [8:0] s_width, s_height,
    input wire s_depth24,
    output wire m_valid,
    input wire m_ready,
    output wire [290:0] m_vertex
);
    localparam IDLE=0, PREPARE=1, MULTIPLY=2, ISSUE=3, WAIT_RESULT=4,
               HOLD=5, FORM_NUMERATOR=6;
    reg [2:0] state;
    reg [1:0] phase;
    reg [319:0] vertex;
    reg [8:0] width,height;
    reg [23:0] depth_limit,depth;
    reg [40:0] reciprocal;
    reg [16:0] screen_x,screen_y;
    reg signed [32:0] coordinate;
    reg signed [42:0] screen_product;
    reg signed [56:0] depth_product;
    reg signed [95:0] numerator;
    reg signed [63:0] denominator;
    wire signed [31:0] vx=vertex[31:0], vy=vertex[63:32];
    wire signed [31:0] vz=vertex[95:64], vw=vertex[127:96];
    wire [8:0] dimension = phase==1 ? height : width;
    wire [16:0] limit = {dimension,8'd0};
    wire div_ready,div_valid;
    wire signed [95:0] quotient;
    wire [16:0] clamped_screen = quotient<0 ? 17'd0 :
        quotient>$signed({79'd0,limit}) ? limit : quotient[16:0];
    wire [23:0] clamped_depth = quotient<0 ? 24'd0 :
        quotient>$signed({72'd0,depth_limit}) ? depth_limit : quotient[23:0];

    g2_divider divider (
        .clk(clk),.rst_n(rst_n),.s_valid(state==ISSUE),.s_ready(div_ready),
        .s_numerator(numerator),.s_denominator(denominator),
        .m_valid(div_valid),.m_ready(state==WAIT_RESULT),
        .m_quotient(quotient),.m_remainder()
    );
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_vertex = m_valid ?
        {vertex[319:128],depth,reciprocal,screen_y,screen_x} : 291'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; phase<=0; vertex<=0; width<=0; height<=0;
            depth_limit<=0; depth<=0; reciprocal<=0; screen_x<=0; screen_y<=0;
            coordinate<=0; screen_product<=0; depth_product<=0;
            numerator<=0; denominator<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    vertex<=s_vertex; width<=s_width; height<=s_height;
                    depth_limit<=s_depth24 ? 24'hffffff : 24'h00ffff;
                    phase<=0; state<=PREPARE;
                end
                PREPARE: begin
                    if (phase==0)
                        coordinate<=$signed({vx[31],vx})+$signed({vw[31],vw});
                    else coordinate<=$signed({vw[31],vw})-$signed({vy[31],vy});
                    if (phase<2) denominator<=$signed({31'd0,vw,1'b0});
                    else denominator<=$signed({32'd0,vw});
                    state<=MULTIPLY;
                end
                MULTIPLY: begin
                    screen_product<=coordinate*$signed({1'b0,dimension});
                    depth_product<=vz*$signed({1'b0,depth_limit});
                    state<=ISSUE;
                    if (phase==2) numerator<=96'd1099511627776;
                    else state<=FORM_NUMERATOR;
                end
                FORM_NUMERATOR: begin
                    if (phase==3)
                        numerator<={{39{depth_product[56]}},depth_product};
                    else numerator<={{45{screen_product[42]}},screen_product,8'd0};
                    state<=ISSUE;
                end
                ISSUE: if (div_ready) state<=WAIT_RESULT;
                WAIT_RESULT: if (div_valid) begin
                    case (phase)
                        0: screen_x<=clamped_screen;
                        1: screen_y<=clamped_screen;
                        2: reciprocal<=quotient[40:0];
                        3: depth<=clamped_depth;
                    endcase
                    if (phase==3) state<=HOLD;
                    else begin phase<=phase+2'd1; state<=PREPARE; end
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
