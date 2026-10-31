module g3_framebuffer_dma #(
    parameter integer MAX_WIDTH=256,
    parameter integer MAX_HEIGHT=256,
    parameter integer TILE_LOG2=3
) (
    input wire clk, rst_n,
    input wire clear_valid,
    output wire clear_ready,
    input wire [8:0] clear_width, clear_height,
    input wire [31:0] clear_rgba,
    output wire clear_done_valid,
    input wire clear_done_ready,
    input wire read_valid,
    output wire read_ready,
    input wire [7:0] read_x, read_y,
    output wire read_result_valid,
    input wire read_result_ready,
    output wire [31:0] read_rgba,
    input wire write_valid,
    output wire write_ready,
    input wire [7:0] write_x, write_y,
    input wire [31:0] write_rgba,
    output wire write_done_valid,
    input wire write_done_ready,
    input wire export_valid,
    output wire export_ready,
    input wire [31:0] export_base, export_stride,
    output wire export_done_valid,
    input wire export_done_ready,
    output wire export_error,
    output wire [31:0] export_words,
    output wire dma_req_valid,
    input wire dma_req_ready,
    output wire [31:0] dma_req_addr, dma_req_data,
    output wire [3:0] dma_req_strb,
    output wire dma_req_last,
    input wire dma_rsp_valid,
    output wire dma_rsp_ready,
    input wire dma_rsp_error
);
    localparam LEGAL_PARAMETERS=MAX_WIDTH>=1 && MAX_WIDTH<=256 &&
        MAX_HEIGHT>=1 && MAX_HEIGHT<=256 && TILE_LOG2>=0 && TILE_LOG2<=4;
    localparam integer SAFE_WIDTH=MAX_WIDTH>=1 && MAX_WIDTH<=256 ? MAX_WIDTH : 1;
    localparam integer SAFE_HEIGHT=MAX_HEIGHT>=1 && MAX_HEIGHT<=256 ? MAX_HEIGHT : 1;
    localparam integer X_BITS=$clog2(SAFE_WIDTH), Y_BITS=$clog2(SAFE_HEIGHT);
    localparam integer ADDRESS_BITS=X_BITS+Y_BITS>0 ? X_BITS+Y_BITS : 1;
    localparam integer WORDS=1 << (X_BITS+Y_BITS);
    localparam integer SAFE_LOG2=TILE_LOG2>=0 && TILE_LOG2<=4 ? TILE_LOG2 : 0;
    localparam [8:0] TILE_SIZE=9'd1 << SAFE_LOG2;
    localparam IDLE=0, CLEAR_WRITE=1, CLEAR_DONE=2, READ_MEMORY=3,
               READ_CAPTURE=4, READ_RESULT=5, WRITE_MEMORY=6, WRITE_DONE=7,
               EXPORT_PRODUCT=8, EXPORT_ROW=9, EXPORT_ADDRESS=10,
               EXPORT_READ=11, EXPORT_CAPTURE=12, REQUEST=13,
               RESPONSE=14, ADVANCE=15, EXPORT_DONE=16;
    reg [4:0] state;
    reg configured;
    reg [8:0] width,height,x,y,tile_x,tile_y;
    reg [31:0] write_data,read_result,base,stride,row_address;
    reg [31:0] request_address,request_data,words_completed;
    reg [40:0] row_product;
    reg error_result;
    (* ramstyle = "M20K", nomem2reg *) reg [31:0] color_mem [0:WORDS-1];
    reg [31:0] memory_q;
    wire [ADDRESS_BITS-1:0] memory_address=({8'd0,y} << X_BITS) | {8'd0,x};
    wire [8:0] tile_limit_x=tile_x+TILE_SIZE;
    wire [8:0] tile_limit_y=tile_y+TILE_SIZE;
    wire [8:0] end_x=tile_limit_x>=width ? width-9'd1 : tile_limit_x-9'd1;
    wire [8:0] end_y=tile_limit_y>=height ? height-9'd1 : tile_limit_y-9'd1;
    wire final_pixel=x==width-9'd1 && y==height-9'd1;
    initial begin
        if (!LEGAL_PARAMETERS)
            $fatal(1,"PARAMETER ERROR: g3_framebuffer_dma dimensions or tile size");
    end
    assign clear_ready=rst_n && LEGAL_PARAMETERS && state==IDLE;
    assign read_ready=clear_ready && configured && !clear_valid;
    assign write_ready=read_ready && !read_valid;
    assign export_ready=write_ready && !write_valid;
    assign clear_done_valid=rst_n && state==CLEAR_DONE;
    assign read_result_valid=rst_n && state==READ_RESULT;
    assign read_rgba=read_result_valid ? read_result : 32'd0;
    assign write_done_valid=rst_n && state==WRITE_DONE;
    assign export_done_valid=rst_n && state==EXPORT_DONE;
    assign export_error=export_done_valid && error_result;
    assign export_words=export_done_valid ? words_completed : 32'd0;
    assign dma_req_valid=rst_n && state==REQUEST;
    assign dma_req_addr=dma_req_valid ? request_address : 32'd0;
    assign dma_req_data=dma_req_valid ? request_data : 32'd0;
    assign dma_req_strb=dma_req_valid ? 4'hf : 4'd0;
    assign dma_req_last=dma_req_valid && final_pixel;
    assign dma_rsp_ready=rst_n && state==RESPONSE;

    always @(posedge clk) begin
        if (rst_n && LEGAL_PARAMETERS) begin
            if (state==CLEAR_WRITE || state==WRITE_MEMORY)
                color_mem[memory_address]<=write_data;
            if (state==READ_MEMORY || state==EXPORT_READ)
                memory_q<=color_mem[memory_address];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; configured<=0; width<=0; height<=0;
            x<=0; y<=0; tile_x<=0; tile_y<=0;
            write_data<=0; read_result<=0; base<=0; stride<=0;
            row_product<=0; row_address<=0; request_address<=0;
            request_data<=0; words_completed<=0; error_result<=0;
        end else if (LEGAL_PARAMETERS) begin
            case (state)
                IDLE: begin
                    if (clear_valid) begin
                        width<=clear_width; height<=clear_height;
                        write_data<=clear_rgba; x<=0; y<=0;
                        configured<=0; state<=CLEAR_WRITE;
                    end else if (read_valid && configured) begin
                        x<={1'b0,read_x}; y<={1'b0,read_y}; state<=READ_MEMORY;
                    end else if (write_valid && configured) begin
                        x<={1'b0,write_x}; y<={1'b0,write_y};
                        write_data<=write_rgba; state<=WRITE_MEMORY;
                    end else if (export_valid && configured) begin
                        base<=export_base; stride<=export_stride;
                        x<=0; y<=0; tile_x<=0; tile_y<=0;
                        words_completed<=0; error_result<=0; state<=EXPORT_PRODUCT;
                    end
                end
                CLEAR_WRITE: begin
                    if (x==width-9'd1) begin
                        x<=0;
                        if (y==height-9'd1) begin configured<=1; state<=CLEAR_DONE; end
                        else y<=y+9'd1;
                    end else x<=x+9'd1;
                end
                CLEAR_DONE: if (clear_done_ready) state<=IDLE;
                READ_MEMORY: state<=READ_CAPTURE;
                READ_CAPTURE: begin read_result<=memory_q; state<=READ_RESULT; end
                READ_RESULT: if (read_result_ready) state<=IDLE;
                WRITE_MEMORY: state<=WRITE_DONE;
                WRITE_DONE: if (write_done_ready) state<=IDLE;
                EXPORT_PRODUCT: begin row_product<=y*stride; state<=EXPORT_ROW; end
                EXPORT_ROW: begin row_address<=base+row_product[31:0]; state<=EXPORT_ADDRESS; end
                EXPORT_ADDRESS: begin
                    request_address<=row_address+{21'd0,x,2'd0};
                    state<=EXPORT_READ;
                end
                EXPORT_READ: state<=EXPORT_CAPTURE;
                EXPORT_CAPTURE: begin request_data<=memory_q; state<=REQUEST; end
                REQUEST: if (dma_req_ready) state<=RESPONSE;
                RESPONSE: if (dma_rsp_valid) begin
                    if (dma_rsp_error) begin error_result<=1; state<=EXPORT_DONE; end
                    else begin
                        words_completed<=words_completed+32'd1;
                        if (final_pixel) state<=EXPORT_DONE;
                        else state<=ADVANCE;
                    end
                end
                ADVANCE: begin
                    if (x==end_x) begin
                        if (y==end_y) begin
                            if (tile_limit_x>=width) begin
                                tile_x<=0; x<=0;
                                tile_y<=tile_y+TILE_SIZE; y<=tile_y+TILE_SIZE;
                            end else begin
                                tile_x<=tile_x+TILE_SIZE; x<=tile_x+TILE_SIZE;
                                y<=tile_y;
                            end
                        end else begin x<=tile_x; y<=y+9'd1; end
                    end else x<=x+9'd1;
                    state<=EXPORT_PRODUCT;
                end
                EXPORT_DONE: if (export_done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
