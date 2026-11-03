module g5_divider #(
    parameter integer WIDTH=192
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [WIDTH-1:0] s_numerator, s_denominator,
    output wire m_valid,
    input wire m_ready,
    output wire [WIDTH-1:0] m_quotient, m_remainder,
    output wire m_error
);
    localparam LEGAL=WIDTH>=16 && WIDTH<=384 && (WIDTH & 15)==0;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_divider WIDTH");
        assign s_ready=0; assign m_valid=0;
        assign m_quotient=0; assign m_remainder=0; assign m_error=0;
    end else begin: implementation
        localparam LIMBS=WIDTH>>4;
        localparam IDLE=0, SHIFT=1, SUBTRACT=2, DECIDE=3, HOLD=4;
        reg [2:0] state;
        reg [4:0] limb;
        reg [8:0] iteration;
        reg [WIDTH-1:0] divisor, quotient, remainder, difference;
        reg [WIDTH:0] trial;
        reg borrow, error;
        wire [16:0] sub_limb={1'b0,trial[limb*16 +:16]}-
            {1'b0,divisor[limb*16 +:16]}-{16'd0,borrow};
        wire accept_subtract=trial[WIDTH] || !borrow;
        assign s_ready=rst_n && state==IDLE;
        assign m_valid=rst_n && state==HOLD;
        assign m_quotient=m_valid && !error ? quotient : {WIDTH{1'b0}};
        assign m_remainder=m_valid && !error ? remainder : {WIDTH{1'b0}};
        assign m_error=m_valid && error;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; limb<=0; iteration<=0;
                divisor<=0; quotient<=0; remainder<=0; difference<=0;
                trial<=0; borrow<=0; error<=0;
            end else begin
                case (state)
                    IDLE: if (s_valid) begin
                        divisor<=s_denominator; quotient<=s_numerator;
                        remainder<=0; iteration<=0; error<=s_denominator==0;
                        state<=SHIFT;
                    end
                    SHIFT: begin
                        trial<={remainder,quotient[WIDTH-1]};
                        limb<=0; borrow<=0; state<=SUBTRACT;
                    end
                    SUBTRACT: begin
                        difference[limb*16 +:16]<=sub_limb[15:0];
                        borrow<=sub_limb[16];
                        if (limb==LIMBS-1) state<=DECIDE;
                        else limb<=limb+5'd1;
                    end
                    DECIDE: begin
                        quotient<={quotient[WIDTH-2:0],accept_subtract};
                        remainder<=accept_subtract ? difference : trial[WIDTH-1:0];
                        if (iteration==WIDTH-1) state<=HOLD;
                        else begin iteration<=iteration+9'd1; state<=SHIFT; end
                    end
                    HOLD: if (m_ready) state<=IDLE;
                    default: state<=IDLE;
                endcase
            end
        end
    end endgenerate
endmodule
