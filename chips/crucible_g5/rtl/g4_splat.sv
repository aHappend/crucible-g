module g4_splat #(
    parameter integer MAX_WIDTH=256, MAX_HEIGHT=256, MAX_SPLATS=64
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [991:0] s_command,
    output wire m_valid,
    input wire m_ready,
    output wire [511:0] m_record,
    output wire m_terminal
);
    localparam LEGAL=MAX_WIDTH>=1 && MAX_WIDTH<=256 &&
        MAX_HEIGHT>=1 && MAX_HEIGHT<=256 && MAX_SPLATS>=1 && MAX_SPLATS<=256;
    localparam integer CAPACITY=LEGAL ? MAX_SPLATS : 1;
    localparam IDLE=0, VALIDATE=1, DETERMINANT_PRODUCT=2,
               DETERMINANT_SUM=3, DETERMINANT_CHECK=4, WRITE=5,
               INITIALIZED_CHECK=6, SORT_CONFIGURE=7, KEY_READ=8,
               KEY_SEND=9, SORT_WAIT=10, START_PIXEL=11, CHECK_NEXT=12,
               INDEX_READ=13, SPLAT_READ=14, CONIC_SEND=15,
               CONIC_WAIT=16, SAMPLE_WAIT=17, FINISH_PIXEL=18,
               PIXEL_WAIT=19, PIXEL_HOLD=20, ADVANCE_PIXEL=21,
               ACK=22, DONE_RECORD=23, TERMINAL_HOLD=24;
    reg [4:0] state;
    reg [991:0] command;
    reg [CAPACITY-1:0] initialized;
    (* ramstyle="M20K", nomem2reg *) reg [192:0] scene [0:CAPACITY-1];
    (* ramstyle="M20K", nomem2reg *) reg [8:0] sorted [0:CAPACITY-1];
    reg [192:0] scene_q;
    reg [8:0] sorted_q, cursor, sorted_count, count, width, height, x, y;
    reg [8:0] evaluated;
    reg [31:0] status, pixels, evaluations, early_pixels;
    reg [511:0] record;
    reg signed [47:0] ac, bb;
    reg signed [48:0] determinant;
    wire [31:0] opcode=command[64 +:32];
    wire [31:0] slot=command[96 +:32];
    wire [15:0] request_width=command[32 +:16], request_height=command[48 +:16];
    wire signed [23:0] a=command[224 +:24], b=command[256 +:24],
        c=command[288 +:24];
    wire write_fields_valid=command[63:32]==0 && slot<MAX_SPLATS &&
        command[991:384]==0 && command[383:376]==0 &&
        command[351:320]<=32'd65536 &&
        command[191:184]=={8{command[183]}} &&
        command[223:216]=={8{command[215]}} &&
        command[255:248]=={8{command[247]}} &&
        command[287:280]=={8{command[279]}} &&
        command[319:312]=={8{command[311]}} && a>0 && c>0;
    wire render_fields_valid=request_width!=0 && request_width<=MAX_WIDTH &&
        request_height!=0 && request_height<=MAX_HEIGHT &&
        command[127:96]<=MAX_SPLATS && command[159:128]<=32'd65536 &&
        command[191:184]==0 && command[991:192]==0;
    wire sort_cfg_ready, sort_ready, sort_valid, sort_last, sort_done;
    wire [31:0] sort_key;
    wire [8:0] sort_index;
    g4_radix_sort #(.MAX_SPLATS(MAX_SPLATS)) sorter (
        .clk(clk),.rst_n(rst_n),.cfg_valid(LEGAL && state==SORT_CONFIGURE),
        .cfg_ready(sort_cfg_ready),.cfg_count(count),
        .s_valid(state==KEY_SEND),.s_ready(sort_ready),.s_key(scene_q[31:0]),
        .m_valid(sort_valid),.m_ready(state==SORT_WAIT),
        .m_key(sort_key),.m_index(sort_index),.m_last(sort_last),
        .done_valid(sort_done),.done_ready(state==SORT_WAIT)
    );
    wire conic_ready, conic_valid;
    wire [16:0] conic_alpha;
    wire compositor_start_ready, compositor_sample_ready, compositor_finish_ready;
    wire compositor_terminated, compositor_valid;
    wire [31:0] compositor_rgba;
    wire [16:0] compositor_t;
    g4_conic conic (
        .clk(clk),.rst_n(rst_n),.s_valid(LEGAL && state==CONIC_SEND),
        .s_ready(conic_ready),.s_pixel({y[7:0],x[7:0]}),
        .s_mean(scene_q[32 +:48]),.s_conic(scene_q[80 +:72]),
        .s_opacity(scene_q[152 +:17]),.m_valid(conic_valid),
        .m_ready(state==CONIC_WAIT && compositor_sample_ready),.m_alpha(conic_alpha)
    );
    g4_compositor compositor (
        .clk(clk),.rst_n(rst_n),.start_valid(LEGAL && state==START_PIXEL),
        .start_ready(compositor_start_ready),.start_background(command[160 +:24]),
        .start_epsilon(command[128 +:17]),
        .s_valid(state==CONIC_WAIT && conic_valid),
        .s_ready(compositor_sample_ready),.s_alpha(conic_alpha),
        .s_rgb(scene_q[169 +:24]),.finish_valid(state==FINISH_PIXEL),
        .finish_ready(compositor_finish_ready),.terminated(compositor_terminated),
        .m_valid(compositor_valid),.m_ready(state==PIXEL_WAIT),
        .m_rgba(compositor_rgba),.m_transmittance(compositor_t)
    );
    initial if (!LEGAL) $fatal(1,"PARAMETER ERROR: g4_splat dimensions or capacity");
    assign s_ready=rst_n && LEGAL && state==IDLE;
    assign m_valid=rst_n && LEGAL &&
        (state==PIXEL_HOLD || state==TERMINAL_HOLD);
    assign m_record=m_valid ? record : 512'd0;
    assign m_terminal=m_valid && state==TERMINAL_HOLD;
    always @(posedge clk) begin
        if (rst_n && LEGAL) begin
            if (state==WRITE)
                scene[slot[8:0]]<={command[352 +:24],command[320 +:17],
                    command[288 +:24],command[256 +:24],command[224 +:24],
                    command[192 +:24],command[160 +:24],command[128 +:32]};
            if (state==KEY_READ) scene_q<=scene[cursor];
            if (state==SORT_WAIT && sort_valid) sorted[sorted_count]<=sort_index;
            if (state==INDEX_READ) sorted_q<=sorted[evaluated];
            if (state==SPLAT_READ) scene_q<=scene[sorted_q];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; command<=0; initialized<=0;
            cursor<=0; sorted_count<=0; count<=0; width<=0; height<=0;
            x<=0; y<=0; evaluated<=0; status<=0; pixels<=0;
            evaluations<=0; early_pixels<=0; record<=0; ac<=0; bb<=0;
            determinant<=0;
        end else if (LEGAL) begin
            case (state)
                IDLE: if (s_valid) begin
                    command<=s_command; status<=0; pixels<=0;
                    evaluations<=0; early_pixels<=0; cursor<=0;
                    sorted_count<=0; x<=0; y<=0; evaluated<=0;
                    state<=VALIDATE;
                end
                VALIDATE: begin
                    if (opcode==32'h810) begin
                        if (write_fields_valid) state<=DETERMINANT_PRODUCT;
                        else begin status<=1; state<=ACK; end
                    end else if (opcode==32'h811) begin
                        count<=command[96 +:9]; width<=request_width[8:0];
                        height<=request_height[8:0];
                        if (!render_fields_valid) begin status<=1; state<=DONE_RECORD; end
                        else if (command[127:96]==0) state<=SORT_CONFIGURE;
                        else state<=INITIALIZED_CHECK;
                    end else begin status<=1; state<=ACK; end
                end
                DETERMINANT_PRODUCT: begin ac<=a*c; bb<=b*b; state<=DETERMINANT_SUM; end
                DETERMINANT_SUM: begin
                    determinant<=$signed({ac[47],ac})-$signed({bb[47],bb});
                    state<=DETERMINANT_CHECK;
                end
                DETERMINANT_CHECK: begin
                    if (determinant>0) state<=WRITE;
                    else begin status<=1; state<=ACK; end
                end
                WRITE: begin initialized[slot[8:0]]<=1; state<=ACK; end
                INITIALIZED_CHECK: begin
                    if (!initialized[cursor]) begin status<=2; state<=DONE_RECORD; end
                    else if (cursor+9'd1==count) begin cursor<=0; state<=SORT_CONFIGURE; end
                    else cursor<=cursor+9'd1;
                end
                SORT_CONFIGURE: if (sort_cfg_ready) begin
                    if (count==0) state<=SORT_WAIT;
                    else state<=KEY_READ;
                end
                KEY_READ: state<=KEY_SEND;
                KEY_SEND: if (sort_ready) begin
                    if (cursor+9'd1==count) state<=SORT_WAIT;
                    else begin cursor<=cursor+9'd1; state<=KEY_READ; end
                end
                SORT_WAIT: begin
                    if (sort_valid) sorted_count<=sorted_count+9'd1;
                    if (sort_done) state<=START_PIXEL;
                end
                START_PIXEL: if (compositor_start_ready) begin
                    evaluated<=0; state<=CHECK_NEXT;
                end
                CHECK_NEXT: begin
                    if (evaluated==count || compositor_terminated) state<=FINISH_PIXEL;
                    else state<=INDEX_READ;
                end
                INDEX_READ: state<=SPLAT_READ;
                SPLAT_READ: state<=CONIC_SEND;
                CONIC_SEND: if (conic_ready) state<=CONIC_WAIT;
                CONIC_WAIT: if (conic_valid && compositor_sample_ready) begin
                    evaluated<=evaluated+9'd1; state<=SAMPLE_WAIT;
                end
                SAMPLE_WAIT: if (compositor_finish_ready) state<=CHECK_NEXT;
                FINISH_PIXEL: if (compositor_finish_ready) state<=PIXEL_WAIT;
                PIXEL_WAIT: if (compositor_valid) begin
                    record<=0; record[0 +:32]<=32'h40000002;
                    record[32 +:32]<=command[0 +:32];
                    record[96 +:32]<={23'd0,x}; record[128 +:32]<={23'd0,y};
                    record[160 +:32]<=compositor_rgba;
                    record[192 +:32]<={15'd0,compositor_t};
                    record[224 +:32]<={23'd0,evaluated};
                    record[256 +:32]<={23'd0,count}; state<=PIXEL_HOLD;
                end
                PIXEL_HOLD: if (m_ready) state<=ADVANCE_PIXEL;
                ADVANCE_PIXEL: begin
                    pixels<=pixels+32'd1;
                    evaluations<=evaluations+{23'd0,evaluated};
                    if (evaluated<count) early_pixels<=early_pixels+32'd1;
                    if (x+9'd1==width) begin
                        x<=0;
                        if (y+9'd1==height) state<=DONE_RECORD;
                        else begin y<=y+9'd1; state<=START_PIXEL; end
                    end else begin x<=x+9'd1; state<=START_PIXEL; end
                end
                ACK: begin
                    record<=0; record[0 +:32]<=32'h40000000;
                    record[32 +:32]<=command[0 +:32]; record[64 +:32]<=status;
                    record[96 +:32]<=opcode; record[128 +:32]<=slot;
                    state<=TERMINAL_HOLD;
                end
                DONE_RECORD: begin
                    record<=0; record[0 +:32]<=32'h40000003;
                    record[32 +:32]<=command[0 +:32]; record[64 +:32]<=status;
                    record[96 +:32]<=pixels; record[128 +:32]<=command[96 +:32];
                    record[160 +:32]<=evaluations; record[192 +:32]<=early_pixels;
                    state<=TERMINAL_HOLD;
                end
                TERMINAL_HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
