module g2_zbuffer #(
    parameter integer MAX_WIDTH=256,
    parameter integer MAX_HEIGHT=256,
    parameter integer TILE_LOG2=3
) (
    input wire clk, rst_n,
    input wire clear_valid,
    output wire clear_ready,
    input wire [8:0] clear_width, clear_height,
    input wire clear_depth24,
    output wire clear_done_valid,
    input wire clear_done_ready,
    input wire tile_valid,
    output wire tile_ready,
    input wire [7:0] tile_x, tile_y,
    input wire [23:0] tile_zmin,
    output wire tile_result_valid,
    input wire tile_result_ready,
    output wire tile_reject,
    input wire frag_valid,
    output wire frag_ready,
    input wire [7:0] frag_x, frag_y,
    input wire [23:0] frag_depth,
    output wire frag_result_valid,
    input wire frag_result_ready,
    output wire frag_pass
);
    localparam integer SAFE_WIDTH =
        MAX_WIDTH>=1 && MAX_WIDTH<=256 ? MAX_WIDTH : 1;
    localparam integer SAFE_HEIGHT =
        MAX_HEIGHT>=1 && MAX_HEIGHT<=256 ? MAX_HEIGHT : 1;
    localparam integer X_BITS = $clog2(SAFE_WIDTH);
    localparam integer Y_BITS = $clog2(SAFE_HEIGHT);
    localparam integer ADDRESS_BITS = X_BITS+Y_BITS>0 ? X_BITS+Y_BITS : 1;
    localparam integer WORDS = 1 << (X_BITS+Y_BITS);
    localparam integer SAFE_LOG2 = TILE_LOG2>=0 && TILE_LOG2<=4 ? TILE_LOG2 : 0;
    localparam [8:0] TILE_SIZE = 9'd1 << SAFE_LOG2;
    localparam IDLE=0, CLEAR_WRITE=1, CLEAR_DONE=2, TILE_READ=3,
               TILE_ACCUMULATE=4, TILE_RESULT=5, FRAG_READ=6,
               FRAG_COMPARE=7, FRAG_WRITE=8, FRAG_RESULT=9;
    reg [3:0] state;
    (* ramstyle = "M20K", nomem2reg *) reg [23:0] depth_mem [0:WORDS-1];
    reg [23:0] memory_q;
    reg [8:0] width,height,x,y,start_x,end_x,end_y;
    reg depth24;
    reg [23:0] maximum,zmin,new_depth;
    reg reject_result,pass_result;
    wire [8:0] requested_end_x = {1'b0,tile_x}+TILE_SIZE-9'd1;
    wire [8:0] requested_end_y = {1'b0,tile_y}+TILE_SIZE-9'd1;
    wire [23:0] next_maximum = memory_q>maximum ? memory_q : maximum;
    wire [ADDRESS_BITS-1:0] address =
        ({7'd0,y} << X_BITS) | {7'd0,x};
    wire memory_write = rst_n && (state==CLEAR_WRITE || state==FRAG_WRITE);
    wire [23:0] memory_write_data = state==CLEAR_WRITE ?
        (depth24 ? 24'hffffff : 24'h00ffff) : new_depth;

    initial begin
        if (MAX_WIDTH<1 || MAX_WIDTH>256 || MAX_HEIGHT<1 || MAX_HEIGHT>256 ||
            TILE_LOG2<0 || TILE_LOG2>4)
            $fatal(1,"PARAMETER ERROR: g2_zbuffer dimensions or tile size");
    end
    always @(posedge clk) begin
        if (memory_write) depth_mem[address]<=memory_write_data;
        if (rst_n && (state==TILE_READ || state==FRAG_READ))
            memory_q<=depth_mem[address];
    end
    assign clear_ready = rst_n && state==IDLE;
    assign tile_ready = rst_n && state==IDLE && !clear_valid;
    assign frag_ready = rst_n && state==IDLE && !clear_valid && !tile_valid;
    assign clear_done_valid = rst_n && state==CLEAR_DONE;
    assign tile_result_valid = rst_n && state==TILE_RESULT;
    assign tile_reject = tile_result_valid && reject_result;
    assign frag_result_valid = rst_n && state==FRAG_RESULT;
    assign frag_pass = frag_result_valid && pass_result;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; width<=0; height<=0; x<=0; y<=0;
            start_x<=0; end_x<=0; end_y<=0; depth24<=0;
            maximum<=0; zmin<=0; new_depth<=0;
            reject_result<=0; pass_result<=0;
        end else begin
            case (state)
                IDLE: begin
                    if (clear_valid) begin
                        width<=clear_width; height<=clear_height;
                        depth24<=clear_depth24; x<=0; y<=0;
                        state<=CLEAR_WRITE;
                    end else if (tile_valid) begin
                        x<={1'b0,tile_x}; y<={1'b0,tile_y};
                        start_x<={1'b0,tile_x};
                        end_x<=requested_end_x>=width ? width-9'd1 : requested_end_x;
                        end_y<=requested_end_y>=height ? height-9'd1 : requested_end_y;
                        maximum<=0; zmin<=tile_zmin;
                        state<=TILE_READ;
                    end else if (frag_valid) begin
                        x<={1'b0,frag_x}; y<={1'b0,frag_y};
                        new_depth<=frag_depth; state<=FRAG_READ;
                    end
                end
                CLEAR_WRITE: begin
                    if (x==width-9'd1) begin
                        x<=0;
                        if (y==height-9'd1) state<=CLEAR_DONE;
                        else y<=y+9'd1;
                    end else x<=x+9'd1;
                end
                CLEAR_DONE: if (clear_done_ready) state<=IDLE;
                TILE_READ: state<=TILE_ACCUMULATE;
                TILE_ACCUMULATE: begin
                    maximum<=next_maximum;
                    if (x==end_x) begin
                        x<=start_x;
                        if (y==end_y) begin
                            reject_result<=zmin>=next_maximum;
                            state<=TILE_RESULT;
                        end else begin y<=y+9'd1; state<=TILE_READ; end
                    end else begin x<=x+9'd1; state<=TILE_READ; end
                end
                TILE_RESULT: if (tile_result_ready) state<=IDLE;
                FRAG_READ: state<=FRAG_COMPARE;
                FRAG_COMPARE: begin
                    pass_result<=new_depth<memory_q;
                    if (new_depth<memory_q) state<=FRAG_WRITE;
                    else state<=FRAG_RESULT;
                end
                FRAG_WRITE: state<=FRAG_RESULT;
                FRAG_RESULT: if (frag_result_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
