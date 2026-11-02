module crucible_g2_top #(
    parameter integer MAX_WIDTH=256,
    parameter integer MAX_HEIGHT=256,
    parameter integer TILE_LOG2=3
) (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [31:0] s_data,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_data,
    output wire m_last
);
    localparam LEGAL_PARAMETERS = MAX_WIDTH>=1 && MAX_WIDTH<=256 &&
        MAX_HEIGHT>=1 && MAX_HEIGHT<=256 && TILE_LOG2>=0 && TILE_LOG2<=4;
    localparam BOOT=0, HEADER=1, ATTRIBUTES=2, LEGACY_SEND=3,
               LEGACY_WAIT=4, ENGINE_SEND=5, ENGINE_WAIT=6;
    reg [2:0] state;
    reg [5:0] word_index;
    reg [991:0] header;
    reg [575:0] attributes;
    reg is_g2,is_draw,invalid_dimensions;
    wire legacy_ready,legacy_valid,legacy_last;
    wire engine_ready,engine_valid,engine_last;
    wire [31:0] legacy_data,engine_data;
    wire draw_mode = s_data==32'd2 || s_data==32'd3 ||
        s_data==32'd6 || s_data==32'd7 ||
        s_data==32'd258 || s_data==32'd259 ||
        s_data==32'd262 || s_data==32'd263;
    wire [31:0] replay_data = word_index==2 && invalid_dimensions ?
        32'hffffffff : header[word_index*32 +:32];
    initial begin
        if (!LEGAL_PARAMETERS)
            $fatal(1,"PARAMETER ERROR: crucible_g2_top dimensions or tile size");
    end
    crucible_g1_top legacy (
        .clk(clk),.rst_n(rst_n),
        .s_valid(LEGAL_PARAMETERS && state==LEGACY_SEND),
        .s_ready(legacy_ready),.s_data(replay_data),
        .m_valid(legacy_valid),.m_ready(state==LEGACY_WAIT && m_ready),
        .m_data(legacy_data),.m_last(legacy_last)
    );
    g2_engine #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
        .TILE_LOG2(TILE_LOG2)) engine (
        .clk(clk),.rst_n(rst_n),
        .s_valid(LEGAL_PARAMETERS && state==ENGINE_SEND),.s_ready(engine_ready),
        .s_header(header),.s_attributes(attributes),
        .m_valid(engine_valid),.m_ready(state==ENGINE_WAIT && m_ready),
        .m_data(engine_data),.m_last(engine_last)
    );
    assign s_ready=rst_n && LEGAL_PARAMETERS && (state==HEADER || state==ATTRIBUTES);
    assign m_valid=rst_n && LEGAL_PARAMETERS &&
        ((state==LEGACY_WAIT && legacy_valid) || (state==ENGINE_WAIT && engine_valid));
    assign m_data=!m_valid ? 32'd0 :
        state==LEGACY_WAIT ? legacy_data : engine_data;
    assign m_last=m_valid && (state==LEGACY_WAIT ? legacy_last : engine_last);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=BOOT; word_index<=0; header<=0; attributes<=0;
            is_g2<=0; is_draw<=0; invalid_dimensions<=0;
        end else if (LEGAL_PARAMETERS) begin
            case (state)
                BOOT: state<=HEADER;
                HEADER: if (s_valid) begin
                    header[word_index*32 +:32]<=s_data;
                    if (word_index==0) attributes<=0;
                    if (word_index==1)
                        invalid_dimensions<=s_data[15:0]==0 ||
                            s_data[15:0]>MAX_WIDTH || s_data[31:16]==0 ||
                            s_data[31:16]>MAX_HEIGHT;
                    if (word_index==2) begin
                        is_draw<=draw_mode;
                        is_g2<=draw_mode || s_data==4 || s_data==5;
                    end
                    if (word_index==30) begin
                        word_index<=0;
                        if (is_draw) state<=ATTRIBUTES;
                        else if (is_g2) state<=ENGINE_SEND;
                        else state<=LEGACY_SEND;
                    end else word_index<=word_index+6'd1;
                end
                ATTRIBUTES: if (s_valid) begin
                    attributes[word_index*32 +:32]<=s_data;
                    if (word_index==17) begin word_index<=0; state<=ENGINE_SEND; end
                    else word_index<=word_index+6'd1;
                end
                LEGACY_SEND: if (legacy_ready) begin
                    if (word_index==30) begin word_index<=0; state<=LEGACY_WAIT; end
                    else word_index<=word_index+6'd1;
                end
                LEGACY_WAIT: if (m_valid && m_ready && m_last) state<=HEADER;
                ENGINE_SEND: if (engine_ready) state<=ENGINE_WAIT;
                ENGINE_WAIT: if (m_valid && m_ready && m_last) state<=HEADER;
                default: state<=BOOT;
            endcase
        end
    end
endmodule
