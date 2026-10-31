module g3_texture_cache (
    input wire clk, rst_n,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire [31:0] cfg_base, cfg_stride,
    input wire [8:0] cfg_width, cfg_height,
    input wire s_valid,
    output wire s_ready,
    input wire signed [31:0] s_u, s_v,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_rgba,
    output wire m_error,
    output wire tex_req_valid,
    input wire tex_req_ready,
    output wire [31:0] tex_req_addr,
    input wire tex_rsp_valid,
    output wire tex_rsp_ready,
    input wire [31:0] tex_rsp_data,
    input wire tex_rsp_error
);
    localparam IDLE=0, LOOKUP=1, READ=2, CAPTURE=3, REFILL_COORD=4,
               ROW_PRODUCT=5, ROW_ADDRESS=6, ADDRESS=7, REQUEST=8,
               RESPONSE=9, FILTER_SEND=10, FILTER_WAIT=11, HOLD=12;
    reg [3:0] state;
    reg configured;
    reg [31:0] base,stride,request_address,row_address;
    reg [8:0] width,height;
    reg [3:0] line_valid;
    reg [47:0] tags;
    (* ramstyle = "M20K", nomem2reg *) reg [31:0] texels_mem [0:63];
    reg [31:0] memory_q;
    reg [7:0] x0,x1,y0,y1,refill_x,refill_y;
    reg [15:0] fx,fy;
    reg [1:0] sample_index;
    reg [3:0] refill_index;
    reg [39:0] row_product;
    reg [127:0] gathered;
    reg [31:0] result;
    reg result_error;
    wire [8:0] last_x=width-9'd1;
    wire [8:0] last_y=height-9'd1;
    wire [23:0] max_u={last_x[7:0],16'd0};
    wire [23:0] max_v={last_y[7:0],16'd0};
    wire [23:0] clamped_u=s_u<0 ? 24'd0 :
        s_u>$signed({8'd0,max_u}) ? max_u : s_u[23:0];
    wire [23:0] clamped_v=s_v<0 ? 24'd0 :
        s_v>$signed({8'd0,max_v}) ? max_v : s_v[23:0];
    wire [7:0] sample_x=sample_index[0] ? x1 : x0;
    wire [7:0] sample_y=sample_index[1] ? y1 : y0;
    wire [1:0] line_index={sample_y[2],sample_x[2]};
    wire [11:0] block_tag={sample_y[7:2],sample_x[7:2]};
    wire cache_hit=line_valid[line_index] && tags[line_index*12 +:12]==block_tag;
    wire [7:0] refill_raw_x={sample_x[7:2],refill_index[1:0]};
    wire [7:0] refill_raw_y={sample_y[7:2],refill_index[3:2]};
    wire [5:0] read_address={line_index,sample_y[1:0],sample_x[1:0]};
    wire filter_ready,filter_valid;
    wire [31:0] filter_rgba;

    g3_bilinear filter (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==FILTER_SEND),.s_ready(filter_ready),
        .s_texels(gathered),.s_fx(fx),.s_fy(fy),
        .m_valid(filter_valid),.m_ready(state==FILTER_WAIT),.m_rgba(filter_rgba)
    );
    assign cfg_ready=rst_n && state==IDLE;
    assign s_ready=rst_n && state==IDLE && configured && !cfg_valid;
    assign m_valid=rst_n && state==HOLD;
    assign m_rgba=m_valid && !result_error ? result : 32'd0;
    assign m_error=m_valid && result_error;
    assign tex_req_valid=rst_n && state==REQUEST;
    assign tex_req_addr=tex_req_valid ? request_address : 32'd0;
    assign tex_rsp_ready=rst_n && state==RESPONSE;

    always @(posedge clk) begin
        if (rst_n) begin
            if (state==READ) memory_q<=texels_mem[read_address];
            if (state==RESPONSE && tex_rsp_valid && !tex_rsp_error)
                texels_mem[{line_index,refill_index}]<=tex_rsp_data;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; configured<=0; base<=0; stride<=0;
            width<=0; height<=0; line_valid<=0; tags<=0;
            request_address<=0; row_address<=0; row_product<=0;
            x0<=0; x1<=0; y0<=0; y1<=0; refill_x<=0; refill_y<=0;
            fx<=0; fy<=0; sample_index<=0; refill_index<=0;
            gathered<=0; result<=0; result_error<=0;
        end else begin
            case (state)
                IDLE: begin
                    if (cfg_valid) begin
                        base<=cfg_base; stride<=cfg_stride;
                        width<=cfg_width; height<=cfg_height;
                        configured<=1; line_valid<=0;
                    end else if (s_valid && configured) begin
                        x0<=clamped_u[23:16]; y0<=clamped_v[23:16];
                        x1<={1'b0,clamped_u[23:16]}+9'd1>=width ?
                            clamped_u[23:16] : clamped_u[23:16]+8'd1;
                        y1<={1'b0,clamped_v[23:16]}+9'd1>=height ?
                            clamped_v[23:16] : clamped_v[23:16]+8'd1;
                        fx<=clamped_u[15:0]; fy<=clamped_v[15:0];
                        sample_index<=0; gathered<=0; result_error<=0;
                        state<=LOOKUP;
                    end
                end
                LOOKUP: begin
                    if (cache_hit) state<=READ;
                    else begin
                        line_valid[line_index]<=0; refill_index<=0;
                        state<=REFILL_COORD;
                    end
                end
                READ: state<=CAPTURE;
                CAPTURE: begin
                    gathered[sample_index*32 +:32]<=memory_q;
                    if (sample_index==3) state<=FILTER_SEND;
                    else begin sample_index<=sample_index+2'd1; state<=LOOKUP; end
                end
                REFILL_COORD: begin
                    refill_x<={1'b0,refill_raw_x}>=width ? width-9'd1 : refill_raw_x;
                    refill_y<={1'b0,refill_raw_y}>=height ? height-9'd1 : refill_raw_y;
                    state<=ROW_PRODUCT;
                end
                ROW_PRODUCT: begin row_product<=refill_y*stride; state<=ROW_ADDRESS; end
                ROW_ADDRESS: begin row_address<=base+row_product[31:0]; state<=ADDRESS; end
                ADDRESS: begin
                    request_address<=row_address+{22'd0,refill_x,2'd0};
                    state<=REQUEST;
                end
                REQUEST: if (tex_req_ready) state<=RESPONSE;
                RESPONSE: if (tex_rsp_valid) begin
                    if (tex_rsp_error) begin
                        line_valid<=0; result_error<=1; result<=0; state<=HOLD;
                    end else if (refill_index==15) begin
                        tags[line_index*12 +:12]<=block_tag;
                        line_valid[line_index]<=1; state<=READ;
                    end else begin
                        refill_index<=refill_index+4'd1; state<=REFILL_COORD;
                    end
                end
                FILTER_SEND: if (filter_ready) state<=FILTER_WAIT;
                FILTER_WAIT: if (filter_valid) begin result<=filter_rgba; state<=HOLD; end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
