module g2_setup (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [991:0] s_header,
    input wire [575:0] s_attributes,
    output wire m_valid,
    input wire m_ready,
    output wire [290:0] m_vertex,
    output wire done_valid,
    input wire done_ready,
    output wire [8:0] done_count
);
    localparam IDLE=0, TRANSFORM_SEND=1, TRANSFORM_WAIT=2, RUN=3, DONE=4;
    reg [2:0] state;
    reg [991:0] header;
    reg [575:0] attributes;
    reg clip_finished;
    reg [8:0] count,retired;
    wire transform_ready,transform_valid,clip_ready,clip_valid,clip_done;
    wire project_ready,project_valid;
    wire [383:0] transformed;
    wire [959:0] clip_input;
    wire [319:0] clip_vertex;
    wire [290:0] projected;
    wire [8:0] clip_count;
    genvar v;
    generate for (v=0;v<3;v=v+1) begin: pack_vertex
        assign clip_input[v*320 +:320] =
            {attributes[v*192 +:192],transformed[v*128 +:128]};
    end endgenerate
    g1_transform transform (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==TRANSFORM_SEND),.s_ready(transform_ready),
        .s_mode_2d(header[66]),.s_matrix(header[96 +:512]),
        .s_vertices(header[608 +:384]),
        .m_valid(transform_valid),.m_ready(state==TRANSFORM_WAIT && clip_ready),
        .m_vertices(transformed)
    );
    g2_clipper clipper (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==TRANSFORM_WAIT && transform_valid),.s_ready(clip_ready),
        .s_vertices(clip_input),
        .m_valid(clip_valid),.m_ready(state==RUN && project_ready),
        .m_vertex(clip_vertex),
        .done_valid(clip_done),.done_ready(state==RUN && !clip_finished),
        .done_count(clip_count)
    );
    g2_project project (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==RUN && clip_valid),.s_ready(project_ready),
        .s_vertex(clip_vertex),.s_width(header[32 +:9]),
        .s_height(header[48 +:9]),.s_depth24(header[64]),
        .m_valid(project_valid),.m_ready(state==RUN && m_ready),
        .m_vertex(projected)
    );
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==RUN && project_valid;
    assign m_vertex = m_valid ? projected : 291'd0;
    assign done_valid = rst_n && state==DONE;
    assign done_count = done_valid ? count : 9'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; header<=0; attributes<=0;
            clip_finished<=0; count<=0; retired<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    header<=s_header; attributes<=s_attributes;
                    clip_finished<=0; count<=0; retired<=0;
                    state<=TRANSFORM_SEND;
                end
                TRANSFORM_SEND: if (transform_ready) state<=TRANSFORM_WAIT;
                TRANSFORM_WAIT: if (transform_valid && clip_ready) state<=RUN;
                RUN: begin
                    if (m_valid && m_ready) retired<=retired+9'd1;
                    if (clip_done && !clip_finished) begin
                        count<=clip_count; clip_finished<=1;
                    end
                    if (clip_finished && retired==count) state<=DONE;
                end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
