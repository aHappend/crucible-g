module g5_ray_query #(
    parameter integer MAX_PRIMITIVES=64
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [991:0] s_command,
    output wire m_valid,
    input wire m_ready,
    output wire [511:0] m_record,
    output wire m_terminal,
    input wire tree_valid,
    input wire [31:0] tree_count, tree_nodes,
    output wire rd_valid,
    input wire rd_ready,
    output wire [31:0] rd_index,
    input wire rd_rsp_valid,
    output wire rd_rsp_ready,
    input wire [511:0] rd_node,
    input wire [287:0] rd_vertices,
    input wire [31:0] rd_parent,
    output wire tri_valid,
    input wire tri_ready,
    output wire [991:0] tri_command,
    input wire tri_rsp_valid,
    output wire tri_rsp_ready,
    input wire [511:0] tri_record
);
    localparam LEGAL=MAX_PRIMITIVES>=1 && MAX_PRIMITIVES<=128;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_ray_query MAX_PRIMITIVES");
        assign s_ready=0; assign m_valid=0; assign m_record=0; assign m_terminal=0;
        assign rd_valid=0; assign rd_index=0; assign rd_rsp_ready=0;
        assign tri_valid=0; assign tri_command=0; assign tri_rsp_ready=0;
    end else begin: implementation
        localparam CAPACITY=2*MAX_PRIMITIVES-1;
        localparam IDLE=0, RANGE_SEND=1, RANGE_WAIT=2,
            READ_SEND=3, READ_WAIT=4, NODE_CHECK=5,
            SLAB_SEND=6, SLAB_WAIT=7, DESCEND=8, ASCEND=9,
            TRI_PREPARE=10, TRI_SEND=11, TRI_WAIT=12,
            DISTANCE_SEND=13, DISTANCE_WAIT=14,
            ID_SEND=15, ID_WAIT=16, SLOT_SEND=17, SLOT_WAIT=18,
            REPLACE=19, HOLD=20;
        reg [4:0] state;
        reg [991:0] command, triangle_command;
        reg [511:0] record, node, candidate;
        reg [287:0] vertices;
        reg [31:0] parent, current, expected_parent, returned_child;
        reg returning, best;
        reg [8:0] scene_nodes;
        reg [7:0] scene_primitives;
        reg [9:0] transitions;
        reg [15:0] transition_limit;
        reg [CAPACITY-1:0] visited;
        wire [31:0] node_id=node[96 +:32], leaf=node[128 +:32];
        wire [31:0] left=node[160 +:32], right=node[192 +:32];
        wire [31:0] primitive_id=node[224 +:32], slot=node[256 +:32];
        wire signed [63:0] t_min=command[320 +:64], t_max=command[384 +:64];
        wire [63:0] best_t=record[128 +:64];
        wire malformed=s_command[32 +:32]!=0 ||
            s_command[64 +:32]!=32'h903 || (|s_command[127:97]) ||
            (|s_command[991:448]) || s_command[383] || s_command[447];
        wire alu_ready, alu_valid, alu_less, alu_equal, alu_carry;
        wire [63:0] alu_result;
        reg [63:0] alu_a, alu_b;
        wire alu_send=state==RANGE_SEND || state==DISTANCE_SEND ||
            state==ID_SEND || state==SLOT_SEND;
        wire alu_wait=state==RANGE_WAIT || state==DISTANCE_WAIT ||
            state==ID_WAIT || state==SLOT_WAIT;
        wire slab_ready, slab_valid, slab_hit, slab_error;
        wire signed [63:0] slab_entry, slab_exit;
        wire bad_common=node[64 +:32]!=0 || node_id!=current ||
            leaf>1 || (current==0 && parent!=32'hffffffff);
        wire bad_internal=left>=scene_nodes || right>=scene_nodes ||
            left==right || left==current || right==current;
        g5_limb_alu #(.WIDTH(64)) query_arithmetic (
            .clk(clk),.rst_n(rst_n),.s_valid(alu_send),.s_ready(alu_ready),
            .s_a(alu_a),.s_b(alu_b),.s_subtract(1'b1),
            .m_valid(alu_valid),.m_ready(alu_wait),.m_result(alu_result),
            .m_less(alu_less),.m_equal(alu_equal),.m_carry(alu_carry)
        );
        g5_slab slab (
            .clk(clk),.rst_n(rst_n),.s_valid(state==SLAB_SEND),
            .s_ready(slab_ready),.s_origin(command[128 +:96]),
            .s_direction(command[224 +:96]),.s_bounds(node[320 +:192]),
            .s_t_min(t_min),.s_t_max(best ? $signed(best_t) : t_max),
            .m_valid(slab_valid),.m_ready(state==SLAB_WAIT),
            .m_hit(slab_hit),.m_error(slab_error),
            .m_t_enter(slab_entry),.m_t_exit(slab_exit)
        );
        assign s_ready=rst_n && state==IDLE;
        assign m_valid=rst_n && state==HOLD;
        assign m_record=m_valid ? record : 512'd0;
        assign m_terminal=m_valid;
        assign rd_valid=rst_n && state==READ_SEND;
        assign rd_index=rd_valid ? current : 32'd0;
        assign rd_rsp_ready=rst_n && state==READ_WAIT;
        assign tri_valid=rst_n && state==TRI_SEND;
        assign tri_command=tri_valid ? triangle_command : 992'd0;
        assign tri_rsp_ready=rst_n && state==TRI_WAIT;
        always @* begin
            alu_a=0; alu_b=0;
            case (state)
                RANGE_SEND: begin alu_a=t_min; alu_b=t_max; end
                DISTANCE_SEND: begin alu_a=candidate[128 +:64]; alu_b=best_t; end
                ID_SEND: begin
                    alu_a={32'd0,primitive_id}; alu_b={32'd0,record[256 +:32]};
                end
                SLOT_SEND: begin
                    alu_a={32'd0,slot}; alu_b={32'd0,record[288 +:32]};
                end
                default: begin end
            endcase
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; command<=0; triangle_command<=0;
                record<=0; node<=0; candidate<=0; vertices<=0; parent<=0;
                current<=0; expected_parent<=0; returned_child<=0;
                returning<=0; best<=0; scene_nodes<=0; scene_primitives<=0;
                transitions<=0; transition_limit<=0; visited<=0;
            end else case (state)
                IDLE: if (s_valid) begin
                    command<=s_command; record<=0;
                    record[0 +:32]<=32'h50000010;
                    record[32 +:32]<=s_command[0 +:32];
                    record[256 +:32]<=32'hffffffff;
                    record[288 +:32]<=32'hffffffff;
                    best<=0; current<=0; expected_parent<=32'hffffffff;
                    returned_child<=0; returning<=0; transitions<=0; visited<=0;
                    scene_nodes<=tree_nodes[8:0]; scene_primitives<=tree_count[7:0];
                    transition_limit<=({7'd0,tree_nodes[8:0]}<<1)+
                        {7'd0,tree_nodes[8:0]}+16'd1;
                    if (malformed) begin
                        record[64 +:32]<=1; record[511:96]<=0; state<=HOLD;
                    end else state<=RANGE_SEND;
                end
                RANGE_SEND: if (alu_ready) state<=RANGE_WAIT;
                RANGE_WAIT: if (alu_valid) begin
                    if (!alu_less && !alu_equal) begin
                        record[64 +:32]<=1; record[511:96]<=0; state<=HOLD;
                    end else if (!tree_valid) begin
                        record[64 +:32]<=2; record[511:96]<=0; state<=HOLD;
                    end else if (scene_nodes==0 && scene_primitives==0) state<=HOLD;
                    else if (scene_primitives==0 || scene_primitives>MAX_PRIMITIVES ||
                        scene_nodes!=({1'b0,scene_primitives}<<1)-9'd1) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else state<=READ_SEND;
                end
                READ_SEND: begin
                    if (current>=scene_nodes || transitions>=transition_limit) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else if (rd_ready) begin
                        transitions<=transitions+10'd1; state<=READ_WAIT;
                    end
                end
                READ_WAIT: if (rd_rsp_valid) begin
                    node<=rd_node; vertices<=rd_vertices; parent<=rd_parent;
                    state<=NODE_CHECK;
                end
                NODE_CHECK: begin
                    if (bad_common || (!leaf && bad_internal) ||
                        (leaf && (left!=32'hffffffff || right!=32'hffffffff ||
                            slot>=scene_primitives)) ||
                        (!returning && (parent!=expected_parent || visited[current]))) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else if (returning) begin
                        if (leaf || !visited[current]) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                        end else if (returned_child==left) begin
                            expected_parent<=current; current<=right;
                            returning<=0; state<=READ_SEND;
                        end else if (returned_child==right) state<=ASCEND;
                        else begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                        end
                    end else begin
                        visited[current]<=1;
                        record[320 +:9]<=record[320 +:9]+9'd1;
                        state<=SLAB_SEND;
                    end
                end
                SLAB_SEND: if (slab_ready) state<=SLAB_WAIT;
                SLAB_WAIT: if (slab_valid) begin
                    if (slab_error) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else if (!slab_hit) state<=ASCEND;
                    else if (leaf) state<=TRI_PREPARE;
                    else state<=DESCEND;
                end
                DESCEND: begin
                    expected_parent<=current; current<=left; returning<=0;
                    state<=READ_SEND;
                end
                ASCEND: begin
                    if (current==0) state<=HOLD;
                    else if (parent>=scene_nodes || parent==current) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else begin
                        returned_child<=current; current<=parent;
                        returning<=1; state<=READ_SEND;
                    end
                end
                TRI_PREPARE: begin
                    if (record[352 +:8]>=scene_primitives) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else begin
                        triangle_command<=0;
                        triangle_command[0 +:32]<=command[0 +:32];
                        triangle_command[64 +:32]<=32'h910;
                        triangle_command[96 +:224]<=command[96 +:224];
                        triangle_command[320 +:288]<=vertices;
                        triangle_command[608 +:64]<=t_min;
                        triangle_command[672 +:64]<=t_max;
                        state<=TRI_SEND;
                    end
                end
                TRI_SEND: if (tri_ready) begin
                    record[352 +:8]<=record[352 +:8]+8'd1; state<=TRI_WAIT;
                end
                TRI_WAIT: if (tri_rsp_valid) begin
                    if (tri_record[64 +:32]!=0 ||
                        tri_record[0 +:32]!=32'h50000010 ||
                        tri_record[32 +:32]!=command[0 +:32] ||
                        tri_record[96 +:32]>1) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
                    end else if (!tri_record[96]) state<=ASCEND;
                    else begin
                        candidate<=tri_record;
                        if (!best) state<=REPLACE;
                        else state<=DISTANCE_SEND;
                    end
                end
                DISTANCE_SEND: if (alu_ready) state<=DISTANCE_WAIT;
                DISTANCE_WAIT: if (alu_valid) begin
                    if (alu_less) state<=REPLACE;
                    else if (alu_equal) state<=ID_SEND;
                    else state<=ASCEND;
                end
                ID_SEND: if (alu_ready) state<=ID_WAIT;
                ID_WAIT: if (alu_valid) begin
                    if (alu_less) state<=REPLACE;
                    else if (alu_equal) state<=SLOT_SEND;
                    else state<=ASCEND;
                end
                SLOT_SEND: if (alu_ready) state<=SLOT_WAIT;
                SLOT_WAIT: if (alu_valid) begin
                    if (alu_less) state<=REPLACE;
                    else state<=ASCEND;
                end
                REPLACE: begin
                    record[96 +:160]<=candidate[96 +:160];
                    record[256 +:32]<=primitive_id; record[288 +:32]<=slot;
                    best<=1; state<=ASCEND;
                end
                HOLD: if (m_ready) state<=IDLE;
                default: begin
                    record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
`ifndef SYNTHESIS
                    $fatal(1,"g5_ray_query: invalid control state");
`endif
                end
            endcase
        end
    end endgenerate
endmodule
