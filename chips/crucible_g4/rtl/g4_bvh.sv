module g4_bvh #(
    parameter integer MAX_NODES=64, STACK_DEPTH=16
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [991:0] s_command,
    output wire m_valid,
    input wire m_ready,
    output wire [511:0] m_record,
    output wire m_terminal
);
    localparam LEGAL=MAX_NODES>=1 && MAX_NODES<=256 &&
        STACK_DEPTH>=1 && STACK_DEPTH<=64;
    localparam integer NODES=LEGAL ? MAX_NODES : 1;
    localparam integer DEPTH=LEGAL ? STACK_DEPTH : 1;
    localparam IDLE=0, VALIDATE=1, WRITE=2, READ=3, CHECK=4,
               SLAB_SEND=5, SLAB_WAIT=6, LEAF=7, NEXT=8,
               POP=9, REPORT=10, HOLD=11;
    reg [3:0] state;
    reg [991:0] command;
    reg [NODES-1:0] initialized, visited;
    (* ramstyle="M20K", nomem2reg *) reg [319:0] nodes [0:NODES-1];
    reg [319:0] node_q;
    (* nomem2reg *) reg [8:0] stack [0:DEPTH-1];
    reg [8:0] stack_q, current;
    reg [6:0] occupancy, maximum;
    reg [31:0] status, tested, primitive_id, leaf_slot;
    reg any_hit, found, is_write;
    reg signed [63:0] best, t_min, t_max, candidate;
    reg [511:0] record;
    wire [31:0] opcode=command[64 +:32];
    wire [31:0] slot=command[96 +:32];
    wire signed [31:0] min_x=command[256 +:32], min_y=command[288 +:32],
        min_z=command[320 +:32], max_x=command[352 +:32],
        max_y=command[384 +:32], max_z=command[416 +:32];
    wire write_valid_fields=command[63:32]==0 && command[991:448]==0 &&
        command[159:129]==0 && slot<MAX_NODES &&
        min_x<=max_x && min_y<=max_y && min_z<=max_z &&
        (command[128] ? command[223:160]==0 :
         command[255:224]==0 && command[191:160]<MAX_NODES &&
         command[223:192]<MAX_NODES);
    wire signed [63:0] request_min=command[352 +:64];
    wire signed [63:0] request_max=command[416 +:64];
    wire query_valid_fields=command[63:32]==0 && command[991:480]==0 &&
        command[159:129]==0 && (slot<MAX_NODES || slot==32'hffffffff) &&
        request_min>=0 && request_min<=request_max;
    wire slab_ready, slab_valid, slab_hit;
    wire signed [63:0] slab_entry, slab_exit;
    wire signed [63:0] clipped_max=found && best<t_max ? best : t_max;
    g4_slab slab (
        .clk(clk),.rst_n(rst_n),.s_valid(LEGAL && state==SLAB_SEND),
        .s_ready(slab_ready),.s_origin(command[160 +:96]),
        .s_direction(command[256 +:96]),.s_bounds(node_q[128 +:192]),
        .s_t_min(t_min),.s_t_max(clipped_max),.m_valid(slab_valid),
        .m_ready(state==SLAB_WAIT),.m_hit(slab_hit),
        .m_t_enter(slab_entry),.m_t_exit(slab_exit)
    );
    initial if (!LEGAL) $fatal(1,"PARAMETER ERROR: g4_bvh capacity");
    assign s_ready=rst_n && LEGAL && state==IDLE;
    assign m_valid=rst_n && LEGAL && state==HOLD;
    assign m_record=m_valid ? record : 512'd0;
    assign m_terminal=m_valid;
    always @(posedge clk) begin
        if (rst_n && LEGAL) begin
            if (state==WRITE) nodes[slot[8:0]]<=command[128 +:320];
            if (state==READ) node_q<=nodes[current];
            if (state==SLAB_WAIT && slab_valid && slab_hit && !node_q[0] &&
                occupancy<STACK_DEPTH)
                stack[occupancy]<=node_q[64 +:9];
            if (state==NEXT && occupancy!=0) stack_q<=stack[occupancy-7'd1];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; command<=0; initialized<=0; visited<=0;
            current<=0; occupancy<=0; maximum<=0; status<=0; tested<=0;
            primitive_id<=32'hffffffff; leaf_slot<=32'hffffffff;
            any_hit<=0; found<=0; is_write<=0;
            best<=0; t_min<=0; t_max<=0; candidate<=0; record<=0;
        end else if (LEGAL) begin
            case (state)
                IDLE: if (s_valid) begin
                    command<=s_command; status<=0; tested<=0; maximum<=0;
                    occupancy<=0; found<=0; visited<=0;
                    primitive_id<=32'hffffffff; leaf_slot<=32'hffffffff;
                    best<=0; state<=VALIDATE;
                end
                VALIDATE: begin
                    is_write<=opcode==32'h800;
                    if (opcode==32'h800) begin
                        if (write_valid_fields) state<=WRITE;
                        else begin status<=1; state<=REPORT; end
                    end else if (opcode==32'h801 && query_valid_fields) begin
                        t_min<=request_min; t_max<=request_max;
                        any_hit<=command[128]; current<=slot[8:0];
                        if (slot==32'hffffffff) state<=REPORT;
                        else state<=READ;
                    end else begin status<=1; state<=REPORT; end
                end
                WRITE: begin initialized[slot[8:0]]<=1; state<=REPORT; end
                READ: state<=CHECK;
                CHECK: begin
                    if (current>=MAX_NODES) begin status<=4; state<=REPORT; end
                    else if (visited[current]) begin status<=4; state<=REPORT; end
                    else if (!initialized[current]) begin status<=2; state<=REPORT; end
                    else begin visited[current]<=1; state<=SLAB_SEND; end
                end
                SLAB_SEND: if (slab_ready) begin
                    tested<=tested+32'd1; state<=SLAB_WAIT;
                end
                SLAB_WAIT: if (slab_valid) begin
                    if (!slab_hit) state<=NEXT;
                    else if (node_q[0]) begin candidate<=slab_entry; state<=LEAF; end
                    else if (occupancy==STACK_DEPTH) begin
                        status<=3; state<=REPORT;
                    end else begin
                        occupancy<=occupancy+7'd1;
                        if (occupancy+7'd1>maximum) maximum<=occupancy+7'd1;
                        current<=node_q[32 +:9]; state<=READ;
                    end
                end
                LEAF: begin
                    if (!found || candidate<best ||
                        (candidate==best && (node_q[96 +:32]<primitive_id ||
                         (node_q[96 +:32]==primitive_id && {23'd0,current}<leaf_slot)))) begin
                        found<=1; best<=candidate;
                        primitive_id<=node_q[96 +:32]; leaf_slot<={23'd0,current};
                    end
                    if (any_hit) state<=REPORT;
                    else state<=NEXT;
                end
                NEXT: begin
                    if (occupancy==0) state<=REPORT;
                    else begin occupancy<=occupancy-7'd1; state<=POP; end
                end
                POP: begin current<=stack_q; state<=READ; end
                REPORT: begin
                    record<=0;
                    record[0 +:32]<=is_write ? 32'h40000000 : 32'h40000001;
                    record[32 +:32]<=command[0 +:32];
                    record[64 +:32]<=status;
                    if (is_write) begin
                        record[96 +:32]<=opcode; record[128 +:32]<=slot;
                    end else begin
                        record[96 +:32]<=status==0 && found ? 32'd1 : 32'd0;
                        record[128 +:32]<=status==0 && found ? primitive_id : 32'hffffffff;
                        record[160 +:32]<=status==0 && found ? leaf_slot : 32'hffffffff;
                        record[192 +:64]<=status==0 && found ? best : 64'd0;
                        record[256 +:32]<=tested;
                        record[288 +:32]<={25'd0,maximum};
                    end
                    state<=HOLD;
                end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
