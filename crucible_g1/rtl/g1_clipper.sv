module g1_clipper (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [383:0] s_vertices,
    output wire m_valid,
    input wire m_ready,
    output wire [127:0] m_vertex,
    output wire done_valid,
    input wire done_ready,
    output wire [8:0] done_count
);
    localparam IDLE=5'd0, PLANE_START=5'd1, READ_B=5'd2,
               DISTANCE=5'd3, CLASSIFY=5'd4, DIFFERENCE=5'd5,
               MULTIPLY=5'd6, DIV_SEND=5'd7, DIV_WAIT=5'd8,
               ADD_COMPONENT=5'd9, FIX_PLANE=5'd10, WRITE_I=5'd11,
               WRITE_B=5'd12, NEXT_EDGE=5'd13, PLANE_DONE=5'd14,
               OUTPUT_READ=5'd15, OUTPUT_HOLD=5'd16, DONE=5'd17,
               SEED=5'd18;
    reg [4:0] state;
    reg [127:0] bank0 [0:383];
    reg [127:0] bank1 [0:383];
    reg bank;
    reg [8:0] count,out_count,edge_index,output_index;
    reg [2:0] plane;
    reg [1:0] component;
    reg [1:0] seed_index;
    reg [383:0] initial_vertices;
    reg emit_b;
    reg [127:0] a,b,intersection,output_vertex;
    reg signed [32:0] fa,fb,delta,offset;
    reg signed [33:0] denominator;
    reg signed [65:0] numerator;
    wire signed [31:0] a_component = a[component*32 +:32];
    wire signed [31:0] b_component = b[component*32 +:32];
    wire signed [33:0] component_sum =
        $signed({{2{a_component[31]}},a_component})+
        $signed({offset[32],offset});
    wire div_ready,div_valid;
    wire signed [95:0] div_quotient;
    wire writing = state==WRITE_I || state==WRITE_B;
    wire [8:0] write_address = state==SEED ? {7'd0,seed_index} : out_count;
    wire [127:0] write_vertex = state==SEED ?
        initial_vertices[seed_index*128 +:128] :
        state==WRITE_I ? intersection : b;
    wire [8:0] read_address = state==PLANE_START ? count-9'd1 :
        state==READ_B ? edge_index : output_index;
    wire [127:0] read_vertex = bank ? bank1[read_address] : bank0[read_address];

    function automatic signed [32:0] distance;
        input [127:0] v;
        input [2:0] p;
        reg signed [32:0] x,y,z,w;
        begin
            x=$signed({v[31],v[31:0]});
            y=$signed({v[63],v[63:32]});
            z=$signed({v[95],v[95:64]});
            w=$signed({v[127],v[127:96]});
            case (p)
                3'd0: distance=w-33'sd1;
                3'd1: distance=x+w;
                3'd2: distance=w-x;
                3'd3: distance=y+w;
                3'd4: distance=w-y;
                3'd5: distance=z;
                3'd6: distance=w-z;
                default: distance=33'sd0;
            endcase
        end
    endfunction

    g1_divider divider (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==DIV_SEND),.s_ready(div_ready),
        .s_numerator({{30{numerator[65]}},numerator}),
        .s_denominator({{30{denominator[33]}},denominator}),
        .m_valid(div_valid),.m_ready(state==DIV_WAIT),
        .m_quotient(div_quotient),.m_remainder()
    );
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==OUTPUT_HOLD;
    assign m_vertex = output_vertex;
    assign done_valid = rst_n && state==DONE;
    assign done_count = count;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; bank<=0; count<=0; out_count<=0;
            edge_index<=0; output_index<=0; plane<=0; component<=0;
            seed_index<=0; initial_vertices<=0;
            emit_b<=0; a<=0; b<=0; intersection<=0; output_vertex<=0;
            fa<=0; fb<=0; delta<=0; offset<=0; denominator<=0; numerator<=0;
        end else begin
            if (state==SEED || (writing && bank))
                bank0[write_address]<=write_vertex;
            if (writing && !bank)
                bank1[write_address]<=write_vertex;
            case (state)
                IDLE: if (s_valid) begin
                    initial_vertices<=s_vertices;
                    seed_index<=0;
                    bank<=0; count<=9'd3; plane<=0;
                    state<=SEED;
                end
                SEED: begin
                    if (seed_index==2'd2) state<=PLANE_START;
                    else seed_index<=seed_index+2'd1;
                end
                PLANE_START: begin
                    out_count<=0;
                    edge_index<=0;
                    if (count==0) state<=PLANE_DONE;
                    else begin
                        a<=read_vertex;
                        state<=READ_B;
                    end
                end
                READ_B: begin
                    b<=read_vertex;
                    state<=DISTANCE;
                end
                DISTANCE: begin
                    fa<=distance(a,plane);
                    fb<=distance(b,plane);
                    state<=CLASSIFY;
                end
                CLASSIFY: begin
                    if (!fa[32] && !fb[32]) state<=WRITE_B;
                    else if (fa[32] && fb[32]) state<=NEXT_EDGE;
                    else begin
                        emit_b<=fa[32] && !fb[32];
                        component<=0;
                        state<=DIFFERENCE;
                    end
                end
                DIFFERENCE: begin
                    delta<=$signed({b_component[31],b_component})-
                           $signed({a_component[31],a_component});
                    denominator<=$signed({fa[32],fa})-$signed({fb[32],fb});
                    state<=MULTIPLY;
                end
                MULTIPLY: begin
                    numerator<=delta*fa;
                    state<=DIV_SEND;
                end
                DIV_SEND: if (div_ready) state<=DIV_WAIT;
                DIV_WAIT: if (div_valid) begin
                    offset<=div_quotient[32:0];
                    state<=ADD_COMPONENT;
                end
                ADD_COMPONENT: begin
                    intersection[component*32 +:32]<=component_sum[31:0];
                    if (component==2'd3) state<=FIX_PLANE;
                    else begin
                        component<=component+2'd1;
                        state<=DIFFERENCE;
                    end
                end
                FIX_PLANE: begin
                    case (plane)
                        3'd0: intersection[127:96]<=32'sd1;
                        3'd1: intersection[31:0]<= -$signed(intersection[127:96]);
                        3'd2: intersection[31:0]<=intersection[127:96];
                        3'd3: intersection[63:32]<= -$signed(intersection[127:96]);
                        3'd4: intersection[63:32]<=intersection[127:96];
                        3'd5: intersection[95:64]<=32'sd0;
                        3'd6: intersection[95:64]<=intersection[127:96];
                        default: intersection<=intersection;
                    endcase
                    state<=WRITE_I;
                end
                WRITE_I: begin
                    out_count<=out_count+9'd1;
                    if (emit_b) state<=WRITE_B;
                    else state<=NEXT_EDGE;
                end
                WRITE_B: begin
                    out_count<=out_count+9'd1;
                    state<=NEXT_EDGE;
                end
                NEXT_EDGE: begin
                    a<=b;
                    if (edge_index==count-9'd1) state<=PLANE_DONE;
                    else begin
                        edge_index<=edge_index+9'd1;
                        state<=READ_B;
                    end
                end
                PLANE_DONE: begin
                    count<=out_count;
                    bank<=!bank;
                    if (plane==3'd6) begin
                        output_index<=0;
                        if (out_count==0) state<=DONE;
                        else state<=OUTPUT_READ;
                    end else begin
                        plane<=plane+3'd1;
                        state<=PLANE_START;
                    end
                end
                OUTPUT_READ: begin
                    output_vertex<=read_vertex;
                    state<=OUTPUT_HOLD;
                end
                OUTPUT_HOLD: if (m_ready) begin
                    if (output_index==count-9'd1) state<=DONE;
                    else begin
                        output_index<=output_index+9'd1;
                        state<=OUTPUT_READ;
                    end
                end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
