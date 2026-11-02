module g5_svgf #(
    parameter integer MAX_WIDTH=32, MAX_HEIGHT=32
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [991:0] s_command,
    output wire m_valid,
    input wire m_ready,
    output wire [511:0] m_record,
    output wire m_terminal
);
    localparam LEGAL=MAX_WIDTH>=1 && MAX_WIDTH<=64 && MAX_HEIGHT>=1 && MAX_HEIGHT<=64;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_svgf dimensions");
        assign s_ready=0; assign m_valid=0; assign m_record=0; assign m_terminal=0;
    end else begin: implementation
        localparam CAPACITY=MAX_WIDTH*MAX_HEIGHT;
        localparam IDLE=0, VALIDATE=1, SAMPLE_ADDRESS=2,
            SAMPLE_SURFACE_SEND=3, SAMPLE_SURFACE_WAIT=4, SAMPLE_STORE=5,
            PAD=6, RUN_DEADLINE_LOW=7, RUN_DEADLINE_HIGH=8, RUN_PREFIX=9,
            TEMP_REQUEST=10, TEMP_CAPTURE=11, MOTION_X_SEND=12,
            MOTION_X_WAIT=13, MOTION_Y_SEND=14, MOTION_Y_WAIT=15,
            HISTORY_PRODUCT=16, HISTORY_ADDRESS=17, HISTORY_REQUEST=18,
            HISTORY_CAPTURE=19, HISTORY_SURFACE_SEND=20, HISTORY_SURFACE_WAIT=21,
            TEMP_CHANNEL_SEND=22, TEMP_CHANNEL_WAIT=23, TEMP_STORE=24,
            SLOT_WAIT=25, CENTER_REQUEST=26, CENTER_CAPTURE=27,
            CENTER_CHANNEL_SEND=28, CENTER_CHANNEL_WAIT=29,
            TAP_COORDINATES=30, TAP_PRODUCT=31, TAP_ADDRESS=32,
            TAP_REQUEST=33, TAP_CAPTURE=34, TAP_SURFACE_SEND=35,
            TAP_SURFACE_WAIT=36, WEIGHT_SQUARE=37, WEIGHT_SELECT=38,
            TAP_CHANNEL_SEND=39, TAP_CHANNEL_WAIT=40, TAP_NEXT=41,
            NORMALIZE_SEND=42, NORMALIZE_WAIT=43, SPATIAL_STORE=44,
            HOLD=45, EMIT_REQUEST=46, EMIT_CAPTURE=47, COMPLETION_GAP=48;
        reg [5:0] state;
        reg [991:0] command;
        reg [511:0] record;
        reg terminal, frame_active, history_valid, history_bank, plane_source;
        reg [6:0] width, height, history_width, history_height;
        reg [12:0] pixels, initialized_count, pixel, emit_pixel, accepted_count;
        reg [6:0] x, y, emit_x, emit_y;
        reg [CAPACITY-1:0] initialized, accepted_map;
        reg [31:0] age, deadline, size_product, run_product;
        reg [15:0] deadline_low;
        reg deadline_carry, running;
        reg [13:0] slot_clock;
        reg spatial;
        reg [1:0] pass;
        reg [2:0] tap_x, tap_y;
        reg signed [15:0] tap_coordinate_x, tap_coordinate_y;
        reg [15:0] address_product;
        reg [12:0] sample_address, history_address, tap_address;
        reg [207:0] center_sample, tap_sample;
        reg [255:0] previous_history, next_history;
        reg [127:0] center_plane, tap_plane, plane_work;
        reg signed [31:0] previous_x, previous_y;
        reg history_in_bounds, history_accepted;
        reg [16:0] normal_weight;
        reg depth_step;
        reg [31:0] square;
        reg [1:0] square_iteration;
        reg [5:0] kernel;
        reg [12:0] read_address;
        reg sample_we, history_we, plane_we;
        reg [12:0] write_address;
        reg [207:0] sample_data;
        reg [255:0] history_data;
        reg [127:0] plane_data;
        (* ramstyle = "M20K", nomem2reg *) reg [207:0] samples [0:CAPACITY-1];
        (* ramstyle = "M20K", nomem2reg *) reg [255:0] history_a [0:CAPACITY-1];
        (* ramstyle = "M20K", nomem2reg *) reg [255:0] history_b [0:CAPACITY-1];
        (* ramstyle = "M20K", nomem2reg *) reg [127:0] plane_a [0:CAPACITY-1];
        (* ramstyle = "M20K", nomem2reg *) reg [127:0] plane_b [0:CAPACITY-1];
        reg [207:0] sample_q;
        reg [255:0] history_a_q, history_b_q;
        reg [127:0] plane_a_q, plane_b_q;
        wire [255:0] history_q=history_bank ? history_b_q : history_a_q;
        wire [127:0] plane_q=plane_source ? plane_b_q : plane_a_q;
        wire [127:0] final_plane_q=plane_source ? plane_a_q : plane_b_q;
        wire [16:0] deadline_sum={1'b0,run_product[15:0]}+17'd63;
        wire engine_rst_n=rst_n && !((state==PAD || state==HOLD) &&
            record[64 +:32]==4);
        wire [31:0] opcode=command[64 +:32];
        wire sample_bad=command[32 +:32]!=0 || (|command[991:416]) ||
            (|command[191:184]) || (|command[223:216]) || command[255] ||
            !normal_component_valid(command[256 +:32]) ||
            !normal_component_valid(command[288 +:32]) ||
            !normal_component_valid(command[320 +:32]) ||
            command[383:368]!={16{command[367]}} ||
            command[415:400]!={16{command[399]}};
        wire begin_bad=(|command[991:128]) || (|command[127:97]) ||
            command[47:32]==0 || command[63:48]==0 ||
            command[47:32]>MAX_WIDTH || command[63:48]>MAX_HEIGHT;
        wire short_bad=command[32 +:32]!=0 || (|command[991:96]);
        wire surface_ready, surface_valid, surface_depth_ok, surface_depth_step;
        wire signed [47:0] surface_dot_raw;
        wire [16:0] surface_dot;
        reg surface_send, surface_take;
        reg [95:0] surface_normal_a, surface_normal_b;
        reg [31:0] surface_depth_a, surface_depth_b;
        wire valid_length=surface_dot_raw[47:32]==0 &&
            surface_dot_raw[31:16]>=16'h3f00 &&
            (surface_dot_raw[31:16]<16'h4100 ||
                (surface_dot_raw[31:16]==16'h4100 && surface_dot_raw[15:0]==0));
        wire motion_ready, motion_valid, motion_less, motion_equal, motion_carry;
        wire [31:0] motion_result;
        reg [31:0] motion_a, motion_b;
        wire [1:0] channel_ready, channel_valid, channel_error;
        wire [31:0] channel_luma [0:1], channel_variance [0:1];
        wire [31:0] channel_mean [0:1], channel_second [0:1];
        reg channel_send, channel_take;
        reg [1:0] channel_mode;
        reg [31:0] channel_input_luma [0:1], channel_input_variance [0:1];
        reg [31:0] channel_input_mean [0:1], channel_input_second [0:1];
        reg signed [15:0] offset_x, offset_y;
        wire [13:0] slot_limit=spatial ? 14'd8192 : 14'd1024;
        wire slot_active=running && state>=TEMP_REQUEST && state<=SPATIAL_STORE;
        function automatic normal_component_valid;
            input [31:0] n;
            begin
                normal_component_valid=(n[31:16]==0 && n[15:0]<=16'h8000) ||
                    (n[31:16]==16'hffff && n[15:0]>=16'h8000);
            end
        endfunction
        function automatic [3:0] kernel_value;
            input [2:0] tap;
            begin
                case (tap)
                    0,4: kernel_value=1;
                    1,3: kernel_value=4;
                    2: kernel_value=6;
                    default: kernel_value=0;
                endcase
            end
        endfunction
        g5_svgf_surface surface (
            .clk(clk),.rst_n(engine_rst_n),.s_valid(surface_send),.s_ready(surface_ready),
            .s_normal_a(surface_normal_a),.s_normal_b(surface_normal_b),
            .s_depth_a(surface_depth_a),.s_depth_b(surface_depth_b),
            .m_valid(surface_valid),.m_ready(surface_take),
            .m_dot_raw(surface_dot_raw),.m_dot(surface_dot),
            .m_depth_ok(surface_depth_ok),.m_depth_step(surface_depth_step)
        );
        g5_limb_alu #(.WIDTH(32)) motion (
            .clk(clk),.rst_n(engine_rst_n),
            .s_valid(state==MOTION_X_SEND || state==MOTION_Y_SEND),
            .s_ready(motion_ready),.s_a(motion_a),.s_b(motion_b),
            .s_subtract(1'b0),.m_valid(motion_valid),
            .m_ready(state==MOTION_X_WAIT || state==MOTION_Y_WAIT),
            .m_result(motion_result),.m_less(motion_less),
            .m_equal(motion_equal),.m_carry(motion_carry)
        );
        genvar lane;
        for (lane=0; lane<2; lane=lane+1) begin: radiance_channels
            g5_svgf_channel filter (
                .clk(clk),.rst_n(engine_rst_n),.s_valid(channel_send),
                .s_ready(channel_ready[lane]),.s_mode(channel_mode),
                .s_luma(channel_input_luma[lane]),
                .s_variance(channel_input_variance[lane]),
                .s_mean(channel_input_mean[lane]),.s_second(channel_input_second[lane]),
                .s_history(history_accepted),.s_normal_weight(normal_weight),
                .s_depth_step(depth_step),.s_kernel(kernel),
                .m_valid(channel_valid[lane]),.m_ready(channel_take),
                .m_luma(channel_luma[lane]),.m_variance(channel_variance[lane]),
                .m_mean(channel_mean[lane]),.m_second(channel_second[lane]),
                .m_error(channel_error[lane])
            );
        end
        assign s_ready=rst_n && state==IDLE;
        assign m_valid=rst_n && state==HOLD;
        assign m_record=m_valid ? record : 512'd0;
        assign m_terminal=m_valid && terminal;
        always @* begin
            read_address=pixel;
            if (state==HISTORY_REQUEST || state==HISTORY_CAPTURE)
                read_address=history_address;
            else if (state==TAP_REQUEST || state==TAP_CAPTURE)
                read_address=tap_address;
            else if (state==EMIT_REQUEST || state==EMIT_CAPTURE)
                read_address=emit_pixel;
            else if (state==SLOT_WAIT && spatial && pass==2 && pixel==pixels-13'd1)
                read_address=0;
            sample_we=rst_n && state==SAMPLE_STORE;
            history_we=rst_n && state==TEMP_STORE;
            plane_we=rst_n && (state==TEMP_STORE || state==SPATIAL_STORE);
            write_address=state==SAMPLE_STORE ? sample_address : pixel;
            sample_data={command[384 +:16],command[352 +:16],
                command[256 +:96],command[224 +:32],
                command[192 +:24],command[160 +:24]};
            history_data=next_history; plane_data=plane_work;
            surface_send=rst_n && (state==SAMPLE_SURFACE_SEND ||
                state==HISTORY_SURFACE_SEND || state==TAP_SURFACE_SEND);
            surface_take=rst_n && (state==SAMPLE_SURFACE_WAIT ||
                state==HISTORY_SURFACE_WAIT || state==TAP_SURFACE_WAIT);
            surface_normal_a=center_sample[80 +:96];
            surface_normal_b=tap_sample[80 +:96];
            surface_depth_a=center_sample[48 +:32];
            surface_depth_b=tap_sample[48 +:32];
            if (state==SAMPLE_SURFACE_SEND) begin
                surface_normal_a=command[256 +:96]; surface_normal_b=command[256 +:96];
                surface_depth_a=0; surface_depth_b=0;
            end else if (state==HISTORY_SURFACE_SEND) begin
                surface_normal_b=previous_history[160 +:96];
                surface_depth_b=previous_history[128 +:32];
            end
            motion_a=state==MOTION_X_SEND ? {25'd0,x} : {25'd0,y};
            motion_b=state==MOTION_X_SEND ?
                {{16{center_sample[191]}},center_sample[176 +:16]} :
                {{16{center_sample[207]}},center_sample[192 +:16]};
            channel_send=rst_n && (&channel_ready) &&
                (state==TEMP_CHANNEL_SEND || state==CENTER_CHANNEL_SEND ||
                state==TAP_CHANNEL_SEND || state==NORMALIZE_SEND);
            channel_take=rst_n && (&channel_valid) &&
                (state==TEMP_CHANNEL_WAIT || state==CENTER_CHANNEL_WAIT ||
                state==TAP_CHANNEL_WAIT || state==NORMALIZE_WAIT);
            channel_mode=0;
            channel_input_luma[0]={8'd0,center_sample[0 +:24]};
            channel_input_luma[1]={8'd0,center_sample[24 +:24]};
            channel_input_variance[0]=0; channel_input_variance[1]=0;
            channel_input_mean[0]=previous_history[0 +:32];
            channel_input_mean[1]=previous_history[32 +:32];
            channel_input_second[0]=previous_history[64 +:32];
            channel_input_second[1]=previous_history[96 +:32];
            if (state==CENTER_CHANNEL_SEND) begin
                channel_mode=1;
                channel_input_luma[0]=center_plane[0 +:32];
                channel_input_luma[1]=center_plane[32 +:32];
                channel_input_variance[0]=center_plane[64 +:32];
                channel_input_variance[1]=center_plane[96 +:32];
            end else if (state==TAP_CHANNEL_SEND) begin
                channel_mode=2;
                channel_input_luma[0]=tap_plane[0 +:32];
                channel_input_luma[1]=tap_plane[32 +:32];
                channel_input_variance[0]=tap_plane[64 +:32];
                channel_input_variance[1]=tap_plane[96 +:32];
            end else if (state==NORMALIZE_SEND) channel_mode=3;
            case (tap_x)
                0: offset_x=-16'sd2;
                1: offset_x=-16'sd1;
                2: offset_x=0;
                3: offset_x=1;
                default: offset_x=2;
            endcase
            case (tap_y)
                0: offset_y=-16'sd2;
                1: offset_y=-16'sd1;
                2: offset_y=0;
                3: offset_y=1;
                default: offset_y=2;
            endcase
        end
        always @(posedge clk) begin
            if (sample_we) samples[write_address]<=sample_data;
            if (history_we) begin
                if (history_bank) history_a[write_address]<=history_data;
                else history_b[write_address]<=history_data;
            end
            if (plane_we) begin
                if (state==TEMP_STORE || plane_source) plane_a[write_address]<=plane_data;
                else plane_b[write_address]<=plane_data;
            end
            sample_q<=samples[read_address];
            history_a_q<=history_a[read_address]; history_b_q<=history_b[read_address];
            plane_a_q<=plane_a[read_address]; plane_b_q<=plane_b[read_address];
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; command<=0; record<=0; terminal<=0;
                frame_active<=0; history_valid<=0; history_bank<=0; plane_source<=0;
                width<=0; height<=0; history_width<=0; history_height<=0; pixels<=0;
                initialized_count<=0; pixel<=0; emit_pixel<=0; accepted_count<=0;
                x<=0; y<=0; emit_x<=0; emit_y<=0; initialized<=0; accepted_map<=0;
                age<=0; deadline<=0; size_product<=0; run_product<=0;
                deadline_low<=0; deadline_carry<=0; running<=0; slot_clock<=0;
                spatial<=0; pass<=0; tap_x<=0; tap_y<=0; tap_coordinate_x<=0;
                tap_coordinate_y<=0; address_product<=0; sample_address<=0;
                history_address<=0; tap_address<=0; center_sample<=0; tap_sample<=0;
                previous_history<=0; next_history<=0; center_plane<=0;
                tap_plane<=0; plane_work<=0; previous_x<=0; previous_y<=0;
                history_in_bounds<=0; history_accepted<=0; normal_weight<=0;
                depth_step<=0; square<=0; square_iteration<=0; kernel<=0;
            end else begin
                if (state!=IDLE && state!=HOLD && state!=EMIT_REQUEST &&
                    state!=EMIT_CAPTURE && state!=COMPLETION_GAP) begin
                    age[15:0]<=age[15:0]+16'd1;
                    if (age[15:0]==16'hffff) age[31:16]<=age[31:16]+16'd1;
                end
                if (slot_active) slot_clock<=slot_clock+14'd1;
                case (state)
                    IDLE: if (s_valid) begin
                        command<=s_command; record<=0; terminal<=1;
                        record[0 +:32]<=32'h50000000;
                        record[32 +:32]<=s_command[0 +:32];
                        record[96 +:32]<=s_command[64 +:32];
                        size_product<=s_command[32 +:16]*s_command[48 +:16];
                        run_product<={3'd0,pixels}*16'd25600;
                        age<=0; deadline<=63; running<=0; state<=VALIDATE;
                    end
                    VALIDATE: case (opcode)
                        32'h920: begin
                            if (begin_bad) begin
                                record[64 +:32]<=1; record[511:96]<=0;
                            end else begin
                                width<=command[38:32]; height<=command[54:48];
                                pixels<=size_product[12:0]; initialized<=0;
                                initialized_count<=0; frame_active<=1; accepted_map<=0;
                                record[128 +:32]<=size_product;
                                if (command[96] || command[38:32]!=history_width ||
                                    command[54:48]!=history_height) history_valid<=0;
                            end
                            state<=PAD;
                        end
                        32'h921: begin
                            if (sample_bad) begin
                                record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                            end else if (!frame_active) begin
                                record[64 +:32]<=2; record[511:96]<=0; state<=PAD;
                            end else if ((|command[127:112]) || (|command[159:144]) ||
                                command[111:96]>={9'd0,width} ||
                                command[143:128]>={9'd0,height}) begin
                                record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                            end else begin
                                address_product<={9'd0,width}*command[128 +:16];
                                state<=SAMPLE_ADDRESS;
                            end
                        end
                        32'h922: begin
                            if (short_bad) begin
                                record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                            end else if (!frame_active || initialized_count!=pixels) begin
                                record[64 +:32]<=2; record[511:96]<=0; state<=PAD;
                            end else begin
                                running<=1; accepted_count<=0; accepted_map<=0;
                                pixel<=0; x<=0; y<=0; spatial<=0; pass<=0;
                                plane_source<=0; state<=RUN_DEADLINE_LOW;
                            end
                        end
                        32'h923: begin
                            if (short_bad) begin
                                record[64 +:32]<=1; record[511:96]<=0;
                            end else history_valid<=0;
                            state<=PAD;
                        end
                        default: begin
                            record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                        end
                    endcase
                    SAMPLE_ADDRESS: begin
                        sample_address<=address_product[12:0]+command[96 +:13];
                        state<=SAMPLE_SURFACE_SEND;
                    end
                    SAMPLE_SURFACE_SEND: if (surface_ready) state<=SAMPLE_SURFACE_WAIT;
                    SAMPLE_SURFACE_WAIT: if (surface_valid) begin
                        if (!valid_length) begin
                            record[64 +:32]<=1; record[511:96]<=0; state<=PAD;
                        end else state<=SAMPLE_STORE;
                    end
                    SAMPLE_STORE: begin
                        if (!initialized[sample_address])
                            initialized_count<=initialized_count+13'd1;
                        initialized[sample_address]<=1; record[128 +:32]<=1; state<=PAD;
                    end
                    PAD: if (age==deadline) begin running<=0; state<=HOLD; end
                    RUN_DEADLINE_LOW: begin
                        deadline_low<=deadline_sum[15:0]; deadline_carry<=deadline_sum[16];
                        state<=RUN_DEADLINE_HIGH;
                    end
                    RUN_DEADLINE_HIGH: begin
                        deadline<={run_product[31:16]+{15'd0,deadline_carry},deadline_low};
                        state<=RUN_PREFIX;
                    end
                    RUN_PREFIX: if (age==63) begin slot_clock<=0; state<=TEMP_REQUEST; end
                    TEMP_REQUEST: state<=TEMP_CAPTURE;
                    TEMP_CAPTURE: begin center_sample<=sample_q; state<=MOTION_X_SEND; end
                    MOTION_X_SEND: if (motion_ready) state<=MOTION_X_WAIT;
                    MOTION_X_WAIT: if (motion_valid) begin
                        previous_x<=motion_result; state<=MOTION_Y_SEND;
                    end
                    MOTION_Y_SEND: if (motion_ready) state<=MOTION_Y_WAIT;
                    MOTION_Y_WAIT: if (motion_valid) begin
                        previous_y<=motion_result;
                        history_in_bounds<=history_valid && previous_x[31:16]==0 &&
                            motion_result[31:16]==0 && previous_x[15:0]<{9'd0,width} &&
                            motion_result[15:0]<{9'd0,height};
                        state<=HISTORY_PRODUCT;
                    end
                    HISTORY_PRODUCT: begin
                        address_product<=history_in_bounds ?
                            {9'd0,width}*previous_y[15:0] : 16'd0;
                        state<=HISTORY_ADDRESS;
                    end
                    HISTORY_ADDRESS: begin
                        history_address<=history_in_bounds ?
                            address_product[12:0]+previous_x[12:0] : 13'd0;
                        state<=HISTORY_REQUEST;
                    end
                    HISTORY_REQUEST: state<=HISTORY_CAPTURE;
                    HISTORY_CAPTURE: begin
                        previous_history<=history_q; history_accepted<=0;
                        if (history_in_bounds) state<=HISTORY_SURFACE_SEND;
                        else state<=TEMP_CHANNEL_SEND;
                    end
                    HISTORY_SURFACE_SEND: if (surface_ready) state<=HISTORY_SURFACE_WAIT;
                    HISTORY_SURFACE_WAIT: if (surface_valid) begin
                        history_accepted<=surface_depth_ok && surface_dot>=17'd58982;
                        state<=TEMP_CHANNEL_SEND;
                    end
                    TEMP_CHANNEL_SEND: if (&channel_ready) state<=TEMP_CHANNEL_WAIT;
                    TEMP_CHANNEL_WAIT: if (&channel_valid) begin
                        if (|channel_error) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else begin
                            next_history<={center_sample[80 +:96],center_sample[48 +:32],
                                channel_second[1],channel_second[0],channel_mean[1],channel_mean[0]};
                            plane_work<={channel_variance[1],channel_variance[0],
                                channel_luma[1],channel_luma[0]};
                            state<=TEMP_STORE;
                        end
                    end
                    TEMP_STORE: begin
                        accepted_map[pixel]<=history_accepted;
                        if (history_accepted) accepted_count<=accepted_count+13'd1;
                        state<=SLOT_WAIT;
                    end
                    SLOT_WAIT: if (slot_clock==slot_limit-14'd1) begin
                        slot_clock<=0;
                        if (pixel==pixels-13'd1) begin
                            pixel<=0; x<=0; y<=0;
                            if (!spatial) begin
                                spatial<=1; pass<=0; state<=CENTER_REQUEST;
                            end else if (pass!=2) begin
                                pass<=pass+2'd1; plane_source<=!plane_source;
                                state<=CENTER_REQUEST;
                            end else begin
                                plane_source<=!plane_source; history_bank<=!history_bank;
                                history_valid<=1; history_width<=width; history_height<=height;
                                frame_active<=0; running<=0; terminal<=0; record<=0;
                                record[0 +:32]<=32'h50000020;
                                record[32 +:32]<=command[0 +:32];
                                record[160 +:128]<=final_plane_q;
                                record[288 +:32]<={31'd0,accepted_map[0]};
                                emit_pixel<=0; emit_x<=0; emit_y<=0; state<=HOLD;
                            end
                        end else begin
                            pixel<=pixel+13'd1;
                            if (x==width-7'd1) begin x<=0; y<=y+7'd1; end
                            else x<=x+7'd1;
                            if (spatial) state<=CENTER_REQUEST;
                            else state<=TEMP_REQUEST;
                        end
                    end
                    CENTER_REQUEST: state<=CENTER_CAPTURE;
                    CENTER_CAPTURE: begin
                        center_sample<=sample_q; center_plane<=plane_q;
                        state<=CENTER_CHANNEL_SEND;
                    end
                    CENTER_CHANNEL_SEND: if (&channel_ready) state<=CENTER_CHANNEL_WAIT;
                    CENTER_CHANNEL_WAIT: if (&channel_valid) begin
                        if (|channel_error) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else begin tap_x<=0; tap_y<=0; state<=TAP_COORDINATES; end
                    end
                    TAP_COORDINATES: begin
                        tap_coordinate_x<=$signed({9'd0,x})+(offset_x<<<pass);
                        tap_coordinate_y<=$signed({9'd0,y})+(offset_y<<<pass);
                        kernel<=kernel_value(tap_x)*kernel_value(tap_y);
                        state<=TAP_PRODUCT;
                    end
                    TAP_PRODUCT: begin
                        if (tap_coordinate_x<0 || tap_coordinate_y<0 ||
                            tap_coordinate_x>=$signed({9'd0,width}) ||
                            tap_coordinate_y>=$signed({9'd0,height})) state<=TAP_NEXT;
                        else begin
                            address_product<={9'd0,width}*$unsigned(tap_coordinate_y);
                            state<=TAP_ADDRESS;
                        end
                    end
                    TAP_ADDRESS: begin
                        tap_address<=address_product[12:0]+tap_coordinate_x[12:0];
                        state<=TAP_REQUEST;
                    end
                    TAP_REQUEST: state<=TAP_CAPTURE;
                    TAP_CAPTURE: begin
                        tap_sample<=sample_q; tap_plane<=plane_q;
                        if (tap_x==2 && tap_y==2) begin
                            normal_weight<=65536; depth_step<=0; state<=TAP_CHANNEL_SEND;
                        end else state<=TAP_SURFACE_SEND;
                    end
                    TAP_SURFACE_SEND: if (surface_ready) state<=TAP_SURFACE_WAIT;
                    TAP_SURFACE_WAIT: if (surface_valid) begin
                        if (!surface_depth_ok || surface_dot<17'd32768) state<=TAP_NEXT;
                        else begin
                            normal_weight<=surface_dot; depth_step<=surface_depth_step;
                            square_iteration<=0; state<=WEIGHT_SQUARE;
                        end
                    end
                    WEIGHT_SQUARE: begin
                        square<=normal_weight[15:0]*normal_weight[15:0];
                        state<=WEIGHT_SELECT;
                    end
                    WEIGHT_SELECT: begin
                        if (!normal_weight[16]) normal_weight<={1'b0,square[31:16]};
                        if (square_iteration==2) state<=TAP_CHANNEL_SEND;
                        else begin square_iteration<=square_iteration+2'd1; state<=WEIGHT_SQUARE; end
                    end
                    TAP_CHANNEL_SEND: if (&channel_ready) state<=TAP_CHANNEL_WAIT;
                    TAP_CHANNEL_WAIT: if (&channel_valid) begin
                        if (|channel_error) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else state<=TAP_NEXT;
                    end
                    TAP_NEXT: begin
                        if (tap_x==4) begin
                            tap_x<=0;
                            if (tap_y==4) state<=NORMALIZE_SEND;
                            else begin tap_y<=tap_y+3'd1; state<=TAP_COORDINATES; end
                        end else begin tap_x<=tap_x+3'd1; state<=TAP_COORDINATES; end
                    end
                    NORMALIZE_SEND: if (&channel_ready) state<=NORMALIZE_WAIT;
                    NORMALIZE_WAIT: if (&channel_valid) begin
                        if (|channel_error) begin
                            record[64 +:32]<=4; record[511:96]<=0; state<=PAD;
                        end else begin
                            plane_work<={channel_variance[1],channel_variance[0],
                                channel_luma[1],channel_luma[0]};
                            state<=SPATIAL_STORE;
                        end
                    end
                    SPATIAL_STORE: state<=SLOT_WAIT;
                    HOLD: if (m_ready) begin
                        if (terminal) state<=IDLE;
                        else if (emit_pixel==pixels-13'd1) state<=COMPLETION_GAP;
                        else begin
                            emit_pixel<=emit_pixel+13'd1;
                            if (emit_x==width-7'd1) begin emit_x<=0; emit_y<=emit_y+7'd1; end
                            else emit_x<=emit_x+7'd1;
                            state<=EMIT_REQUEST;
                        end
                    end
                    EMIT_REQUEST: state<=EMIT_CAPTURE;
                    EMIT_CAPTURE: begin
                        record<=0; record[0 +:32]<=32'h50000020;
                        record[32 +:32]<=command[0 +:32];
                        record[96 +:32]<={25'd0,emit_x}; record[128 +:32]<={25'd0,emit_y};
                        record[160 +:128]<=plane_q;
                        record[288 +:32]<={31'd0,accepted_map[emit_pixel]};
                        terminal<=0; state<=HOLD;
                    end
                    COMPLETION_GAP: begin
                        record<=0; record[0 +:32]<=32'h50000000;
                        record[32 +:32]<=command[0 +:32]; record[96 +:32]<=32'h922;
                        record[128 +:32]<={19'd0,pixels}; record[160 +:32]<=3;
                        record[192 +:32]<={19'd0,accepted_count}; terminal<=1; state<=HOLD;
                    end
                    default: begin
                        record[64 +:32]<=4; record[511:96]<=0; terminal<=1; state<=PAD;
`ifndef SYNTHESIS
                        $fatal(1,"g5_svgf: invalid control state");
`endif
                    end
                endcase
                if (slot_active && slot_clock==slot_limit-14'd1 && state!=SLOT_WAIT) begin
                    record<=0; record[0 +:32]<=32'h50000000;
                    record[32 +:32]<=command[0 +:32]; record[64 +:32]<=4;
                    terminal<=1;
                    if (spatial && pass==2 && pixel==pixels-13'd1) begin
                        running<=0; state<=HOLD;
                    end else state<=PAD;
`ifndef SYNTHESIS
                    $fatal(1,"g5_svgf: computation exceeded fixed pixel slot");
`endif
                end
            end
        end
    end endgenerate
endmodule
