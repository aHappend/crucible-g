module g1_transform (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire s_mode_2d,
    input wire [511:0] s_matrix,
    input wire [383:0] s_vertices,
    output wire m_valid,
    input wire m_ready,
    output wire [383:0] m_vertices
);
    localparam IDLE=2'd0, ISSUE=2'd1, WAIT_RESULT=2'd2, HOLD=2'd3;
    reg [1:0] state,row;
    reg [1:0] vertex_index;
    reg mode_2d;
    reg [511:0] matrix;
    reg [383:0] vertices,result;
    wire [127:0] vertex_raw = vertices[vertex_index*128 +:128];
    wire [127:0] dot_b = mode_2d ?
        {32'sd65536,32'sd0,vertex_raw[63:0]} : vertex_raw;
    wire dot_ready,dot_valid;
    wire signed [31:0] dot_result;

    g1_dot4 dot (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==ISSUE),.s_ready(dot_ready),
        .s_a(matrix[row*128 +:128]),.s_b(dot_b),
        .m_valid(dot_valid),.m_ready(state==WAIT_RESULT),
        .m_result(dot_result)
    );
    assign s_ready = rst_n && state==IDLE;
    assign m_valid = rst_n && state==HOLD;
    assign m_vertices = result;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; row<=0; vertex_index<=0; mode_2d<=0;
            matrix<=0; vertices<=0; result<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    matrix<=s_matrix; vertices<=s_vertices; mode_2d<=s_mode_2d;
                    row<=0; vertex_index<=0; state<=ISSUE;
                end
                ISSUE: if (dot_ready) state<=WAIT_RESULT;
                WAIT_RESULT: if (dot_valid) begin
                    result[vertex_index*128+row*32 +:32]<=dot_result;
                    if (row==2'd3) begin
                        row<=0;
                        if (vertex_index==2'd2) state<=HOLD;
                        else begin
                            vertex_index<=vertex_index+2'd1;
                            state<=ISSUE;
                        end
                    end else begin
                        row<=row+2'd1;
                        state<=ISSUE;
                    end
                end
                HOLD: if (m_ready) state<=IDLE;
            endcase
        end
    end
endmodule
