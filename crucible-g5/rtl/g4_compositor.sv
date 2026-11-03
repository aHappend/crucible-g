module g4_compositor (
    input wire clk, rst_n, start_valid,
    output wire start_ready,
    input wire [23:0] start_background,
    input wire [16:0] start_epsilon,
    input wire s_valid,
    output wire s_ready,
    input wire [16:0] s_alpha,
    input wire [23:0] s_rgb,
    input wire finish_valid,
    output wire finish_ready, terminated, m_valid,
    input wire m_ready,
    output wire [31:0] m_rgba,
    output wire [16:0] m_transmittance
);
    localparam IDLE=0, ACTIVE=1, WEIGHT_PRODUCT=2, WEIGHT_ROUND=3,
               COLOR_PRODUCT=4, ACCUMULATE=5, BACKGROUND=6,
               FINAL_SUM=7, QUANTIZE=8, PUBLISH=9, HOLD=10;
    reg [3:0] state;
    reg [23:0] background, rgb;
    reg [16:0] epsilon, transmittance, alpha, weight, next_t;
    reg [33:0] product;
    reg [31:0] rgba;
    wire [34:0] rounded_weight={1'b0,product}+35'd32768;
    genvar ch;
    generate for (ch=0;ch<3;ch=ch+1) begin: channel
        reg [24:0] sample_product, background_product, accumulator;
        reg [25:0] final_sum;
        wire [26:0] rounded_color={1'b0,final_sum}+27'd32768;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                sample_product<=0; background_product<=0; accumulator<=0;
                final_sum<=0; rgba[ch*8 +:8]<=0;
            end else begin
                if (state==IDLE && start_valid) accumulator<=0;
                if (state==COLOR_PRODUCT) sample_product<=weight*rgb[ch*8 +:8];
                if (state==ACCUMULATE) accumulator<=accumulator+sample_product;
                if (state==BACKGROUND)
                    background_product<=transmittance*background[ch*8 +:8];
                if (state==FINAL_SUM)
                    final_sum<={1'b0,accumulator}+{1'b0,background_product};
                if (state==QUANTIZE) begin
                    if (rounded_color[26:16]>11'd255) rgba[ch*8 +:8]<=8'd255;
                    else rgba[ch*8 +:8]<=rounded_color[23:16];
                end
            end
        end
    end endgenerate
    assign start_ready=rst_n && state==IDLE;
    assign terminated=rst_n && state!=IDLE && transmittance<epsilon;
    assign finish_ready=rst_n && state==ACTIVE;
    assign s_ready=finish_ready && !terminated && !finish_valid;
    assign m_valid=rst_n && state==HOLD;
    assign m_rgba=m_valid ? rgba : 32'd0;
    assign m_transmittance=m_valid ? transmittance : 17'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; background<=0; rgb<=0; epsilon<=0;
            transmittance<=0; alpha<=0; weight<=0; next_t<=0;
            product<=0; rgba[31:24]<=0;
        end else begin
            case (state)
                IDLE: if (start_valid) begin
                    background<=start_background; epsilon<=start_epsilon;
                    transmittance<=17'd65536; state<=ACTIVE;
                end
                ACTIVE: begin
                    if (finish_valid) state<=BACKGROUND;
                    else if (s_valid && !terminated) begin
                        alpha<=s_alpha; rgb<=s_rgb; state<=WEIGHT_PRODUCT;
                    end
                end
                WEIGHT_PRODUCT: begin product<=transmittance*alpha; state<=WEIGHT_ROUND; end
                WEIGHT_ROUND: begin weight<=rounded_weight[32:16]; state<=COLOR_PRODUCT; end
                COLOR_PRODUCT: begin next_t<=transmittance-weight; state<=ACCUMULATE; end
                ACCUMULATE: begin transmittance<=next_t; state<=ACTIVE; end
                BACKGROUND: state<=FINAL_SUM;
                FINAL_SUM: state<=QUANTIZE;
                QUANTIZE: begin rgba[31:24]<=8'hff; state<=PUBLISH; end
                PUBLISH: state<=HOLD;
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
