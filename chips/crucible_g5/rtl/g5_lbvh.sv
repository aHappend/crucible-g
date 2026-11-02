module g5_lbvh #(
    parameter integer MAX_PRIMITIVES=64
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [991:0] s_command,
    output wire m_valid,
    input wire m_ready,
    output wire [511:0] m_record,
    output wire m_terminal,
    output wire tree_valid,
    output wire [31:0] tree_count, tree_nodes,
    input wire rd_valid,
    output wire rd_ready,
    input wire [31:0] rd_index,
    output wire rd_rsp_valid,
    input wire rd_rsp_ready,
    output wire [511:0] rd_node,
    output wire [287:0] rd_vertices,
    output wire [31:0] rd_parent
);
    localparam LEGAL=MAX_PRIMITIVES>=1 && MAX_PRIMITIVES<=128;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_lbvh MAX_PRIMITIVES");
        assign s_ready=0; assign m_valid=0; assign m_record=0;
        assign m_terminal=0; assign tree_valid=0; assign tree_count=0;
        assign tree_nodes=0; assign rd_ready=0; assign rd_rsp_valid=0;
        assign rd_node=0; assign rd_vertices=0; assign rd_parent=0;
    end else begin: implementation
        localparam CAPACITY=2*MAX_PRIMITIVES-1;
        localparam IDLE=0, WRITE_COMPARE=1, WRITE_SELECT=2,
            MID_SEND=3, MID_WAIT=4, MORTON_SEND=5, MORTON_WAIT=6,
            PRIMITIVE_STORE=7, PAD=8, HOLD=9, BUILD_PREFIX=10,
            LOAD_REQUEST=11, LOAD_CAPTURE=12,
            COUNT_REQUEST=13, COUNT_CAPTURE=14,
            SCATTER_REQUEST=15, SCATTER_CAPTURE=16, SCATTER_STORE=17,
            SORT_PAD=18, NODE_START=19, KEY_LO_REQUEST=20,
            KEY_LO_CAPTURE=21, KEY_HI_REQUEST=22, KEY_HI_CAPTURE=23,
            FIND_BIT=24, SEARCH_REQUEST=25, SEARCH_CAPTURE=26,
            SEARCH_DECIDE=27, INTERNAL_PREPARE=28, NODE_STORE=29,
            LEFT_PUSH=30, RIGHT_PUSH=31, LEAF_REQUEST=32,
            LEAF_CAPTURE=33, PRIM_REQUEST=34, PRIM_CAPTURE=35,
            POP=36, UNION_LEFT_REQUEST=37, UNION_LEFT_CAPTURE=38,
            UNION_RIGHT_REQUEST=39, UNION_RIGHT_CAPTURE=40,
            UNION_COMPARE=41, UNION_SELECT=42,
            EMIT_REQUEST=43, EMIT_CAPTURE=44, RECORD_GAP=45,
            NODE_READ_REQUEST=46, NODE_READ_CAPTURE=47;
        reg [5:0] state;
        reg [991:0] command;
        reg [511:0] record, node_work, left_node, right_node, root_record;
        reg [287:0] vertex_work;
        reg [31:0] parent_work;
        reg terminal, completed;
        reg [MAX_PRIMITIVES-1:0] initialized;
        reg [7:0] count, completed_count, scan, zero_count, zero_pos, one_pos;
        reg [8:0] completed_nodes, node_count, emit_index;
        reg [31:0] age, deadline;
        reg [31:0] latency_product;
        reg [15:0] deadline_low;
        reg deadline_carry;
        wire [16:0] deadline_sum={1'b0,latency_product[15:0]}+17'd543;
        reg building;
        reg [1:0] vertex_number;
        reg signed [31:0] minimum [0:2];
        reg signed [31:0] maximum [0:2];
        reg [2:0] min_high_less, min_high_equal, min_low_less;
        reg [2:0] max_high_greater, max_high_equal, max_low_greater;
        wire [95:0] candidate=command[(5+3*vertex_number)*32 +:96];
        reg [29:0] xyz;
        wire morton_ready, morton_valid;
        wire [29:0] morton_code;
        reg [29:0] code;
        wire [2:0] midpoint_ready, midpoint_valid;
        wire [47:0] midpoint [0:2];
        wire [2:0] midpoint_less, midpoint_equal, midpoint_carry;
        reg [5:0] radix_bit;
        reg sort_bank;
        reg [15:0] sort_clock, sort_period;
        reg [37:0] scatter_key, key_lo, key_hi, key_mid;
        reg [7:0] scatter_index, search_low, search_high, search_mid;
        reg [5:0] differing_bit;
        reg [5:0] sp;
        reg [7:0] frame_lo [0:38], frame_hi [0:38], frame_split [0:38];
        reg [8:0] frame_id [0:38];
        reg [31:0] frame_parent [0:38];
        reg [1:0] frame_phase [0:38];
        reg store_internal;
        reg [7:0] leaf_slot;
        reg [8:0] node_address;
        reg [7:0] primitive_address, sort_address;
        reg primitive_we, node_we, sort_a_we, sort_b_we;
        reg [541:0] primitive_data;
        reg [831:0] node_data;
        reg [37:0] sort_data;
        (* ramstyle = "M20K", nomem2reg *) reg [541:0] primitives [0:MAX_PRIMITIVES-1];
        (* ramstyle = "M20K", nomem2reg *) reg [831:0] nodes [0:CAPACITY-1];
        (* nomem2reg *) reg [37:0] sort_a [0:MAX_PRIMITIVES-1];
        (* nomem2reg *) reg [37:0] sort_b [0:MAX_PRIMITIVES-1];
        reg [541:0] primitive_q;
        reg [831:0] node_q, external_q;
        reg [37:0] sort_a_q, sort_b_q;
        wire [37:0] sorted_q=sort_bank ? sort_b_q : sort_a_q;
        reg [1:0] read_state;
        reg [31:0] read_index;
        reg read_invalid;
        reg [831:0] read_result;
        wire [31:0] opcode=s_command[64 +:32];
        wire [31:0] argument=s_command[96 +:32];
        wire common_bad=s_command[32 +:32]!=0;
        wire write_bad=common_bad || (|s_command[991:448]);
        wire short_bad=common_bad || (|s_command[991:128]);
        wire [8:0] left_id=frame_id[sp]+9'd1;
        wire [8:0] right_id=frame_id[sp]+
            {(frame_split[sp]-frame_lo[sp]+8'd1),1'b0};
        wire min_choose [0:2], max_choose [0:2];
        integer i;
        genvar axis;
        for (axis=0; axis<3; axis=axis+1) begin: midpoint_axes
            assign min_choose[axis]=min_high_less[axis] ||
                (min_high_equal[axis] && min_low_less[axis]);
            assign max_choose[axis]=max_high_greater[axis] ||
                (max_high_equal[axis] && max_low_greater[axis]);
            g5_limb_alu #(.WIDTH(48)) midpoint_adder (
                .clk(clk),.rst_n(rst_n),.s_valid(state==MID_SEND),
                .s_ready(midpoint_ready[axis]),
                .s_a({{16{minimum[axis][31]}},minimum[axis]}),
                .s_b({{16{maximum[axis][31]}},maximum[axis]}),
                .s_subtract(1'b0),.m_valid(midpoint_valid[axis]),
                .m_ready(state==MID_WAIT),.m_result(midpoint[axis]),
                .m_less(midpoint_less[axis]),.m_equal(midpoint_equal[axis]),
                .m_carry(midpoint_carry[axis])
            );
        end
        g5_morton morton (
            .clk(clk),.rst_n(rst_n),.s_valid(state==MORTON_SEND),
            .s_ready(morton_ready),.s_xyz(xyz),.m_valid(morton_valid),
            .m_ready(state==MORTON_WAIT),.m_code(morton_code)
        );
        assign s_ready=rst_n && state==IDLE && read_state==0;
        assign m_valid=rst_n && state==HOLD;
        assign m_record=m_valid ? record : 512'd0;
        assign m_terminal=m_valid && terminal;
        assign tree_valid=rst_n && completed;
        assign tree_count=tree_valid ? {24'd0,completed_count} : 32'd0;
        assign tree_nodes=tree_valid ? {23'd0,completed_nodes} : 32'd0;
        assign rd_ready=rst_n && state==IDLE && read_state==0 && !s_valid;
        assign rd_rsp_valid=rst_n && read_state==3;
        assign rd_node=rd_rsp_valid ? read_result[511:0] : 512'd0;
        assign rd_vertices=rd_rsp_valid ? read_result[799:512] : 288'd0;
        assign rd_parent=rd_rsp_valid ? read_result[831:800] : 32'd0;

        always @* begin
            primitive_address=scan; sort_address=scan;
            node_address=frame_id[sp];
            primitive_we=0; node_we=0; sort_a_we=0; sort_b_we=0;
            primitive_data=0; node_data=0; sort_data=0;
            case (state)
                PRIMITIVE_STORE: begin
                    primitive_address=command[96 +:8]; primitive_we=1;
                    primitive_data={command[128 +:32],code,
                        maximum[2],maximum[1],maximum[0],
                        minimum[2],minimum[1],minimum[0],command[160 +:288]};
                end
                LOAD_CAPTURE: begin
                    sort_a_we=initialized[scan];
                    sort_data={primitive_q[509:480],scan};
                end
                SCATTER_STORE: begin
                    sort_address=scatter_index; sort_data=scatter_key;
                    sort_a_we=sort_bank; sort_b_we=!sort_bank;
                end
                KEY_LO_REQUEST: sort_address=frame_lo[sp];
                KEY_HI_REQUEST: sort_address=frame_hi[sp];
                SEARCH_REQUEST: sort_address=search_mid;
                LEAF_REQUEST: sort_address=frame_lo[sp];
                PRIM_REQUEST: primitive_address=leaf_slot;
                NODE_STORE: begin
                    node_we=1; node_data={parent_work,vertex_work,node_work};
                end
                UNION_LEFT_REQUEST: node_address=left_id;
                UNION_RIGHT_REQUEST: node_address=right_id;
                EMIT_REQUEST: node_address=emit_index;
                NODE_READ_REQUEST: node_address=command[96 +:9];
                default: begin end
            endcase
        end
        always @(posedge clk) begin
            if (rst_n && primitive_we) primitives[primitive_address]<=primitive_data;
            primitive_q<=primitives[primitive_address];
            if (rst_n && node_we) nodes[node_address]<=node_data;
            node_q<=nodes[node_address];
            if (rst_n && sort_a_we) sort_a[sort_address]<=sort_data;
            if (rst_n && sort_b_we) sort_b[sort_address]<=sort_data;
            sort_a_q<=sort_a[sort_address]; sort_b_q<=sort_b[sort_address];
            external_q<=nodes[read_index<CAPACITY ? read_index : 32'd0];
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                read_state<=0; read_index<=0; read_invalid<=0; read_result<=0;
            end else case (read_state)
                0: if (rd_valid && rd_ready) begin
                    read_index<=rd_index;
                    read_invalid<=!completed || rd_index>=completed_nodes;
                    read_state<=1;
                end
                1: read_state<=2;
                2: begin
                    if (read_invalid) begin
                        read_result<=0;
                        read_result[64 +:32]<=32'd1;
                    end else read_result<=external_q;
                    read_state<=3;
                end
                3: if (rd_rsp_ready) read_state<=0;
            endcase
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; command<=0; record<=0; node_work<=0;
                left_node<=0; right_node<=0; root_record<=0; vertex_work<=0; parent_work<=0;
                terminal<=0; completed<=0; initialized<=0; count<=0;
                completed_count<=0; completed_nodes<=0; node_count<=0;
                scan<=0; zero_count<=0; zero_pos<=0; one_pos<=0;
                emit_index<=0; age<=0; deadline<=0; latency_product<=0;
                deadline_low<=0; deadline_carry<=0; building<=0;
                vertex_number<=0; min_high_less<=0; min_high_equal<=0;
                min_low_less<=0; max_high_greater<=0; max_high_equal<=0;
                max_low_greater<=0; xyz<=0; code<=0; radix_bit<=0;
                sort_bank<=0; sort_clock<=0; sort_period<=0;
                scatter_key<=0; key_lo<=0; key_hi<=0; key_mid<=0;
                scatter_index<=0; search_low<=0; search_high<=0;
                search_mid<=0; differing_bit<=0; sp<=0;
                store_internal<=0; leaf_slot<=0;
                for (i=0; i<3; i=i+1) begin minimum[i]<=0; maximum[i]<=0; end
            end else begin
                if (state!=IDLE && state!=HOLD && state!=RECORD_GAP &&
                    state!=EMIT_REQUEST && state!=EMIT_CAPTURE) begin
                    age[15:0]<=age[15:0]+16'd1;
                    if (age[15:0]==16'hffff) age[31:16]<=age[31:16]+16'd1;
                end
                if (building && age==0) begin
                    deadline_low<=deadline_sum[15:0];
                    deadline_carry<=deadline_sum[16];
                end
                if (building && age==1)
                    deadline<={latency_product[31:16]+{15'd0,deadline_carry},
                        deadline_low};
                if (state>=LOAD_REQUEST && state<=SORT_PAD)
                    sort_clock<=sort_clock+16'd1;
                case (state)
                    IDLE: if (s_valid && s_ready) begin
                        command<=s_command; record<=0; age<=0;
                        terminal<=1; building<=0; deadline<=32'd63;
                        record[0 +:32]<=32'h50000000;
                        record[32 +:32]<=s_command[0 +:32];
                        record[96 +:32]<=opcode;
                        if (opcode==32'h900) begin
                            if (write_bad) begin
                                record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                            end else if (argument>=MAX_PRIMITIVES) begin
                                record[64 +:32]<=3; record[511:96]<=0; state<=PAD;
                            end else begin
                                for (i=0; i<3; i=i+1) begin
                                    minimum[i]<=s_command[(5+i)*32 +:32];
                                    maximum[i]<=s_command[(5+i)*32 +:32];
                                end
                                vertex_number<=1; state<=WRITE_COMPARE;
                            end
                        end else if (opcode==32'h901) begin
                            if (short_bad) begin
                                record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                            end else if (argument>MAX_PRIMITIVES) begin
                                record[64 +:32]<=3; record[511:96]<=0; state<=PAD;
                            end else if (argument==0) begin
                                completed<=1; completed_count<=0; completed_nodes<=0;
                                record[192 +:32]<=32'hffffffff; state<=PAD;
                            end else begin
                                count<=argument[7:0];
                                node_count<=({1'b0,argument[7:0]}<<1)-9'd1;
                                latency_product<={8'd0,argument[7:0]}*16'd560;
                                building<=1; scan<=0; radix_bit<=0;
                                sort_bank<=0; sort_clock<=0;
                                sort_period<=({8'd0,argument[7:0]}<<3)+16'd16;
                                state<=BUILD_PREFIX;
                            end
                        end else if (opcode==32'h902) begin
                            deadline<=3; record[0 +:32]<=32'h50000001;
                            record[511:96]<=0;
                            if (short_bad) begin record[64 +:32]<=1; state<=PAD; end
                            else if (!completed) begin record[64 +:32]<=2; state<=PAD; end
                            else if (argument>=completed_nodes) begin
                                record[64 +:32]<=1; state<=PAD;
                            end else state<=NODE_READ_REQUEST;
                        end else begin
                            record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                        end
                    end
                    WRITE_COMPARE: begin
                        for (i=0; i<3; i=i+1) begin
                            min_high_less[i]<=$signed(candidate[i*32+16 +:16])<
                                $signed(minimum[i][31:16]);
                            min_high_equal[i]<=candidate[i*32+16 +:16]==minimum[i][31:16];
                            min_low_less[i]<=candidate[i*32 +:16]<minimum[i][15:0];
                            max_high_greater[i]<=$signed(candidate[i*32+16 +:16])>
                                $signed(maximum[i][31:16]);
                            max_high_equal[i]<=candidate[i*32+16 +:16]==maximum[i][31:16];
                            max_low_greater[i]<=candidate[i*32 +:16]>maximum[i][15:0];
                        end
                        state<=WRITE_SELECT;
                    end
                    WRITE_SELECT: begin
                        for (i=0; i<3; i=i+1) begin
                            if (min_choose[i]) minimum[i]<=candidate[i*32 +:32];
                            if (max_choose[i]) maximum[i]<=candidate[i*32 +:32];
                        end
                        if (vertex_number==2) state<=MID_SEND;
                        else begin vertex_number<=2; state<=WRITE_COMPARE; end
                    end
                    MID_SEND: if (&midpoint_ready) state<=MID_WAIT;
                    MID_WAIT: if (&midpoint_valid) begin
                        for (i=0; i<3; i=i+1)
                            xyz[i*10 +:10]<={~midpoint[i][32],midpoint[i][31:23]};
                        state<=MORTON_SEND;
                    end
                    MORTON_SEND: if (morton_ready) state<=MORTON_WAIT;
                    MORTON_WAIT: if (morton_valid) begin code<=morton_code; state<=PRIMITIVE_STORE; end
                    PRIMITIVE_STORE: begin
                        initialized[command[96 +:8]]<=1; completed<=0;
                        record[128 +:32]<=1; state<=PAD;
                    end
                    BUILD_PREFIX: if (age==63) begin sort_clock<=0; state<=LOAD_REQUEST; end
                    LOAD_REQUEST: state<=LOAD_CAPTURE;
                    LOAD_CAPTURE: begin
                        if (!initialized[scan]) begin
                            record[64 +:32]<=2; record[511:96]<=0;
                            building<=0; state<=PAD;
                        end else if (scan==count-1) begin
                            scan<=0; zero_count<=0; state<=COUNT_REQUEST;
                        end else begin scan<=scan+8'd1; state<=LOAD_REQUEST; end
                    end
                    COUNT_REQUEST: state<=COUNT_CAPTURE;
                    COUNT_CAPTURE: begin
                        if (!sorted_q[radix_bit]) zero_count<=zero_count+8'd1;
                        if (scan==count-1) begin
                            scan<=0; zero_pos<=0;
                            one_pos<=zero_count+{7'd0,!sorted_q[radix_bit]};
                            state<=SCATTER_REQUEST;
                        end else begin scan<=scan+8'd1; state<=COUNT_REQUEST; end
                    end
                    SCATTER_REQUEST: state<=SCATTER_CAPTURE;
                    SCATTER_CAPTURE: begin
                        scatter_key<=sorted_q;
                        if (sorted_q[radix_bit]) begin
                            scatter_index<=one_pos; one_pos<=one_pos+8'd1;
                        end else begin scatter_index<=zero_pos; zero_pos<=zero_pos+8'd1; end
                        state<=SCATTER_STORE;
                    end
                    SCATTER_STORE: begin
                        if (scan==count-1) state<=SORT_PAD;
                        else begin scan<=scan+8'd1; state<=SCATTER_REQUEST; end
                    end
                    SORT_PAD: if (sort_clock==sort_period-1) begin
                        sort_bank<=!sort_bank; sort_clock<=0; scan<=0; zero_count<=0;
                        if (radix_bit==37) begin
                            sp<=0; frame_lo[0]<=0; frame_hi[0]<=count-8'd1;
                            frame_id[0]<=0; frame_parent[0]<=32'hffffffff;
                            frame_phase[0]<=0; completed<=0; state<=NODE_START;
                        end else begin radix_bit<=radix_bit+6'd1; state<=COUNT_REQUEST; end
                    end
                    NODE_START: begin
                        node_work<=0; vertex_work<=0; parent_work<=frame_parent[sp];
                        node_work[0 +:32]<=32'h50000001;
                        node_work[32 +:32]<=command[0 +:32];
                        node_work[96 +:32]<={23'd0,frame_id[sp]};
                        if (frame_lo[sp]==frame_hi[sp]) state<=LEAF_REQUEST;
                        else state<=KEY_LO_REQUEST;
                    end
                    KEY_LO_REQUEST: state<=KEY_LO_CAPTURE;
                    KEY_LO_CAPTURE: begin key_lo<=sorted_q; state<=KEY_HI_REQUEST; end
                    KEY_HI_REQUEST: state<=KEY_HI_CAPTURE;
                    KEY_HI_CAPTURE: begin key_hi<=sorted_q; differing_bit<=37; state<=FIND_BIT; end
                    FIND_BIT: begin
                        if (key_lo[differing_bit]!=key_hi[differing_bit]) begin
                            search_low<=frame_lo[sp]; search_high<=frame_hi[sp];
                            search_mid<=({1'b0,frame_lo[sp]}+{1'b0,frame_hi[sp]})>>1;
                            state<=SEARCH_REQUEST;
                        end else if (differing_bit==0) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else differing_bit<=differing_bit-6'd1;
                    end
                    SEARCH_REQUEST: state<=SEARCH_CAPTURE;
                    SEARCH_CAPTURE: begin key_mid<=sorted_q; state<=SEARCH_DECIDE; end
                    SEARCH_DECIDE: begin
                        if (search_high-search_low==1) begin
                            frame_split[sp]<=search_low; state<=INTERNAL_PREPARE;
                        end else if (key_mid[differing_bit]) begin
                            search_high<=search_mid;
                            search_mid<=({1'b0,search_low}+{1'b0,search_mid})>>1;
                            state<=SEARCH_REQUEST;
                        end else begin
                            search_low<=search_mid;
                            search_mid<=({1'b0,search_mid}+{1'b0,search_high})>>1;
                            state<=SEARCH_REQUEST;
                        end
                    end
                    INTERNAL_PREPARE: begin
                        node_work[160 +:32]<={23'd0,left_id};
                        node_work[192 +:32]<={23'd0,right_id};
                        node_work[224 +:32]<=32'hffffffff;
                        node_work[256 +:32]<=32'hffffffff;
                        store_internal<=1; state<=NODE_STORE;
                    end
                    LEAF_REQUEST: state<=LEAF_CAPTURE;
                    LEAF_CAPTURE: begin leaf_slot<=sorted_q[7:0]; state<=PRIM_REQUEST; end
                    PRIM_REQUEST: state<=PRIM_CAPTURE;
                    PRIM_CAPTURE: begin
                        vertex_work<=primitive_q[287:0];
                        node_work[128 +:32]<=1;
                        node_work[160 +:32]<=32'hffffffff;
                        node_work[192 +:32]<=32'hffffffff;
                        node_work[224 +:32]<=primitive_q[541:510];
                        node_work[256 +:32]<={24'd0,leaf_slot};
                        node_work[288 +:32]<={2'd0,primitive_q[509:480]};
                        node_work[320 +:192]<=primitive_q[479:288];
                        store_internal<=0; state<=NODE_STORE;
                    end
                    NODE_STORE: begin
                        if (frame_id[sp]==0) root_record<=node_work;
                        if (store_internal) state<=LEFT_PUSH;
                        else state<=POP;
                    end
                    LEFT_PUSH: begin
                        if (sp==38) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else begin
                            frame_phase[sp]<=1;
                            frame_lo[sp+1]<=frame_lo[sp]; frame_hi[sp+1]<=frame_split[sp];
                            frame_id[sp+1]<=left_id; frame_parent[sp+1]<={23'd0,frame_id[sp]};
                            frame_phase[sp+1]<=0; sp<=sp+6'd1; state<=NODE_START;
                        end
                    end
                    RIGHT_PUSH: begin
                        if (sp==38) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else begin
                            frame_phase[sp]<=2;
                            frame_lo[sp+1]<=frame_split[sp]+8'd1; frame_hi[sp+1]<=frame_hi[sp];
                            frame_id[sp+1]<=right_id; frame_parent[sp+1]<={23'd0,frame_id[sp]};
                            frame_phase[sp+1]<=0; sp<=sp+6'd1; state<=NODE_START;
                        end
                    end
                    POP: begin
                        if (sp==0) begin
                            record<=0; record[0 +:32]<=32'h50000000;
                            record[32 +:32]<=command[0 +:32]; record[96 +:32]<=32'h901;
                            record[128 +:32]<={24'd0,count};
                            record[160 +:32]<={23'd0,node_count};
                            state<=PAD;
                        end else begin
                            sp<=sp-6'd1;
                            if (frame_phase[sp-1]==1) state<=RIGHT_PUSH;
                            else state<=UNION_LEFT_REQUEST;
                        end
                    end
                    UNION_LEFT_REQUEST: state<=UNION_LEFT_CAPTURE;
                    UNION_LEFT_CAPTURE: begin left_node<=node_q[511:0]; state<=UNION_RIGHT_REQUEST; end
                    UNION_RIGHT_REQUEST: state<=UNION_RIGHT_CAPTURE;
                    UNION_RIGHT_CAPTURE: begin right_node<=node_q[511:0]; state<=UNION_COMPARE; end
                    UNION_COMPARE: begin
                        for (i=0; i<3; i=i+1) begin
                            min_high_less[i]<=$signed(left_node[336+i*32 +:16])<
                                $signed(right_node[336+i*32 +:16]);
                            min_high_equal[i]<=left_node[336+i*32 +:16]==right_node[336+i*32 +:16];
                            min_low_less[i]<=left_node[320+i*32 +:16]<right_node[320+i*32 +:16];
                            max_high_greater[i]<=$signed(left_node[432+i*32 +:16])>
                                $signed(right_node[432+i*32 +:16]);
                            max_high_equal[i]<=left_node[432+i*32 +:16]==right_node[432+i*32 +:16];
                            max_low_greater[i]<=left_node[416+i*32 +:16]>right_node[416+i*32 +:16];
                        end
                        state<=UNION_SELECT;
                    end
                    UNION_SELECT: begin
                        node_work<=0; vertex_work<=0; parent_work<=frame_parent[sp];
                        node_work[0 +:32]<=32'h50000001;
                        node_work[32 +:32]<=command[0 +:32];
                        node_work[96 +:32]<={23'd0,frame_id[sp]};
                        node_work[160 +:32]<={23'd0,left_id};
                        node_work[192 +:32]<={23'd0,right_id};
                        node_work[224 +:32]<=32'hffffffff;
                        node_work[256 +:32]<=32'hffffffff;
                        for (i=0; i<3; i=i+1) begin
                            node_work[320+i*32 +:32]<=min_choose[i] ?
                                left_node[320+i*32 +:32] : right_node[320+i*32 +:32];
                            node_work[416+i*32 +:32]<=max_choose[i] ?
                                left_node[416+i*32 +:32] : right_node[416+i*32 +:32];
                        end
                        store_internal<=0; state<=NODE_STORE;
                    end
                    NODE_READ_REQUEST: state<=NODE_READ_CAPTURE;
                    NODE_READ_CAPTURE: begin
                        record<=node_q[511:0]; record[32 +:32]<=command[0 +:32];
                        state<=PAD;
                    end
                    PAD: begin end
                    HOLD: if (m_ready) begin
                        if (terminal) state<=IDLE;
                        else state<=RECORD_GAP;
                    end
                    RECORD_GAP: begin
                        if (emit_index==node_count) begin
                            record<=0; record[0 +:32]<=32'h50000000;
                            record[32 +:32]<=command[0 +:32]; record[96 +:32]<=32'h901;
                            record[128 +:32]<={24'd0,count};
                            record[160 +:32]<={23'd0,node_count};
                            terminal<=1; state<=HOLD;
                        end else state<=EMIT_REQUEST;
                    end
                    EMIT_REQUEST: state<=EMIT_CAPTURE;
                    EMIT_CAPTURE: begin
                        record<=node_q[511:0]; terminal<=0;
                        emit_index<=emit_index+9'd1; state<=HOLD;
                    end
                    default: begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
`ifndef SYNTHESIS
                        $fatal(1,"g5_lbvh: invalid control state");
`endif
                    end
                endcase
                if (state!=IDLE && state!=HOLD && state!=RECORD_GAP &&
                    state!=EMIT_REQUEST && state!=EMIT_CAPTURE && age==deadline) begin
                    if (state!=PAD) begin
                        record[64 +:32]<=4; record[511:96]<=0; state<=HOLD;
`ifndef SYNTHESIS
                        $fatal(1,"g5_lbvh: fixed publication slot overrun");
`endif
                    end else if (building && record[64 +:32]==0) begin
                        completed<=1; completed_count<=count; completed_nodes<=node_count;
                        emit_index<=1; terminal<=0;
                        record<=root_record; state<=HOLD;
                    end else state<=HOLD;
                end
            end
        end
    end endgenerate
endmodule
