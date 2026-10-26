module g1_raster (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [101:0] s_vertices,
    input wire [8:0] s_width,
    input wire [8:0] s_height,
    output wire m_valid,
    input wire m_ready,
    output wire [7:0] m_x,
    output wire [7:0] m_y,
    output wire [16:0] m_lambda0,
    output wire [16:0] m_lambda1,
    output wire [16:0] m_lambda2,
    output wire done_valid,
    input wire done_ready,
    output wire done_nondegenerate
);
    localparam IDLE=4'd0, AREA_SEND=4'd1, AREA_WAIT=4'd2,
               BOUNDS=4'd3, PIXEL_SEND=4'd4, PIXEL_WAIT=4'd5,
               DIV0_SEND=4'd6, DIV0_WAIT=4'd7, DIV1_PREP=4'd8,
               DIV1_SEND=4'd9, DIV1_WAIT=4'd10, PIXEL_HOLD=4'd11,
               NEXT_PIXEL=4'd12, DONE=4'd13;
    reg [3:0] state;
    reg [33:0] v0,v1,v2;
    reg [8:0] width,height,x,y,x_min,x_max,y_max;
    reg signed [36:0] area,edge1;
    reg signed [95:0] numerator;
    reg [16:0] lambda0,lambda1,lambda2;
    reg nondegenerate;
    wire edge_ready0,edge_ready1,edge_ready2;
    wire edge_valid0,edge_valid1,edge_valid2;
    wire signed [36:0] e0,e1,e2;
    wire all_ready = edge_ready0 && edge_ready1 && edge_ready2;
    wire all_valid = edge_valid0 && edge_valid1 && edge_valid2;
    wire pixel_issue = state==PIXEL_SEND && all_ready;
    wire pixel_consume = state==PIXEL_WAIT && all_valid;
    wire [33:0] sample_point =
        {1'b0,y[7:0],8'h80,1'b0,x[7:0],8'h80};
    wire div_ready,div_valid;
    wire signed [95:0] quotient;
    wire [17:0] residual_weight =
        18'd65536-{1'b0,lambda0}-{1'b0,quotient[16:0]};

    function automatic [16:0] min3;
        input [16:0] a,b,c;
        begin
            if (a<=b && a<=c) min3=a;
            else if (b<=c) min3=b;
            else min3=c;
        end
    endfunction
    function automatic [16:0] max3;
        input [16:0] a,b,c;
        begin
            if (a>=b && a>=c) max3=a;
            else if (b>=c) max3=b;
            else max3=c;
        end
    endfunction
    function automatic top_left;
        input [33:0] a,b;
        reg signed [17:0] dx,dy;
        begin
            dx=$signed({1'b0,b[16:0]})-$signed({1'b0,a[16:0]});
            dy=$signed({1'b0,b[33:17]})-$signed({1'b0,a[33:17]});
            top_left=(dy<0) || (dy==0 && dx>0);
        end
    endfunction
    wire [16:0] min_x_raw = min3(v0[16:0],v1[16:0],v2[16:0]);
    wire [16:0] max_x_raw = max3(v0[16:0],v1[16:0],v2[16:0]);
    wire [16:0] min_y_raw = min3(v0[33:17],v1[33:17],v2[33:17]);
    wire [16:0] max_y_raw = max3(v0[33:17],v1[33:17],v2[33:17]);
    wire inside0 = e0>0 || (e0==0 && top_left(v1,v2));
    wire inside1 = e1>0 || (e1==0 && top_left(v2,v0));
    wire inside2 = e2>0 || (e2==0 && top_left(v0,v1));

    g1_edge edge0 (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==AREA_SEND || pixel_issue),.s_ready(edge_ready0),
        .s_a(state==AREA_SEND ? v0 : v1),
        .s_b(state==AREA_SEND ? v1 : v2),
        .s_p(state==AREA_SEND ? v2 : sample_point),
        .m_valid(edge_valid0),
        .m_ready(state==AREA_WAIT || pixel_consume),.m_edge(e0)
    );
    g1_edge edge_1 (
        .clk(clk),.rst_n(rst_n),
        .s_valid(pixel_issue),.s_ready(edge_ready1),
        .s_a(v2),.s_b(v0),.s_p(sample_point),
        .m_valid(edge_valid1),.m_ready(pixel_consume),.m_edge(e1)
    );
    g1_edge edge_2 (
        .clk(clk),.rst_n(rst_n),
        .s_valid(pixel_issue),.s_ready(edge_ready2),
        .s_a(v0),.s_b(v1),.s_p(sample_point),
        .m_valid(edge_valid2),.m_ready(pixel_consume),.m_edge(e2)
    );
    g1_divider divider (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==DIV0_SEND || state==DIV1_SEND),.s_ready(div_ready),
        .s_numerator(numerator),
        .s_denominator({{27{area[36]}},area}),
        .m_valid(div_valid),.m_ready(state==DIV0_WAIT || state==DIV1_WAIT),
        .m_quotient(quotient),.m_remainder()
    );

    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==PIXEL_HOLD;
    assign m_x = x[7:0];
    assign m_y = y[7:0];
    assign m_lambda0 = lambda0;
    assign m_lambda1 = lambda1;
    assign m_lambda2 = lambda2;
    assign done_valid = rst_n && state==DONE;
    assign done_nondegenerate = nondegenerate;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; v0<=0; v1<=0; v2<=0;
            width<=0; height<=0; x<=0; y<=0;
            x_min<=0; x_max<=0; y_max<=0;
            area<=0; edge1<=0; numerator<=0;
            lambda0<=0; lambda1<=0; lambda2<=0; nondegenerate<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    v0<=s_vertices[33:0];
                    v1<=s_vertices[67:34];
                    v2<=s_vertices[101:68];
                    width<=s_width; height<=s_height;
                    nondegenerate<=0;
                    state<=AREA_SEND;
                end
                AREA_SEND: if (edge_ready0) state<=AREA_WAIT;
                AREA_WAIT: if (edge_valid0) begin
                    if (e0==0) state<=DONE;
                    else begin
                        nondegenerate<=1;
                        if (e0<0) begin
                            v1<=v2; v2<=v1; area<= -e0;
                        end else area<=e0;
                        state<=BOUNDS;
                    end
                end
                BOUNDS: begin
                    x<=min_x_raw[16:8];
                    y<=min_y_raw[16:8];
                    x_min<=min_x_raw[16:8];
                    if (max_x_raw[16:8]>=width) x_max<=width-9'd1;
                    else x_max<=max_x_raw[16:8];
                    if (max_y_raw[16:8]>=height) y_max<=height-9'd1;
                    else y_max<=max_y_raw[16:8];
                    if (min_x_raw[16:8]>=width || min_y_raw[16:8]>=height)
                        state<=DONE;
                    else state<=PIXEL_SEND;
                end
                PIXEL_SEND: if (all_ready) state<=PIXEL_WAIT;
                PIXEL_WAIT: if (all_valid) begin
                    if (inside0 && inside1 && inside2) begin
                        numerator<={{43{e0[36]}},e0,16'b0};
                        edge1<=e1;
                        state<=DIV0_SEND;
                    end else state<=NEXT_PIXEL;
                end
                DIV0_SEND: if (div_ready) state<=DIV0_WAIT;
                DIV0_WAIT: if (div_valid) begin
                    lambda0<=quotient[16:0];
                    state<=DIV1_PREP;
                end
                DIV1_PREP: begin
                    numerator<={{43{edge1[36]}},edge1,16'b0};
                    state<=DIV1_SEND;
                end
                DIV1_SEND: if (div_ready) state<=DIV1_WAIT;
                DIV1_WAIT: if (div_valid) begin
                    lambda1<=quotient[16:0];
                    lambda2<=residual_weight[16:0];
                    state<=PIXEL_HOLD;
                end
                PIXEL_HOLD: if (m_ready) state<=NEXT_PIXEL;
                NEXT_PIXEL: begin
                    if (x==x_max) begin
                        x<=x_min;
                        if (y==y_max) state<=DONE;
                        else begin
                            y<=y+9'd1;
                            state<=PIXEL_SEND;
                        end
                    end else begin
                        x<=x+9'd1;
                        state<=PIXEL_SEND;
                    end
                end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
