module g2_engine #(
    parameter integer MAX_WIDTH=256,
    parameter integer MAX_HEIGHT=256,
    parameter integer TILE_LOG2=3
) (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [991:0] s_header,
    input wire [575:0] s_attributes,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_data,
    output wire m_last
);
    localparam IDLE=0, VALIDATE=1, CLEAR_SEND=2, CLEAR_WAIT=3,
               SETUP_SEND=4, SETUP_WAIT=5, FAN_READ1=6, FAN_CAPTURE1=7,
               FAN_READ2=8, FAN_CAPTURE2=9, AREA_SEND=10, AREA_WAIT=11,
               BOUNDS=12, TILE_START=13, TILE_SEND=14, TILE_WAIT=15,
               RASTER_SEND=16, RASTER_WAIT=17, DEPTH_PRODUCT=18,
               DEPTH_PAIR=19, DEPTH_SUM=20, FRAG_SEND=21, FRAG_WAIT=22,
               INTERPOLATE_SEND=23, INTERPOLATE_WAIT=24, PIXEL_HOLD=25,
               NEXT_TILE=26, NEXT_FAN=27, COMPLETE=28, COMPLETE_HOLD=29;
    localparam integer SAFE_LOG2 = TILE_LOG2>=0 && TILE_LOG2<=4 ? TILE_LOG2 : 0;
    localparam [8:0] TILE_SIZE = 9'd1 << SAFE_LOG2;
    localparam [8:0] TILE_MASK = 9'h1ff << SAFE_LOG2;
    reg [4:0] state;
    reg [991:0] header;
    reg [575:0] attributes;
    reg [31:0] tag,status;
    reg [8:0] width,height;
    reg depth24,disable_early;
    reg configured,configured_depth24;
    reg [8:0] configured_width,configured_height;
    (* ramstyle = "M20K", nomem2reg *) reg [290:0] projected [0:383];
    reg [290:0] polygon_q,v0,v1,v2;
    reg [8:0] projected_count,polygon_count,fan_i,fan_index;
    reg [8:0] tile_x,tile_y,tile_start_x,tile_last_x,tile_last_y;
    reg [7:0] sample_x,sample_y;
    reg [16:0] lambda0,lambda1,lambda2;
    reg [40:0] depth_product0,depth_product1,depth_product2;
    reg [41:0] depth_pair;
    reg [23:0] sample_depth;
    reg [31:0] pixels_emitted,fan_total,tiles_tested,tiles_rejected;
    reg [31:0] fragments_tested,fragments_passed,fragments_failed;
    reg [415:0] record;
    reg [3:0] record_index;

    wire setup_ready,setup_valid,setup_done;
    wire [290:0] setup_vertex;
    wire [8:0] setup_count;
    wire area_ready,area_valid;
    wire signed [36:0] area;
    wire raster_ready,raster_valid,raster_done;
    wire [7:0] raster_x,raster_y;
    wire [16:0] raster_lambda0,raster_lambda1,raster_lambda2;
    wire clear_ready,clear_done,tile_ready,tile_result_valid,tile_reject;
    wire frag_ready,frag_result_valid,frag_pass;
    wire interpolate_ready,interpolate_valid;
    wire [191:0] interpolated_attributes;
    wire [31:0] mode = header[64 +:32];
    wire clear_mode = mode==4 || mode==5;
    wire draw_mode = mode==2 || mode==3 || mode==6 || mode==7 ||
        mode==258 || mode==259 || mode==262 || mode==263;
    wire dimensions_valid = header[32 +:16]!=0 && header[32 +:16]<=MAX_WIDTH &&
        header[48 +:16]!=0 && header[48 +:16]<=MAX_HEIGHT;
    wire configuration_matches = configured && configured_width==width &&
        configured_height==height && configured_depth24==depth24;
    wire [8:0] fan_next = fan_i+9'd1;
    wire [42:0] depth_sum = {1'b0,depth_pair}+{2'd0,depth_product2};

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
    wire [16:0] min_x_raw = min3(v0[16:0],v1[16:0],v2[16:0]);
    wire [16:0] min_y_raw = min3(v0[33:17],v1[33:17],v2[33:17]);
    wire [16:0] max_x_raw = max3(v0[16:0],v1[16:0],v2[16:0]);
    wire [16:0] max_y_raw = max3(v0[33:17],v1[33:17],v2[33:17]);
    wire [8:0] end_x = max_x_raw[16:8]>=width ? width-9'd1 : max_x_raw[16:8];
    wire [8:0] end_y = max_y_raw[16:8]>=height ? height-9'd1 : max_y_raw[16:8];
    wire [23:0] z0=v0[98:75], z1=v1[98:75], z2=v2[98:75];
    wire [23:0] zmin = z0<=z1 && z0<=z2 ? z0 : z1<=z2 ? z1 : z2;

    g2_setup setup (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==SETUP_SEND),.s_ready(setup_ready),
        .s_header(header),.s_attributes(attributes),
        .m_valid(setup_valid),.m_ready(state==SETUP_WAIT),.m_vertex(setup_vertex),
        .done_valid(setup_done),.done_ready(state==SETUP_WAIT),.done_count(setup_count)
    );
    g1_edge area_edge (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==AREA_SEND),.s_ready(area_ready),
        .s_a(v0[33:0]),.s_b(v1[33:0]),.s_p(v2[33:0]),
        .m_valid(area_valid),.m_ready(state==AREA_WAIT),.m_edge(area)
    );
    g2_raster #(.TILE_LOG2(TILE_LOG2)) raster (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==RASTER_SEND),.s_ready(raster_ready),
        .s_vertices({v2[33:0],v1[33:0],v0[33:0]}),
        .s_width(width),.s_height(height),.s_tile_x(tile_x[7:0]),.s_tile_y(tile_y[7:0]),
        .m_valid(raster_valid),.m_ready(state==RASTER_WAIT),
        .m_x(raster_x),.m_y(raster_y),
        .m_lambda0(raster_lambda0),.m_lambda1(raster_lambda1),.m_lambda2(raster_lambda2),
        .done_valid(raster_done),.done_ready(state==RASTER_WAIT)
    );
    g2_zbuffer #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
        .TILE_LOG2(TILE_LOG2)) zbuffer (
        .clk(clk),.rst_n(rst_n),
        .clear_valid(state==CLEAR_SEND),.clear_ready(clear_ready),
        .clear_width(width),.clear_height(height),.clear_depth24(depth24),
        .clear_done_valid(clear_done),.clear_done_ready(state==CLEAR_WAIT),
        .tile_valid(state==TILE_SEND),.tile_ready(tile_ready),
        .tile_x(tile_x[7:0]),.tile_y(tile_y[7:0]),.tile_zmin(zmin),
        .tile_result_valid(tile_result_valid),.tile_result_ready(state==TILE_WAIT),
        .tile_reject(tile_reject),
        .frag_valid(state==FRAG_SEND),.frag_ready(frag_ready),
        .frag_x(sample_x),.frag_y(sample_y),.frag_depth(sample_depth),
        .frag_result_valid(frag_result_valid),.frag_result_ready(state==FRAG_WAIT),
        .frag_pass(frag_pass)
    );
    g2_interpolator interpolator (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==INTERPOLATE_SEND),.s_ready(interpolate_ready),
        .s_lambda0(lambda0),.s_lambda1(lambda1),.s_lambda2(lambda2),
        .s_q({v2[74:34],v1[74:34],v0[74:34]}),
        .s_attributes({v2[290:99],v1[290:99],v0[290:99]}),
        .m_valid(interpolate_valid),.m_ready(state==INTERPOLATE_WAIT),
        .m_attributes(interpolated_attributes)
    );

    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && (state==PIXEL_HOLD || state==COMPLETE_HOLD);
    assign m_data = m_valid ? record[record_index*32 +:32] : 32'd0;
    assign m_last = m_valid && state==COMPLETE_HOLD && record_index==12;

    always @(posedge clk) begin
        if (rst_n) begin
            if (state==SETUP_WAIT && setup_valid)
                projected[projected_count]<=setup_vertex;
            if (state==FAN_READ1) polygon_q<=projected[fan_i];
            if (state==FAN_READ2) polygon_q<=projected[fan_next];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; header<=0; attributes<=0; tag<=0; status<=0;
            width<=0; height<=0; depth24<=0; disable_early<=0;
            configured<=0; configured_depth24<=0; configured_width<=0; configured_height<=0;
            v0<=0; v1<=0; v2<=0; projected_count<=0; polygon_count<=0;
            fan_i<=0; fan_index<=0; tile_x<=0; tile_y<=0;
            tile_start_x<=0; tile_last_x<=0; tile_last_y<=0;
            sample_x<=0; sample_y<=0; lambda0<=0; lambda1<=0; lambda2<=0;
            depth_product0<=0; depth_product1<=0; depth_product2<=0; depth_pair<=0;
            sample_depth<=0; pixels_emitted<=0; fan_total<=0;
            tiles_tested<=0; tiles_rejected<=0; fragments_tested<=0;
            fragments_passed<=0; fragments_failed<=0; record<=0; record_index<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    header<=s_header; attributes<=s_attributes;
                    tag<=s_header[31:0]; width<=s_header[32 +:9]; height<=s_header[48 +:9];
                    depth24<=s_header[64]; disable_early<=s_header[72];
                    pixels_emitted<=0; fan_total<=0; tiles_tested<=0; tiles_rejected<=0;
                    fragments_tested<=0; fragments_passed<=0; fragments_failed<=0;
                    projected_count<=0; polygon_count<=0; fan_i<=1; fan_index<=0;
                    status<=0; record_index<=0; state<=VALIDATE;
                end
                VALIDATE: begin
                    if (!dimensions_valid || (!clear_mode && !draw_mode)) begin
                        status<=1; state<=COMPLETE;
                    end else if (clear_mode) state<=CLEAR_SEND;
                    else if (!configuration_matches) begin status<=4; state<=COMPLETE; end
                    else state<=SETUP_SEND;
                end
                CLEAR_SEND: if (clear_ready) state<=CLEAR_WAIT;
                CLEAR_WAIT: if (clear_done) begin
                    configured<=1; configured_width<=width; configured_height<=height;
                    configured_depth24<=depth24; status<=0; state<=COMPLETE;
                end
                SETUP_SEND: if (setup_ready) state<=SETUP_WAIT;
                SETUP_WAIT: begin
                    if (setup_valid) begin
                        if (projected_count==0) v0<=setup_vertex;
                        projected_count<=projected_count+9'd1;
                    end
                    if (setup_done) begin
                        polygon_count<=setup_count;
                        if (setup_count<3) begin status<=2; state<=COMPLETE; end
                        else state<=FAN_READ1;
                    end
                end
                FAN_READ1: state<=FAN_CAPTURE1;
                FAN_CAPTURE1: begin v1<=polygon_q; state<=FAN_READ2; end
                FAN_READ2: state<=FAN_CAPTURE2;
                FAN_CAPTURE2: begin v2<=polygon_q; state<=AREA_SEND; end
                AREA_SEND: if (area_ready) state<=AREA_WAIT;
                AREA_WAIT: if (area_valid) begin
                    if (area==0) state<=NEXT_FAN;
                    else begin
                        fan_total<=fan_total+32'd1;
                        if (area<0) begin v1<=v2; v2<=v1; end
                        state<=BOUNDS;
                    end
                end
                BOUNDS: begin
                    tile_x<=min_x_raw[16:8] & TILE_MASK;
                    tile_start_x<=min_x_raw[16:8] & TILE_MASK;
                    tile_y<=min_y_raw[16:8] & TILE_MASK;
                    tile_last_x<=end_x & TILE_MASK; tile_last_y<=end_y & TILE_MASK;
                    if (min_x_raw[16:8]>=width || min_y_raw[16:8]>=height)
                        state<=NEXT_FAN;
                    else state<=TILE_START;
                end
                TILE_START: begin
                    tiles_tested<=tiles_tested+32'd1;
                    if (disable_early) state<=RASTER_SEND;
                    else state<=TILE_SEND;
                end
                TILE_SEND: if (tile_ready) state<=TILE_WAIT;
                TILE_WAIT: if (tile_result_valid) begin
                    if (tile_reject) begin
                        tiles_rejected<=tiles_rejected+32'd1; state<=NEXT_TILE;
                    end else state<=RASTER_SEND;
                end
                RASTER_SEND: if (raster_ready) state<=RASTER_WAIT;
                RASTER_WAIT: begin
                    if (raster_valid) begin
                        sample_x<=raster_x; sample_y<=raster_y;
                        lambda0<=raster_lambda0; lambda1<=raster_lambda1; lambda2<=raster_lambda2;
                        state<=DEPTH_PRODUCT;
                    end else if (raster_done) state<=NEXT_TILE;
                end
                DEPTH_PRODUCT: begin
                    depth_product0<=lambda0*z0; depth_product1<=lambda1*z1;
                    depth_product2<=lambda2*z2; state<=DEPTH_PAIR;
                end
                DEPTH_PAIR: begin
                    depth_pair<={1'b0,depth_product0}+{1'b0,depth_product1};
                    state<=DEPTH_SUM;
                end
                DEPTH_SUM: begin sample_depth<=depth_sum[39:16]; state<=FRAG_SEND; end
                FRAG_SEND: if (frag_ready) state<=FRAG_WAIT;
                FRAG_WAIT: if (frag_result_valid) begin
                    fragments_tested<=fragments_tested+32'd1;
                    if (frag_pass) begin
                        fragments_passed<=fragments_passed+32'd1;
                        pixels_emitted<=pixels_emitted+32'd1;
                        state<=INTERPOLATE_SEND;
                    end else begin
                        fragments_failed<=fragments_failed+32'd1; state<=RASTER_WAIT;
                    end
                end
                INTERPOLATE_SEND: if (interpolate_ready) state<=INTERPOLATE_WAIT;
                INTERPOLATE_WAIT: if (interpolate_valid) begin
                    record<={interpolated_attributes,8'd0,sample_depth,
                        15'd0,lambda2,15'd0,lambda1,15'd0,lambda0,
                        7'd0,fan_index,sample_y,sample_x,tag,32'd0};
                    record_index<=0; state<=PIXEL_HOLD;
                end
                PIXEL_HOLD: if (m_ready) begin
                    if (record_index==12) begin record_index<=0; state<=RASTER_WAIT; end
                    else record_index<=record_index+4'd1;
                end
                NEXT_TILE: begin
                    if (tile_x==tile_last_x) begin
                        tile_x<=tile_start_x;
                        if (tile_y==tile_last_y) state<=NEXT_FAN;
                        else begin tile_y<=tile_y+TILE_SIZE; state<=TILE_START; end
                    end else begin tile_x<=tile_x+TILE_SIZE; state<=TILE_START; end
                end
                NEXT_FAN: begin
                    if (fan_i==polygon_count-9'd2) begin
                        if (fan_total==0) status<=3;
                        else status<=0;
                        state<=COMPLETE;
                    end else begin
                        fan_i<=fan_i+9'd1; fan_index<=fan_index+9'd1; state<=FAN_READ1;
                    end
                end
                COMPLETE: begin
                    record<={96'd0,fragments_failed,fragments_passed,fragments_tested,
                        tiles_rejected,tiles_tested,fan_total,pixels_emitted,status,tag,32'd1};
                    record_index<=0; state<=COMPLETE_HOLD;
                end
                COMPLETE_HOLD: if (m_ready) begin
                    if (record_index==12) begin record_index<=0; state<=IDLE; end
                    else record_index<=record_index+4'd1;
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
