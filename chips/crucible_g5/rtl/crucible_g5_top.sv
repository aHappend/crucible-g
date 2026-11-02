module crucible_g5_top #(
    parameter integer MAX_WIDTH=256, MAX_HEIGHT=256, TILE_LOG2=3,
    parameter integer MAX_NODES=64, MAX_SPLATS=64, STACK_DEPTH=16,
    parameter integer MAX_PRIMITIVES=64, SVGF_MAX_WIDTH=32, SVGF_MAX_HEIGHT=32
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
        STACK_DEPTH>=1 && STACK_DEPTH<=64 && MAX_PRIMITIVES>=1 &&
        MAX_PRIMITIVES<=128 && SVGF_MAX_WIDTH>=1 && SVGF_MAX_WIDTH<=64 &&
        SVGF_MAX_HEIGHT>=1 && SVGF_MAX_HEIGHT<=64;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: crucible_g5_top parameters");
        assign s_ready=0; assign m_valid=0; assign m_data=0; assign m_last=0;
        assign tex_req_valid=0; assign tex_req_addr=0; assign tex_rsp_ready=0;
        assign dma_req_valid=0; assign dma_req_addr=0; assign dma_req_data=0;
        assign dma_req_strb=0; assign dma_req_last=0; assign dma_rsp_ready=0;
    end else begin: implementation
        localparam BOOT=0, INTAKE=1, DISPATCH=2, REPLAY=3, LEGACY_WAIT=4,
            BUILDER_SEND=5, BUILDER_WAIT=6, QUERY_SEND=7, QUERY_WAIT=8,
            TRIANGLE_SEND=9, TRIANGLE_WAIT=10, DENOISE_SEND=11,
            DENOISE_WAIT=12, OUTPUT_RECORD=13;
        reg [3:0] state, record_source;
        reg [1567:0] command;
        reg [5:0] word_index;
        reg long_frame;
        reg [511:0] record;
        reg [3:0] output_index;
        reg terminal;
        wire [31:0] opcode=command[64 +:32];
        wire legacy_ready, legacy_valid, legacy_last;
        wire [31:0] legacy_data;
        wire legacy_tex_valid, legacy_tex_ready;
        wire [31:0] legacy_tex_addr;
        wire legacy_dma_valid, legacy_dma_ready, legacy_dma_last;
        wire [31:0] legacy_dma_addr, legacy_dma_data;
        wire [3:0] legacy_dma_strb;
        wire builder_ready, builder_valid, builder_terminal;
        wire query_ready, query_valid, query_terminal;
        wire triangle_ready, triangle_valid, triangle_terminal;
        wire denoise_ready, denoise_valid, denoise_terminal;
        wire [511:0] builder_record, query_record, triangle_record, denoise_record;
        wire tree_valid, rd_valid, rd_ready, rd_rsp_valid, rd_rsp_ready;
        wire [31:0] tree_count, tree_nodes, rd_index, rd_parent;
        wire [511:0] rd_node;
        wire [287:0] rd_vertices;
        wire query_tri_valid, query_tri_ready, query_tri_rsp_ready;
        wire [991:0] query_tri_command;
        wire triangle_owned_by_query=state==QUERY_WAIT;
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
        crucible_g4_top #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
            .TILE_LOG2(TILE_LOG2),.MAX_NODES(MAX_NODES),
            .MAX_SPLATS(MAX_SPLATS),.STACK_DEPTH(STACK_DEPTH)) compatibility (
            .clk(clk),.rst_n(rst_n),.s_valid(rst_n && state==REPLAY),
            .s_ready(legacy_ready),.s_data(command[word_index*32 +:32]),
            .m_valid(legacy_valid),.m_ready(rst_n && state==LEGACY_WAIT && m_ready),
            .m_data(legacy_data),.m_last(legacy_last),
            .tex_req_valid(legacy_tex_valid),.tex_req_ready(tex_req_ready && rst_n),
            .tex_req_addr(legacy_tex_addr),.tex_rsp_valid(tex_rsp_valid && rst_n),
            .tex_rsp_ready(legacy_tex_ready),.tex_rsp_data(tex_rsp_data),
            .tex_rsp_error(tex_rsp_error),.dma_req_valid(legacy_dma_valid),
            .dma_req_ready(dma_req_ready && rst_n),.dma_req_addr(legacy_dma_addr),
            .dma_req_data(legacy_dma_data),.dma_req_strb(legacy_dma_strb),
            .dma_req_last(legacy_dma_last),.dma_rsp_valid(dma_rsp_valid && rst_n),
            .dma_rsp_ready(legacy_dma_ready),.dma_rsp_error(dma_rsp_error)
        );
        g5_lbvh #(.MAX_PRIMITIVES(MAX_PRIMITIVES)) builder (
            .clk(clk),.rst_n(rst_n),.s_valid(rst_n && state==BUILDER_SEND),
            .s_ready(builder_ready),.s_command(command[991:0]),
            .m_valid(builder_valid),.m_ready(rst_n && state==BUILDER_WAIT),
            .m_record(builder_record),.m_terminal(builder_terminal),
            .tree_valid(tree_valid),.tree_count(tree_count),.tree_nodes(tree_nodes),
            .rd_valid(rd_valid),.rd_ready(rd_ready),.rd_index(rd_index),
            .rd_rsp_valid(rd_rsp_valid),.rd_rsp_ready(rd_rsp_ready),
            .rd_node(rd_node),.rd_vertices(rd_vertices),.rd_parent(rd_parent)
        );
        g5_ray_query #(.MAX_PRIMITIVES(MAX_PRIMITIVES)) ray_query (
            .clk(clk),.rst_n(rst_n),.s_valid(rst_n && state==QUERY_SEND),
            .s_ready(query_ready),.s_command(command[991:0]),
            .m_valid(query_valid),.m_ready(rst_n && state==QUERY_WAIT),
            .m_record(query_record),.m_terminal(query_terminal),
            .tree_valid(tree_valid),.tree_count(tree_count),.tree_nodes(tree_nodes),
            .rd_valid(rd_valid),.rd_ready(rd_ready),.rd_index(rd_index),
            .rd_rsp_valid(rd_rsp_valid),.rd_rsp_ready(rd_rsp_ready),
            .rd_node(rd_node),.rd_vertices(rd_vertices),.rd_parent(rd_parent),
            .tri_valid(query_tri_valid),.tri_ready(query_tri_ready),
            .tri_command(query_tri_command),
            .tri_rsp_valid(triangle_valid && triangle_owned_by_query),
            .tri_rsp_ready(query_tri_rsp_ready),.tri_record(triangle_record)
        );
        assign query_tri_ready=triangle_ready && triangle_owned_by_query;
        g5_ray_triangle triangle (
            .clk(clk),.rst_n(rst_n),
            .s_valid(rst_n && (state==TRIANGLE_SEND ||
                (triangle_owned_by_query && query_tri_valid))),
            .s_ready(triangle_ready),
            .s_command(triangle_owned_by_query ? query_tri_command : command[991:0]),
            .m_valid(triangle_valid),
            .m_ready(rst_n && (state==TRIANGLE_WAIT ||
                (triangle_owned_by_query && query_tri_rsp_ready))),
            .m_record(triangle_record),.m_terminal(triangle_terminal)
        );
        g5_svgf #(.MAX_WIDTH(SVGF_MAX_WIDTH),.MAX_HEIGHT(SVGF_MAX_HEIGHT)) denoiser (
            .clk(clk),.rst_n(rst_n),.s_valid(rst_n && state==DENOISE_SEND),
            .s_ready(denoise_ready),.s_command(command[991:0]),
            .m_valid(denoise_valid),.m_ready(rst_n && state==DENOISE_WAIT),
            .m_record(denoise_record),.m_terminal(denoise_terminal)
        );
        assign s_ready=rst_n && state==INTAKE;
        assign m_valid=rst_n && (state==OUTPUT_RECORD ||
            (state==LEGACY_WAIT && legacy_valid));
        assign m_data=!m_valid ? 32'd0 : state==OUTPUT_RECORD ?
            record[output_index*32 +:32] : legacy_data;
        assign m_last=m_valid && (state==OUTPUT_RECORD ?
            terminal && output_index==15 : legacy_last);
        assign tex_req_valid=rst_n && legacy_tex_valid;
        assign tex_req_addr=rst_n ? legacy_tex_addr : 32'd0;
        assign tex_rsp_ready=rst_n && legacy_tex_ready;
        assign dma_req_valid=rst_n && legacy_dma_valid;
        assign dma_req_addr=rst_n ? legacy_dma_addr : 32'd0;
        assign dma_req_data=rst_n ? legacy_dma_data : 32'd0;
        assign dma_req_strb=rst_n ? legacy_dma_strb : 4'd0;
        assign dma_req_last=rst_n && legacy_dma_last;
        assign dma_rsp_ready=rst_n && legacy_dma_ready;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=BOOT; record_source<=0; command<=0; word_index<=0;
                long_frame<=0; record<=0; output_index<=0; terminal<=0;
            end else case (state)
                BOOT: state<=INTAKE;
                INTAKE: if (s_valid) begin
                    command[word_index*32 +:32]<=s_data;
                    if (word_index==2) long_frame<=is_draw(s_data);
                    if ((!long_frame && word_index==30) ||
                        (long_frame && word_index==48)) begin
                        word_index<=0; state<=DISPATCH;
                    end else word_index<=word_index+6'd1;
                end
                DISPATCH: case (opcode)
                    32'h900,32'h901,32'h902: state<=BUILDER_SEND;
                    32'h903: state<=QUERY_SEND;
                    32'h910: state<=TRIANGLE_SEND;
                    32'h920,32'h921,32'h922,32'h923: state<=DENOISE_SEND;
                    default: state<=REPLAY;
                endcase
                REPLAY: if (legacy_ready) begin
                    if ((!long_frame && word_index==30) ||
                        (long_frame && word_index==48)) begin
                        word_index<=0; state<=LEGACY_WAIT;
                    end else word_index<=word_index+6'd1;
                end
                LEGACY_WAIT: if (legacy_valid && m_ready && legacy_last)
                    state<=INTAKE;
                BUILDER_SEND: if (builder_ready) state<=BUILDER_WAIT;
                QUERY_SEND: if (query_ready) state<=QUERY_WAIT;
                TRIANGLE_SEND: if (triangle_ready) state<=TRIANGLE_WAIT;
                DENOISE_SEND: if (denoise_ready) state<=DENOISE_WAIT;
                BUILDER_WAIT: if (builder_valid) begin
                    record<=builder_record; terminal<=builder_terminal;
                    record_source<=BUILDER_WAIT; output_index<=0; state<=OUTPUT_RECORD;
                end
                QUERY_WAIT: if (query_valid) begin
                    record<=query_record; terminal<=query_terminal;
                    record_source<=QUERY_WAIT; output_index<=0; state<=OUTPUT_RECORD;
                end
                TRIANGLE_WAIT: if (triangle_valid) begin
                    record<=triangle_record; terminal<=triangle_terminal;
                    record_source<=TRIANGLE_WAIT; output_index<=0; state<=OUTPUT_RECORD;
                end
                DENOISE_WAIT: if (denoise_valid) begin
                    record<=denoise_record; terminal<=denoise_terminal;
                    record_source<=DENOISE_WAIT; output_index<=0; state<=OUTPUT_RECORD;
                end
                OUTPUT_RECORD: if (m_ready) begin
                    if (output_index==15) begin
                        output_index<=0;
                        if (terminal) state<=INTAKE;
                        else state<=record_source;
                    end else output_index<=output_index+4'd1;
                end
                default: begin
                    state<=BOOT;
`ifndef SYNTHESIS
                    $fatal(1,"crucible_g5_top: invalid control state");
`endif
                end
            endcase
        end
    end endgenerate
endmodule
