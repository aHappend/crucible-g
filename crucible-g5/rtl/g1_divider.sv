module g1_divider (
    input wire clk,
    input wire rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire signed [95:0] s_numerator,
    input wire signed [63:0] s_denominator,
    output wire m_valid,
    input wire m_ready,
    output wire signed [95:0] m_quotient,
    output wire signed [63:0] m_remainder
);
    g2_divider limb_divider (
        .clk(clk),.rst_n(rst_n),
        .s_valid(s_valid),.s_ready(s_ready),
        .s_numerator(s_numerator),.s_denominator(s_denominator),
        .m_valid(m_valid),.m_ready(m_ready),
        .m_quotient(m_quotient),.m_remainder(m_remainder)
    );
endmodule
