module g3_shader_pipeline (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [127:0] s_vertex_rgba,
    input wire [31:0] s_texture_rgba, s_destination_rgba,
    input wire [14:0] s_program,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_rgba
);
    localparam IDLE=0, QUANTIZE=1, MODULATE=2, COMBINE=3,
               PRODUCTS=4, SUMS=5, NORMALIZE=6, HOLD=7;
    reg [2:0] state;
    reg [127:0] vertex;
    reg [31:0] texture_rgba,destination,result;
    reg [14:0] program_bits;
    wire [31:0] combined;

    function automatic [8:0] normalize255;
        input [17:0] n;
        reg [18:0] t,adjusted;
        begin
            // Exact for 0 <= n <= 130177; t = n+1 avoids 255-multiple bias.
            t={1'b0,n}+19'd1;
            adjusted=t+(t>>8)+(t>>16);
            normalize255=adjusted[16:8];
        end
    endfunction
    function automatic [7:0] factor;
        input [2:0] code;
        input [7:0] source_alpha,destination_alpha;
        begin
            case (code)
                0: factor=0;
                1: factor=255;
                2: factor=source_alpha;
                3: factor=8'd255-source_alpha;
                4: factor=destination_alpha;
                5: factor=8'd255-destination_alpha;
                default: factor=0;
            endcase
        end
    endfunction
    genvar c;
    generate for (c=0;c<4;c=c+1) begin: channel
        wire signed [31:0] attribute_value=vertex[c*32 +:32];
        wire [16:0] clamped=attribute_value<0 ? 17'd0 :
            attribute_value>32'sd65536 ? 17'd65536 : attribute_value[16:0];
        wire [24:0] quantized_product=clamped*8'd255+25'd32768;
        reg [7:0] vertex8,source8,source_factor,destination_factor;
        reg [15:0] modulation_product,source_product,destination_product;
        reg [17:0] blend_sum;
        wire [8:0] modulated=normalize255({2'd0,modulation_product}+18'd127);
        wire [2:0] sf_code=c==3 ? program_bits[11:9] : program_bits[5:3];
        wire [2:0] df_code=c==3 ? program_bits[14:12] : program_bits[8:6];
        wire [7:0] sf=factor(sf_code,combined[31:24],destination[31:24]);
        wire [7:0] df=factor(df_code,combined[31:24],destination[31:24]);
        wire [8:0] normalized=normalize255(blend_sum);
        assign combined[c*8 +:8]=!program_bits[0] ? vertex8 :
            program_bits[1] ? modulated[7:0] : texture_rgba[c*8 +:8];
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                vertex8<=0; source8<=0; source_factor<=0; destination_factor<=0;
                modulation_product<=0; source_product<=0;
                destination_product<=0; blend_sum<=0; result[c*8 +:8]<=0;
            end else begin
                vertex8<=quantized_product[23:16];
                modulation_product<=vertex8*texture_rgba[c*8 +:8];
                source8<=combined[c*8 +:8];
                source_factor<=sf; destination_factor<=df;
                source_product<=source8*source_factor;
                destination_product<=destination[c*8 +:8]*destination_factor;
                blend_sum<={2'd0,source_product}+{2'd0,destination_product}+18'd127;
                if (state==NORMALIZE) begin
                    if (!program_bits[2]) result[c*8 +:8]<=source8;
                    else if (normalized>9'd255) result[c*8 +:8]<=8'd255;
                    else result[c*8 +:8]<=normalized[7:0];
                end
            end
        end
    end endgenerate
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_rgba=m_valid ? result : 32'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; vertex<=0; texture_rgba<=0; destination<=0; program_bits<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin
                    vertex<=s_vertex_rgba; texture_rgba<=s_texture_rgba;
                    destination<=s_destination_rgba; program_bits<=s_program;
                    state<=QUANTIZE;
                end
                QUANTIZE: state<=MODULATE;
                MODULATE: state<=COMBINE;
                COMBINE: state<=PRODUCTS;
                PRODUCTS: state<=SUMS;
                SUMS: state<=NORMALIZE;
                NORMALIZE: state<=HOLD;
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
