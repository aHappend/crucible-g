module g4_radix_sort #(
    parameter integer MAX_SPLATS=64
) (
    input wire clk, rst_n, cfg_valid,
    output wire cfg_ready,
    input wire [8:0] cfg_count,
    input wire s_valid,
    output wire s_ready,
    input wire [31:0] s_key,
    output wire m_valid,
    input wire m_ready,
    output wire [31:0] m_key,
    output wire [8:0] m_index,
    output wire m_last, done_valid,
    input wire done_ready
);
    localparam LEGAL=MAX_SPLATS>=1 && MAX_SPLATS<=256;
    localparam integer CAPACITY=LEGAL ? MAX_SPLATS : 1;
    localparam IDLE=0, LOAD=1, COUNT_READ=2, COUNT_USE=3, POSITIONS=4,
               SCATTER_READ=5, SCATTER_WRITE=6, PASS_END=7,
               OUTPUT_READ=8, OUTPUT_HOLD=9, DONE=10;
    reg [3:0] state;
    reg [8:0] count, cursor, zeros, position_zero, position_one;
    reg [4:0] bit_index;
    reg bank;
    (* ramstyle="M20K", nomem2reg *) reg [40:0] ping [0:CAPACITY-1];
    (* ramstyle="M20K", nomem2reg *) reg [40:0] pong [0:CAPACITY-1];
    reg [40:0] read_q;
    wire [8:0] scatter_address=read_q[bit_index] ? position_one : position_zero;
    initial if (!LEGAL) $fatal(1,"PARAMETER ERROR: g4_radix_sort capacity");
    assign cfg_ready=rst_n && LEGAL && state==IDLE;
    assign s_ready=rst_n && LEGAL && state==LOAD;
    assign m_valid=rst_n && LEGAL && state==OUTPUT_HOLD;
    assign m_key=m_valid ? read_q[31:0] : 32'd0;
    assign m_index=m_valid ? read_q[40:32] : 9'd0;
    assign m_last=m_valid && cursor+9'd1==count;
    assign done_valid=rst_n && LEGAL && state==DONE;
    always @(posedge clk) begin
        if (rst_n && LEGAL) begin
            if (state==LOAD && s_valid) ping[cursor]<={cursor,s_key};
            if (state==COUNT_READ || state==SCATTER_READ || state==OUTPUT_READ) begin
                if (bank) read_q<=pong[cursor];
                else read_q<=ping[cursor];
            end
            if (state==SCATTER_WRITE) begin
                if (bank) ping[scatter_address]<=read_q;
                else pong[scatter_address]<=read_q;
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; count<=0; cursor<=0; zeros<=0;
            position_zero<=0; position_one<=0; bit_index<=0; bank<=0;
        end else if (LEGAL) begin
            case (state)
                IDLE: if (cfg_valid) begin
                    count<=cfg_count; cursor<=0; zeros<=0; bank<=0; bit_index<=0;
                    if (cfg_count==0) state<=DONE;
                    else state<=LOAD;
                end
                LOAD: if (s_valid) begin
                    if (cursor+9'd1==count) begin
                        cursor<=0;
                        if (count==1) state<=OUTPUT_READ;
                        else state<=COUNT_READ;
                    end else cursor<=cursor+9'd1;
                end
                COUNT_READ: state<=COUNT_USE;
                COUNT_USE: begin
                    if (!read_q[bit_index]) zeros<=zeros+9'd1;
                    if (cursor+9'd1==count) begin cursor<=0; state<=POSITIONS; end
                    else begin cursor<=cursor+9'd1; state<=COUNT_READ; end
                end
                POSITIONS: begin
                    position_zero<=0; position_one<=zeros; state<=SCATTER_READ;
                end
                SCATTER_READ: state<=SCATTER_WRITE;
                SCATTER_WRITE: begin
                    if (read_q[bit_index]) position_one<=position_one+9'd1;
                    else position_zero<=position_zero+9'd1;
                    if (cursor+9'd1==count) state<=PASS_END;
                    else begin cursor<=cursor+9'd1; state<=SCATTER_READ; end
                end
                PASS_END: begin
                    bank<=!bank; cursor<=0; zeros<=0;
                    if (bit_index==31) state<=OUTPUT_READ;
                    else begin bit_index<=bit_index+5'd1; state<=COUNT_READ; end
                end
                OUTPUT_READ: state<=OUTPUT_HOLD;
                OUTPUT_HOLD: if (m_ready) begin
                    if (cursor+9'd1==count) state<=DONE;
                    else begin cursor<=cursor+9'd1; state<=OUTPUT_READ; end
                end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
