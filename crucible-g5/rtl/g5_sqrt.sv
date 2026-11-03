module g5_sqrt #(
    parameter integer WIDTH=64
) (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [WIDTH-1:0] s_radicand,
    output wire m_valid,
    input wire m_ready,
    output wire [(WIDTH>1 ? WIDTH>>1 : 1)-1:0] m_root
);
    localparam LEGAL=WIDTH>=16 && WIDTH<=192 && (WIDTH & 15)==0;
    generate if (!LEGAL) begin: invalid_parameters
        initial $fatal(1,"PARAMETER ERROR: g5_sqrt WIDTH");
        assign s_ready=0; assign m_valid=0; assign m_root=0;
    end else begin: implementation
        localparam LIMBS=WIDTH>>4, ROOT_WIDTH=WIDTH>>1;
        localparam IDLE=0, SHIFT=1, SUBTRACT=2, DECIDE=3, HOLD=4;
        reg [2:0] state;
        reg [3:0] limb;
        reg [6:0] iteration;
        reg [WIDTH-1:0] radicand, remainder, trial, candidate, difference;
        reg [ROOT_WIDTH-1:0] root;
        reg borrow;
        wire [16:0] sub_limb={1'b0,trial[limb*16 +:16]}-
            {1'b0,candidate[limb*16 +:16]}-{16'd0,borrow};
        assign s_ready=rst_n && state==IDLE;
        assign m_valid=rst_n && state==HOLD;
        assign m_root=m_valid ? root : {ROOT_WIDTH{1'b0}};
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; limb<=0; iteration<=0; radicand<=0;
                remainder<=0; trial<=0; candidate<=0; difference<=0;
                root<=0; borrow<=0;
            end else begin
                case (state)
                    IDLE: if (s_valid) begin
                        radicand<=s_radicand; remainder<=0; root<=0;
                        iteration<=0; state<=SHIFT;
                    end
                    SHIFT: begin
                        trial<={remainder[WIDTH-3:0],radicand[WIDTH-1 -:2]};
                        candidate<={{(ROOT_WIDTH-2){1'b0}},root,2'b01};
                        radicand<={radicand[WIDTH-3:0],2'b00};
                        limb<=0; borrow<=0; state<=SUBTRACT;
                    end
                    SUBTRACT: begin
                        difference[limb*16 +:16]<=sub_limb[15:0];
                        borrow<=sub_limb[16];
                        if (limb==LIMBS-1) state<=DECIDE;
                        else limb<=limb+4'd1;
                    end
                    DECIDE: begin
                        remainder<=borrow ? trial : difference;
                        root<={root[ROOT_WIDTH-2:0],!borrow};
                        if (iteration==ROOT_WIDTH-1) state<=HOLD;
                        else begin iteration<=iteration+7'd1; state<=SHIFT; end
                    end
                    HOLD: if (m_ready) state<=IDLE;
                    default: state<=IDLE;
                endcase
            end
        end
    end endgenerate
endmodule
