module crucible_g3_top #(
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
    output wire m_last,
    output wire tex_req_valid,
    input wire tex_req_ready,
    output wire [31:0] tex_req_addr,
    input wire tex_rsp_valid,
    output wire tex_rsp_ready,
    input wire [31:0] tex_rsp_data,
    input wire tex_rsp_error,
    output wire dma_req_valid,
    input wire dma_req_ready,
    output wire [31:0] dma_req_addr, dma_req_data,
    output wire [3:0] dma_req_strb,
    output wire dma_req_last,
    input wire dma_rsp_valid,
    output wire dma_rsp_ready,
    input wire dma_rsp_error
);
    localparam LEGAL_PARAMETERS=MAX_WIDTH>=1 && MAX_WIDTH<=256 &&
        MAX_HEIGHT>=1 && MAX_HEIGHT<=256 && TILE_LOG2>=0 && TILE_LOG2<=4;
    localparam BOOT=0, INTAKE=1, VALIDATE=2, DESCRIPTOR_PRODUCT=3,
               DESCRIPTOR_ROW=4, DESCRIPTOR_LAST=5, DESCRIPTOR_CHECK=6,
               CONFIGURE_TEXTURE=7, CLEAR_SEND=8, CLEAR_WAIT=9,
               EXPORT_SEND=10, EXPORT_WAIT=11, REPLAY=12, PARENT_WAIT=13,
               DISPATCH=14, TEXTURE_SEND=15, TEXTURE_WAIT=16,
               CACHE_ACCOUNT=17, READ_SEND=18, READ_WAIT=19,
               SOURCE_SEND=20, SOURCE_WAIT=21, SHADER_SEND=22,
               SHADER_WAIT=23, WRITE_SEND=24, WRITE_WAIT=25,
               COMPLETE=26, OUTPUT_RECORD=27;
    reg [4:0] state;
    reg [5:0] word_index;
    reg [1567:0] command;
    reg long_frame,g3_draw,state_command;
    reg texture_configured,shader_configured,color_configured;
    reg [8:0] texture_width,texture_height,color_width,color_height;
    reg [14:0] shader_program;
    reg [40:0] descriptor_product;
    reg [41:0] descriptor_row,descriptor_last;
    reg [415:0] parent_record;
    reg [3:0] parent_index;
    reg parent_terminal,output_terminal,texture_failed,sample_error;
    reg [511:0] output_record;
    reg [3:0] output_index;
    reg [31:0] filtered_texture,destination_rgba,source_rgba,final_rgba;
    reg [31:0] status,pixels_written,fan_count,tiles_tested,tiles_rejected;
    reg [31:0] fragments_tested,fragments_passed,fragments_failed;
    reg [31:0] texture_hits,texture_misses,dma_words;

    // A tag-only mirror reconstructs lookup statistics without changing cache ports.
    // Successful refills before an error bound exactly how far to account.
    reg [3:0] account_valid;
    reg [47:0] account_tags;
    reg [7:0] account_x0,account_x1,account_y0,account_y1;
    reg [1:0] account_index;
    reg [3:0] response_word;
    reg [2:0] completed_refills;
    wire [7:0] account_x=account_index[0] ? account_x1 : account_x0;
    wire [7:0] account_y=account_index[1] ? account_y1 : account_y0;
    wire [1:0] account_line={account_y[2],account_x[2]};
    wire [11:0] account_tag={account_y[7:2],account_x[7:2]};
    wire account_hit=account_valid[account_line] &&
        account_tags[account_line*12 +:12]==account_tag;
    wire [8:0] texture_last_x=texture_width-9'd1;
    wire [8:0] texture_last_y=texture_height-9'd1;
    wire [23:0] max_u={texture_last_x[7:0],16'd0};
    wire [23:0] max_v={texture_last_y[7:0],16'd0};
    wire signed [31:0] sample_u=parent_record[224 +:32];
    wire signed [31:0] sample_v=parent_record[256 +:32];
    wire [23:0] clamped_u=sample_u<0 ? 24'd0 :
        sample_u>$signed({8'd0,max_u}) ? max_u : sample_u[23:0];
    wire [23:0] clamped_v=sample_v<0 ? 24'd0 :
        sample_v>$signed({8'd0,max_v}) ? max_v : sample_v[23:0];

    function automatic is_parent_draw;
        input [31:0] opcode;
        begin
            case (opcode)
                2,3,6,7,258,259,262,263: is_parent_draw=1;
                default: is_parent_draw=0;
            endcase
        end
    endfunction
    function automatic is_g3_draw;
        input [31:0] opcode;
        begin
            case (opcode)
                514,515,518,519,770,771,774,775: is_g3_draw=1;
                default: is_g3_draw=0;
            endcase
        end
    endfunction
    function automatic is_state_command;
        input [31:0] opcode;
        begin
            case (opcode)
                1024,1025,1026,1027: is_state_command=1;
                default: is_state_command=0;
            endcase
        end
    endfunction
    wire [31:0] opcode=command[64 +:32];
    wire [15:0] command_width=command[32 +:16];
    wire [15:0] command_height=command[48 +:16];
    wire [31:0] descriptor_base=command[96 +:32];
    wire [31:0] descriptor_stride=command[128 +:32];
    wire [31:0] program_word=command[96 +:32];
    wire viewport_valid=command_width!=0 && command_width<=MAX_WIDTH &&
        command_height!=0 && command_height<=MAX_HEIGHT;
    wire texture_dimensions_valid=command_width!=0 && command_width<=256 &&
        command_height!=0 && command_height<=256;
    wire color_matches=color_configured && command_width==color_width &&
        command_height==color_height;
    wire address_fields_valid=descriptor_base[1:0]==0 &&
        descriptor_stride[1:0]==0 &&
        descriptor_stride>={14'd0,command_width,2'd0} &&
        command[991:160]==0;
    wire program_valid=command[63:32]==0 && command[991:128]==0 &&
        program_word[31:15]==0 && program_word[5:3]<=5 &&
        program_word[8:6]<=5 && program_word[11:9]<=5 &&
        program_word[14:12]<=5;
    wire [8:0] descriptor_height_minus_one=command_height[8:0]-9'd1;

    wire compatibility_ready,compatibility_valid,compatibility_last;
    wire [31:0] compatibility_data;
    wire [31:0] replay_data=word_index==2 && g3_draw ?
        (opcode & 32'hfffffdff) : command[word_index*32 +:32];
    wire cache_cfg_ready,cache_ready,cache_valid,cache_error;
    wire [31:0] cache_rgba;
    wire shader_ready,shader_valid;
    wire [31:0] shader_rgba;
    wire fb_clear_ready,fb_clear_done,fb_read_ready,fb_read_valid;
    wire fb_write_ready,fb_write_done,fb_export_ready,fb_export_done,fb_export_error;
    wire [31:0] fb_read_rgba,fb_export_words;

    initial begin
        if (!LEGAL_PARAMETERS)
            $fatal(1,"PARAMETER ERROR: crucible_g3_top dimensions or tile size");
    end
    crucible_g2_top #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
        .TILE_LOG2(TILE_LOG2)) compatibility (
        .clk(clk),.rst_n(rst_n),
        .s_valid(LEGAL_PARAMETERS && state==REPLAY),
        .s_ready(compatibility_ready),.s_data(replay_data),
        .m_valid(compatibility_valid),
        .m_ready(state==PARENT_WAIT && (g3_draw || m_ready)),
        .m_data(compatibility_data),.m_last(compatibility_last)
    );
    g3_texture_cache texture_cache (
        .clk(clk),.rst_n(rst_n),
        .cfg_valid(LEGAL_PARAMETERS && state==CONFIGURE_TEXTURE),
        .cfg_ready(cache_cfg_ready),.cfg_base(descriptor_base),
        .cfg_stride(descriptor_stride),.cfg_width(command_width[8:0]),
        .cfg_height(command_height[8:0]),
        .s_valid(state==TEXTURE_SEND),.s_ready(cache_ready),
        .s_u(sample_u),.s_v(sample_v),
        .m_valid(cache_valid),.m_ready(state==TEXTURE_WAIT),
        .m_rgba(cache_rgba),.m_error(cache_error),
        .tex_req_valid(tex_req_valid),.tex_req_ready(tex_req_ready),
        .tex_req_addr(tex_req_addr),.tex_rsp_valid(tex_rsp_valid),
        .tex_rsp_ready(tex_rsp_ready),.tex_rsp_data(tex_rsp_data),
        .tex_rsp_error(tex_rsp_error)
    );
    g3_shader_pipeline shader (
        .clk(clk),.rst_n(rst_n),
        .s_valid(state==SOURCE_SEND || state==SHADER_SEND),.s_ready(shader_ready),
        .s_vertex_rgba(parent_record[288 +:128]),
        .s_texture_rgba(filtered_texture),.s_destination_rgba(destination_rgba),
        .s_program(state==SOURCE_SEND ? shader_program & 15'h7ffb : shader_program),
        .m_valid(shader_valid),.m_ready(state==SOURCE_WAIT || state==SHADER_WAIT),
        .m_rgba(shader_rgba)
    );
    g3_framebuffer_dma #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
        .TILE_LOG2(TILE_LOG2)) framebuffer_dma (
        .clk(clk),.rst_n(rst_n),
        .clear_valid(LEGAL_PARAMETERS && state==CLEAR_SEND),.clear_ready(fb_clear_ready),
        .clear_width(command_width[8:0]),.clear_height(command_height[8:0]),
        .clear_rgba(command[96 +:32]),
        .clear_done_valid(fb_clear_done),.clear_done_ready(state==CLEAR_WAIT),
        .read_valid(state==READ_SEND),.read_ready(fb_read_ready),
        .read_x(parent_record[64 +:8]),.read_y(parent_record[72 +:8]),
        .read_result_valid(fb_read_valid),.read_result_ready(state==READ_WAIT),
        .read_rgba(fb_read_rgba),
        .write_valid(state==WRITE_SEND),.write_ready(fb_write_ready),
        .write_x(parent_record[64 +:8]),.write_y(parent_record[72 +:8]),
        .write_rgba(final_rgba),.write_done_valid(fb_write_done),
        .write_done_ready(state==WRITE_WAIT),
        .export_valid(LEGAL_PARAMETERS && state==EXPORT_SEND),.export_ready(fb_export_ready),
        .export_base(descriptor_base),.export_stride(descriptor_stride),
        .export_done_valid(fb_export_done),.export_done_ready(state==EXPORT_WAIT),
        .export_error(fb_export_error),.export_words(fb_export_words),
        .dma_req_valid(dma_req_valid),.dma_req_ready(dma_req_ready),
        .dma_req_addr(dma_req_addr),.dma_req_data(dma_req_data),
        .dma_req_strb(dma_req_strb),.dma_req_last(dma_req_last),
        .dma_rsp_valid(dma_rsp_valid),.dma_rsp_ready(dma_rsp_ready),
        .dma_rsp_error(dma_rsp_error)
    );
    assign s_ready=rst_n && LEGAL_PARAMETERS && state==INTAKE;
    assign m_valid=rst_n && LEGAL_PARAMETERS && (state==OUTPUT_RECORD ||
        (state==PARENT_WAIT && !g3_draw && compatibility_valid));
    assign m_data=!m_valid ? 32'd0 : state==OUTPUT_RECORD ?
        output_record[output_index*32 +:32] : compatibility_data;
    assign m_last=m_valid && (state==OUTPUT_RECORD ?
        output_terminal && output_index==15 : compatibility_last);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=BOOT; word_index<=0; command<=0;
            long_frame<=0; g3_draw<=0; state_command<=0;
            texture_configured<=0; shader_configured<=0; color_configured<=0;
            texture_width<=0; texture_height<=0; color_width<=0; color_height<=0;
            shader_program<=0; descriptor_product<=0; descriptor_row<=0;
            descriptor_last<=0; parent_record<=0; parent_index<=0;
            parent_terminal<=0; output_terminal<=0; texture_failed<=0; sample_error<=0;
            output_record<=0; output_index<=0; filtered_texture<=0;
            destination_rgba<=0; source_rgba<=0; final_rgba<=0;
            status<=0; pixels_written<=0; fan_count<=0; tiles_tested<=0;
            tiles_rejected<=0; fragments_tested<=0; fragments_passed<=0;
            fragments_failed<=0; texture_hits<=0; texture_misses<=0; dma_words<=0;
            account_valid<=0; account_tags<=0;
            account_x0<=0; account_x1<=0; account_y0<=0; account_y1<=0;
            account_index<=0; response_word<=0; completed_refills<=0;
        end else if (LEGAL_PARAMETERS) begin
            if (state==TEXTURE_WAIT && tex_rsp_valid && tex_rsp_ready && !tex_rsp_error) begin
                if (response_word==15) begin
                    response_word<=0; completed_refills<=completed_refills+3'd1;
                end else response_word<=response_word+4'd1;
            end
            case (state)
                BOOT: state<=INTAKE;
                INTAKE: if (s_valid) begin
                    command[word_index*32 +:32]<=s_data;
                    if (word_index==0) begin
                        status<=0; pixels_written<=0; fan_count<=0;
                        tiles_tested<=0; tiles_rejected<=0; fragments_tested<=0;
                        fragments_passed<=0; fragments_failed<=0;
                        texture_hits<=0; texture_misses<=0; dma_words<=0;
                        texture_failed<=0; parent_index<=0;
                    end
                    if (word_index==2) begin
                        long_frame<=is_parent_draw(s_data) || is_g3_draw(s_data);
                        g3_draw<=is_g3_draw(s_data);
                        state_command<=is_state_command(s_data);
                    end
                    if ((word_index==30 && !long_frame) || word_index==48) begin
                        word_index<=0; state<=VALIDATE;
                    end else word_index<=word_index+6'd1;
                end
                VALIDATE: begin
                    if (state_command) begin
                        case (opcode)
                            1024: begin
                                if (!texture_dimensions_valid || !address_fields_valid) begin
                                    status<=1; state<=COMPLETE;
                                end else state<=DESCRIPTOR_PRODUCT;
                            end
                            1025: begin
                                if (!program_valid) status<=1;
                                else begin shader_program<=program_word[14:0]; shader_configured<=1; end
                                state<=COMPLETE;
                            end
                            1026: begin
                                if (!viewport_valid || command[991:128]!=0) begin
                                    status<=1; state<=COMPLETE;
                                end else state<=CLEAR_SEND;
                            end
                            1027: begin
                                if (!viewport_valid || !address_fields_valid) begin
                                    status<=1; state<=COMPLETE;
                                end else state<=DESCRIPTOR_PRODUCT;
                            end
                            default: begin status<=1; state<=COMPLETE; end
                        endcase
                    end else if (g3_draw) begin
                        if (!viewport_valid) begin status<=1; state<=COMPLETE; end
                        else if (!color_matches || !shader_configured ||
                            (shader_program[0] && !texture_configured)) begin
                            status<=4; state<=COMPLETE;
                        end else state<=REPLAY;
                    end else state<=REPLAY;
                end
                DESCRIPTOR_PRODUCT: begin
                    descriptor_product<=descriptor_height_minus_one*descriptor_stride;
                    state<=DESCRIPTOR_ROW;
                end
                DESCRIPTOR_ROW: begin
                    descriptor_row<={10'd0,descriptor_base}+{1'b0,descriptor_product};
                    state<=DESCRIPTOR_LAST;
                end
                DESCRIPTOR_LAST: begin
                    descriptor_last<=descriptor_row+{24'd0,command_width,2'd0}-42'd1;
                    state<=DESCRIPTOR_CHECK;
                end
                DESCRIPTOR_CHECK: begin
                    if (descriptor_last[41:32]!=0) begin status<=1; state<=COMPLETE; end
                    else if (opcode==1024) state<=CONFIGURE_TEXTURE;
                    else if (!color_matches) begin status<=4; state<=COMPLETE; end
                    else state<=EXPORT_SEND;
                end
                CONFIGURE_TEXTURE: if (cache_cfg_ready) begin
                    texture_width<=command_width[8:0]; texture_height<=command_height[8:0];
                    texture_configured<=1; account_valid<=0; state<=COMPLETE;
                end
                CLEAR_SEND: if (fb_clear_ready) state<=CLEAR_WAIT;
                CLEAR_WAIT: if (fb_clear_done) begin
                    color_width<=command_width[8:0]; color_height<=command_height[8:0];
                    color_configured<=1; state<=COMPLETE;
                end
                EXPORT_SEND: if (fb_export_ready) state<=EXPORT_WAIT;
                EXPORT_WAIT: if (fb_export_done) begin
                    if (fb_export_error) status<=5;
                    dma_words<=fb_export_words; state<=COMPLETE;
                end
                REPLAY: if (compatibility_ready) begin
                    if ((!long_frame && word_index==30) || word_index==48) begin
                        word_index<=0; parent_index<=0; state<=PARENT_WAIT;
                    end else word_index<=word_index+6'd1;
                end
                PARENT_WAIT: if (compatibility_valid) begin
                    if (!g3_draw) begin
                        if (m_ready && compatibility_last) state<=INTAKE;
                    end else begin
                        parent_record[parent_index*32 +:32]<=compatibility_data;
                        if (parent_index==12) begin
                            parent_terminal<=compatibility_last;
                            parent_index<=0; state<=DISPATCH;
                        end else parent_index<=parent_index+4'd1;
                    end
                end
                DISPATCH: begin
                    if (parent_terminal) begin
                        if (texture_failed) status<=5;
                        else status<=parent_record[64 +:32];
                        fan_count<=parent_record[128 +:32];
                        tiles_tested<=parent_record[160 +:32];
                        tiles_rejected<=parent_record[192 +:32];
                        fragments_tested<=parent_record[224 +:32];
                        fragments_passed<=parent_record[256 +:32];
                        fragments_failed<=parent_record[288 +:32];
                        state<=COMPLETE;
                    end else if (texture_failed) state<=PARENT_WAIT;
                    else if (shader_program[0]) state<=TEXTURE_SEND;
                    else begin filtered_texture<=0; state<=READ_SEND; end
                end
                TEXTURE_SEND: if (cache_ready) begin
                    account_x0<=clamped_u[23:16]; account_y0<=clamped_v[23:16];
                    account_x1<={1'b0,clamped_u[23:16]}+9'd1>=texture_width ?
                        clamped_u[23:16] : clamped_u[23:16]+8'd1;
                    account_y1<={1'b0,clamped_v[23:16]}+9'd1>=texture_height ?
                        clamped_v[23:16] : clamped_v[23:16]+8'd1;
                    account_index<=0; response_word<=0; completed_refills<=0;
                    state<=TEXTURE_WAIT;
                end
                TEXTURE_WAIT: if (cache_valid) begin
                    filtered_texture<=cache_rgba; sample_error<=cache_error;
                    state<=CACHE_ACCOUNT;
                end
                CACHE_ACCOUNT: begin
                    if (account_hit) texture_hits<=texture_hits+32'd1;
                    else texture_misses<=texture_misses+32'd1;
                    if (!account_hit && sample_error && completed_refills==0) begin
                        account_valid<=0; texture_failed<=1; state<=PARENT_WAIT;
                    end else begin
                        if (!account_hit) begin
                            account_valid[account_line]<=1;
                            account_tags[account_line*12 +:12]<=account_tag;
                            if (sample_error) completed_refills<=completed_refills-3'd1;
                        end
                        if (account_index==3) state<=READ_SEND;
                        else account_index<=account_index+2'd1;
                    end
                end
                READ_SEND: if (fb_read_ready) state<=READ_WAIT;
                READ_WAIT: if (fb_read_valid) begin
                    destination_rgba<=fb_read_rgba; state<=SOURCE_SEND;
                end
                SOURCE_SEND: if (shader_ready) state<=SOURCE_WAIT;
                SOURCE_WAIT: if (shader_valid) begin source_rgba<=shader_rgba; state<=SHADER_SEND; end
                SHADER_SEND: if (shader_ready) state<=SHADER_WAIT;
                SHADER_WAIT: if (shader_valid) begin final_rgba<=shader_rgba; state<=WRITE_SEND; end
                WRITE_SEND: if (fb_write_ready) state<=WRITE_WAIT;
                WRITE_WAIT: if (fb_write_done) begin
                    pixels_written<=pixels_written+32'd1;
                    output_record<={final_rgba,source_rgba,filtered_texture,
                        parent_record[415:32],32'd2};
                    output_index<=0; output_terminal<=0; state<=OUTPUT_RECORD;
                end
                COMPLETE: begin
                    output_record<={96'd0,dma_words,texture_misses,texture_hits,
                        fragments_failed,fragments_passed,fragments_tested,
                        tiles_rejected,tiles_tested,fan_count,pixels_written,
                        status,command[31:0],32'd3};
                    output_index<=0; output_terminal<=1; state<=OUTPUT_RECORD;
                end
                OUTPUT_RECORD: if (m_ready) begin
                    if (output_index==15) begin
                        output_index<=0;
                        if (output_terminal) state<=INTAKE;
                        else state<=PARENT_WAIT;
                    end else output_index<=output_index+4'd1;
                end
                default: state<=BOOT;
            endcase
        end
    end
endmodule
