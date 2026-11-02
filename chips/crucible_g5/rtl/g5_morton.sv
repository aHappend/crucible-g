module g5_morton (
    input wire clk, rst_n, s_valid,
    output wire s_ready,
    input wire [29:0] s_xyz,
    output wire m_valid,
    input wire m_ready,
    output wire [29:0] m_code
);
    localparam IDLE=0, INTERLEAVE=1, HOLD=2;
    reg [1:0] state;
    reg [29:0] xyz, code;
    wire [29:0] interleaved;
    genvar i;
    generate for (i=0; i<10; i=i+1) begin: axis_bits
        assign interleaved[3*i]=xyz[i];
        assign interleaved[3*i+1]=xyz[10+i];
        assign interleaved[3*i+2]=xyz[20+i];
    end endgenerate
    assign s_ready=rst_n && state==IDLE;
    assign m_valid=rst_n && state==HOLD;
    assign m_code=m_valid ? code : 30'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; xyz<=0; code<=0;
        end else begin
            case (state)
                IDLE: if (s_valid) begin xyz<=s_xyz; state<=INTERLEAVE; end
                INTERLEAVE: begin code<=interleaved; state<=HOLD; end
                HOLD: if (m_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
