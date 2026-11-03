module crucible_g4_top #(
    parameter integer MAX_WIDTH=256, MAX_HEIGHT=256, TILE_LOG2=3,
    parameter integer MAX_NODES=64, MAX_SPLATS=64, STACK_DEPTH=16
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [31:0] s_data,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_data,
    output wire m_last,
    output wire tex_req_valid,
    input wire tex_req_ready,
    output wire [31:0] tex_req_addr,
    input wire tex_rsp_valid,
    output wire tex_rsp_ready,
    input wire [31:0] tex_rsp_data,
    input wire tex_rsp_error,
    output wire dma_req_valid,
    input wire dma_req_ready,
    output wire [31:0] dma_req_addr, dma_req_data,
    output wire [3:0] dma_req_strb,
    output wire dma_req_last,
    input wire dma_rsp_valid,
    output wire dma_rsp_ready,
    input wire dma_rsp_error
);
    localparam LEGAL=MAX_WIDTH>=1 && MAX_WIDTH<=256 &&
        MAX_HEIGHT>=1 && MAX_HEIGHT<=256 && TILE_LOG2>=0 && TILE_LOG2<=4 &&
        MAX_NODES>=1 && MAX_NODES<=256 && MAX_SPLATS>=1 && MAX_SPLATS<=256 &&
        STACK_DEPTH>=1 && STACK_DEPTH<=64;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: crucible_g4_top parameters");
        assign s_ready=0;
        assign m_valid=0; assign m_data=0; assign m_last=0;
        assign tex_req_valid=0; assign tex_req_addr=0; assign tex_rsp_ready=0;
        assign dma_req_valid=0; assign dma_req_addr=0; assign dma_req_data=0;
        assign dma_req_strb=0; assign dma_req_last=0; assign dma_rsp_ready=0;
    end else begin: implementation
        localparam BOOT=0, INTAKE=1, DISPATCH=2, REPLAY=3, PARENT_WAIT=4,
                   BVH_SEND=5, BVH_WAIT=6, SPLAT_SEND=7, SPLAT_WAIT=8,
                   OUTPUT_RECORD=9;
        reg [3:0] state;
        reg [1567:0] command;
        reg [5:0] word_index;
        reg long_frame;
        reg [511:0] record;
        reg [3:0] output_index;
        reg terminal, from_splat;
        wire parent_ready, parent_valid, parent_last;
        wire [31:0] parent_data;
        wire parent_tex_valid, parent_tex_ready;
        wire [31:0] parent_tex_addr;
        wire parent_dma_valid, parent_dma_ready, parent_dma_last;
        wire [31:0] parent_dma_addr, parent_dma_data;
        wire [3:0] parent_dma_strb;
        wire bvh_ready, bvh_valid, bvh_terminal;
        wire splat_ready, splat_valid, splat_terminal;
        wire [511:0] bvh_record, splat_record;
        wire [31:0] opcode=command[64 +:32];
        function automatic is_draw;
            input [31:0] op;
            begin
                case (op)
                    2,3,6,7,258,259,262,263,514,515,518,519,770,771,774,775:
                        is_draw=1;
                    default: is_draw=0;
                endcase
            end
        endfunction
        crucible_g3_top #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
            .TILE_LOG2(TILE_LOG2)) compatibility (
            .clk(clk),.rst_n(rst_n),.s_valid(state==REPLAY),
            .s_ready(parent_ready),.s_data(command[word_index*32 +:32]),
            .m_valid(parent_valid),.m_ready(state==PARENT_WAIT && m_ready),
            .m_data(parent_data),.m_last(parent_last),
            .tex_req_valid(parent_tex_valid),.tex_req_ready(tex_req_ready && rst_n),
            .tex_req_addr(parent_tex_addr),.tex_rsp_valid(tex_rsp_valid && rst_n),
            .tex_rsp_ready(parent_tex_ready),.tex_rsp_data(tex_rsp_data),
            .tex_rsp_error(tex_rsp_error),.dma_req_valid(parent_dma_valid),
            .dma_req_ready(dma_req_ready && rst_n),.dma_req_addr(parent_dma_addr),
            .dma_req_data(parent_dma_data),.dma_req_strb(parent_dma_strb),
            .dma_req_last(parent_dma_last),.dma_rsp_valid(dma_rsp_valid && rst_n),
            .dma_rsp_ready(parent_dma_ready),.dma_rsp_error(dma_rsp_error)
        );
        g4_bvh #(.MAX_NODES(MAX_NODES),.STACK_DEPTH(STACK_DEPTH)) bvh (
            .clk(clk),.rst_n(rst_n),.s_valid(state==BVH_SEND),
            .s_ready(bvh_ready),.s_command(command[991:0]),
            .m_valid(bvh_valid),.m_ready(state==BVH_WAIT),
            .m_record(bvh_record),.m_terminal(bvh_terminal)
        );
        g4_splat #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
            .MAX_SPLATS(MAX_SPLATS)) splat (
            .clk(clk),.rst_n(rst_n),.s_valid(state==SPLAT_SEND),
            .s_ready(splat_ready),.s_command(command[991:0]),
            .m_valid(splat_valid),.m_ready(state==SPLAT_WAIT),
            .m_record(splat_record),.m_terminal(splat_terminal)
        );
        assign s_ready=rst_n && state==INTAKE;
        assign m_valid=rst_n && (state==OUTPUT_RECORD ||
            (state==PARENT_WAIT && parent_valid));
        assign m_data=!m_valid ? 32'd0 : state==OUTPUT_RECORD ?
            record[output_index*32 +:32] : parent_data;
        assign m_last=m_valid && (state==OUTPUT_RECORD ?
            terminal && output_index==15 : parent_last);
        assign tex_req_valid=rst_n && parent_tex_valid;
        assign tex_req_addr=rst_n ? parent_tex_addr : 32'd0;
        assign tex_rsp_ready=rst_n && parent_tex_ready;
        assign dma_req_valid=rst_n && parent_dma_valid;
        assign dma_req_addr=rst_n ? parent_dma_addr : 32'd0;
        assign dma_req_data=rst_n ? parent_dma_data : 32'd0;
        assign dma_req_strb=rst_n ? parent_dma_strb : 4'd0;
        assign dma_req_last=rst_n && parent_dma_last;
        assign dma_rsp_ready=rst_n && parent_dma_ready;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=BOOT; command<=0; word_index<=0; long_frame<=0;
                record<=0; output_index<=0; terminal<=0; from_splat<=0;
            end else begin
                case (state)
                    BOOT: state<=INTAKE;
                    INTAKE: if (s_valid) begin
                        command[word_index*32 +:32]<=s_data;
                        if (word_index==2) long_frame<=is_draw(s_data);
                        if ((!long_frame && word_index==30) ||
                            (long_frame && word_index==48)) begin
                            word_index<=0; state<=DISPATCH;
                        end else word_index<=word_index+6'd1;
                    end
                    DISPATCH: begin
                        if (opcode==32'h800 || opcode==32'h801) state<=BVH_SEND;
                        else if (opcode==32'h810 || opcode==32'h811) state<=SPLAT_SEND;
                        else state<=REPLAY;
                    end
                    REPLAY: if (parent_ready) begin
                        if ((!long_frame && word_index==30) ||
                            (long_frame && word_index==48)) begin
                            word_index<=0; state<=PARENT_WAIT;
                        end else word_index<=word_index+6'd1;
                    end
                    PARENT_WAIT: if (parent_valid && m_ready && parent_last)
                        state<=INTAKE;
                    BVH_SEND: if (bvh_ready) state<=BVH_WAIT;
                    SPLAT_SEND: if (splat_ready) state<=SPLAT_WAIT;
                    BVH_WAIT: if (bvh_valid) begin
                        record<=bvh_record; terminal<=bvh_terminal;
                        from_splat<=0; output_index<=0; state<=OUTPUT_RECORD;
                    end
                    SPLAT_WAIT: if (splat_valid) begin
                        record<=splat_record; terminal<=splat_terminal;
                        from_splat<=1; output_index<=0; state<=OUTPUT_RECORD;
                    end
                    OUTPUT_RECORD: if (m_ready) begin
                        if (output_index==15) begin
                            output_index<=0;
                            if (terminal) state<=INTAKE;
                            else if (from_splat) state<=SPLAT_WAIT;
                            else state<=BVH_WAIT;
                        end else output_index<=output_index+4'd1;
                    end
                    default: state<=BOOT;
                endcase
            end
        end
    end endgenerate
endmodule
