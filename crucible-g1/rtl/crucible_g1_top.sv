module crucible_g1_top (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [31:0] s_data,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_data,
    output wire m_last
);
    localparam BOOT=4'd0, RECEIVE=4'd1, TRANSFORM_SEND=4'd2,
               TRANSFORM_WAIT=4'd3, PROJECT_WAIT=4'd4,
               RASTER_SEND=4'd5, RASTER_WAIT=4'd6,
               COMPLETE_SEND=4'd7, COMPLETE_WAIT=4'd8, FAN_READ=4'd9;
    reg [3:0] state;
    reg [4:0] word_index;
    reg [31:0] tag;
    reg [8:0] width,height;
    reg mode_2d,invalid_command;
    reg [511:0] matrix;
    reg [383:0] vertices;
    reg [33:0] projected [0:383];
    reg [33:0] fan_origin;
    reg [101:0] raster_vertices;
    reg [8:0] projected_count,polygon_count,fan_i,fan_index;
    reg clip_finished;
    reg [31:0] pixel_total,fan_total,status;
    reg [191:0] record;
    reg record_valid,record_completion;
    reg [2:0] record_index;
    wire transform_ready,transform_valid;
    wire [383:0] transformed_vertices;
    wire clip_ready,clip_valid,clip_done;
    wire [127:0] clip_vertex;
    wire [8:0] clip_count;
    wire project_ready,project_valid;
    wire [33:0] project_vertex;
    wire raster_ready,raster_valid,raster_done,raster_nondegenerate;
    wire [7:0] raster_x,raster_y;
    wire [16:0] lambda0,lambda1,lambda2;
    wire take_raster = state==RASTER_WAIT && !record_valid;
    wire [8:0] fan_next = fan_i+9'd1;

    g1_transform transform (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==TRANSFORM_SEND),.s_ready(transform_ready),
        .s_mode_2d(mode_2d),.s_matrix(matrix),.s_vertices(vertices),
        .m_valid(transform_valid),
        .m_ready(state==TRANSFORM_WAIT && clip_ready),
        .m_vertices(transformed_vertices)
    );
    g1_clipper clipper (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==TRANSFORM_WAIT && transform_valid),.s_ready(clip_ready),
        .s_vertices(transformed_vertices),
        .m_valid(clip_valid),
        .m_ready(state==PROJECT_WAIT && project_ready),.m_vertex(clip_vertex),
        .done_valid(clip_done),
        .done_ready(state==PROJECT_WAIT && !clip_finished),.done_count(clip_count)
    );
    g1_project project (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==PROJECT_WAIT && clip_valid),.s_ready(project_ready),
        .s_vertex(clip_vertex),.s_width(width),.s_height(height),
        .m_valid(project_valid),.m_ready(state==PROJECT_WAIT),
        .m_vertex(project_vertex)
    );
    g1_raster raster (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==RASTER_SEND),.s_ready(raster_ready),
        .s_vertices(raster_vertices),
        .s_width(width),.s_height(height),
        .m_valid(raster_valid),.m_ready(take_raster),
        .m_x(raster_x),.m_y(raster_y),
        .m_lambda0(lambda0),.m_lambda1(lambda1),.m_lambda2(lambda2),
        .done_valid(raster_done),.done_ready(take_raster),
        .done_nondegenerate(raster_nondegenerate)
    );

    assign s_ready = rst_n && state==RECEIVE;
    assign m_valid = rst_n && record_valid;
    assign m_data = m_valid ? record[record_index*32 +:32] : 32'd0;
    assign m_last = m_valid && record_completion && record_index==3'd5;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=BOOT; word_index<=0; tag<=0; width<=0; height<=0;
            mode_2d<=0; invalid_command<=0; matrix<=0; vertices<=0;
            projected_count<=0; polygon_count<=0; fan_i<=0; fan_index<=0;
            fan_origin<=0; raster_vertices<=0;
            clip_finished<=0; pixel_total<=0; fan_total<=0; status<=0;
            record<=0; record_valid<=0; record_completion<=0; record_index<=0;
        end else begin
            if (record_valid && m_ready) begin
                if (record_index==3'd5) begin
                    record_valid<=0;
                    record_index<=0;
                    if (record_completion) state<=RECEIVE;
                end else record_index<=record_index+3'd1;
            end
            case (state)
                BOOT: state<=RECEIVE;
                RECEIVE: if (s_valid) begin
                    if (word_index==0) begin
                        tag<=s_data;
                        invalid_command<=0;
                        pixel_total<=0; fan_total<=0;
                        projected_count<=0; polygon_count<=0;
                        clip_finished<=0; fan_i<=0; fan_index<=0;
                    end else if (word_index==5'd1) begin
                        width<=s_data[8:0];
                        height<=s_data[24:16];
                        if (s_data[15:0]==0 || s_data[15:0]>16'd256 ||
                            s_data[31:16]==0 || s_data[31:16]>16'd256)
                            invalid_command<=1;
                    end else if (word_index==5'd2) begin
                        mode_2d<=s_data==32'd1;
                        if (s_data!=0 && s_data!=32'd1) invalid_command<=1;
                    end else if (word_index<=5'd18)
                        matrix[(word_index-5'd3)*32 +:32]<=s_data;
                    else vertices[(word_index-5'd19)*32 +:32]<=s_data;
                    if (word_index==5'd30) begin
                        word_index<=0;
                        if (invalid_command) begin
                            status<=32'd1;
                            state<=COMPLETE_SEND;
                        end else state<=TRANSFORM_SEND;
                    end else word_index<=word_index+5'd1;
                end
                TRANSFORM_SEND: if (transform_ready) state<=TRANSFORM_WAIT;
                TRANSFORM_WAIT: if (transform_valid && clip_ready)
                    state<=PROJECT_WAIT;
                PROJECT_WAIT: begin
                    if (project_valid) begin
                        projected[projected_count]<=project_vertex;
                        if (projected_count==0) fan_origin<=project_vertex;
                        projected_count<=projected_count+9'd1;
                    end
                    if (clip_done && !clip_finished) begin
                        polygon_count<=clip_count;
                        clip_finished<=1;
                    end
                    if (clip_finished && projected_count==polygon_count) begin
                        if (polygon_count<9'd3) begin
                            status<=32'd2;
                            state<=COMPLETE_SEND;
                        end else begin
                            fan_i<=9'd1;
                            fan_index<=0;
                            state<=FAN_READ;
                        end
                    end
                end
                FAN_READ: begin
                    raster_vertices<={projected[fan_next],projected[fan_i],fan_origin};
                    state<=RASTER_SEND;
                end
                RASTER_SEND: if (raster_ready) state<=RASTER_WAIT;
                RASTER_WAIT: begin
                    if (raster_valid && !record_valid) begin
                        record<={
                            15'd0,lambda2,
                            15'd0,lambda1,
                            15'd0,lambda0,
                            7'd0,fan_index,raster_y,raster_x,
                            tag,32'd0
                        };
                        record_valid<=1;
                        record_completion<=0;
                        record_index<=0;
                        pixel_total<=pixel_total+32'd1;
                    end
                    if (raster_done && !record_valid) begin
                        if (raster_nondegenerate) fan_total<=fan_total+32'd1;
                        if (fan_i==polygon_count-9'd2) begin
                            if (fan_total!=0 || raster_nondegenerate) status<=0;
                            else status<=32'd3;
                            state<=COMPLETE_SEND;
                        end else begin
                            fan_i<=fan_i+9'd1;
                            fan_index<=fan_index+9'd1;
                            state<=FAN_READ;
                        end
                    end
                end
                COMPLETE_SEND: if (!record_valid) begin
                    record<={32'd0,fan_total,pixel_total,status,tag,32'd1};
                    record_valid<=1;
                    record_completion<=1;
                    record_index<=0;
                    state<=COMPLETE_WAIT;
                end
                COMPLETE_WAIT: begin end
                default: state<=BOOT;
            endcase
        end
    end
endmodule
