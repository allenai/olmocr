import unittest

from olmocr.bench.katex import compare_rendered_equations, render_equation


class TestRenderedEquationComparison(unittest.TestCase):
    def test_exact_match(self):
        eq1 = render_equation("a+b", use_cache=False)
        eq2 = render_equation("a+b", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_whitespace_difference(self):
        eq1 = render_equation("a+b", use_cache=False)
        eq2 = render_equation("a + b", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_not_found(self):
        eq1 = render_equation("c-d", use_cache=False)
        eq2 = render_equation("a+b", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_align_block_contains_needle(self):
        eq_plain = render_equation("a+b", use_cache=False)
        eq_align = render_equation("\\begin{align*}a+b\\end{align*}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq_plain, eq_align))

    def test_align_block_needle_not_in(self):
        eq_align = render_equation("\\begin{align*}a+b\\end{align*}", use_cache=False)
        eq_diff = render_equation("c-d", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq_diff, eq_align))

    def test_big(self):
        ref_rendered = render_equation("\\nabla \\cdot \\mathbf{E} = \\frac{\\rho}{\\varepsilon_0}", use_cache=False, debug_dom=False)
        align_rendered = render_equation(
            """\\begin{align*}\\nabla \\cdot \\mathbf{E} = \\frac{\\rho}{\\varepsilon_0}\\end{align*}""", use_cache=False, debug_dom=False
        )
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_dot_end1(self):
        ref_rendered = render_equation(
            "\\lambda_{g}=\\sum_{s \\in S} \\zeta_{n}^{\\psi(g s)}=\\sum_{i=1}^{k}\\left[\\sum_{s, R s=\\mathcal{I}_{i}} \\zeta_{n}^{\\varphi(g s)}\\right]"
        )
        align_rendered = render_equation(
            "\\lambda_{g}=\\sum_{s \\in S} \\zeta_{n}^{\\psi(g s)}=\\sum_{i=1}^{k}\\left[\\sum_{s, R s=\\mathcal{I}_{i}} \\zeta_{n}^{\\varphi(g s)}\\right]."
        )
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_x_vs_textx(self):
        ref_rendered = render_equation("C_{T}\\left(u_{n}^{T} X_{n}^{\\text {Test }}, \\bar{x}^{\\text {Test }}\\right)")
        align_rendered = render_equation("C_T \\left(u^T_n X^{\\text{Test}}_n,\\overline{ \\text{x}}^{\\text{Test}}\\right)")
        self.assertFalse(compare_rendered_equations(ref_rendered, align_rendered))

    @unittest.skip("There is a debate whether bar and overline should be the same, currently they are not")
    def test_overline(self):
        ref_rendered = render_equation("C_{T}\\left(u_{n}^{T} X_{n}^{\\text {Test }}, \\bar{x}^{\\text {Test }}\\right)")
        align_rendered = render_equation("C_T \\left(u^T_n X^{\\text{Test}}_n,\\overline{ x}^{\\text{Test}}\\right)")
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_parens(self):
        ref_rendered = render_equation("\\left\\{ \\left( 0_{X},0_{Y},-1\\right) \\right\\} ")
        align_rendered = render_equation("\\{(0_{X}, 0_{Y}, -1)\\}")
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_dot_end2(self):
        ref_rendered = render_equation(
            "\\lambda_{g}=\\sum_{s \\in S} \\zeta_{n}^{\\psi(g s)}=\\sum_{i=1}^{k}\\left[\\sum_{s, R s=\\mathcal{I}_{i}} \\zeta_{n}^{\\psi(g s)}\\right]"
        )
        align_rendered = render_equation(
            "\\lambda_g = \\sum_{s \\in S} \\zeta_n^{\\psi(gs)} = \\sum_{i=1}^{k} \\left[ \\sum_{s, Rs = \\mathcal{I}_i} \\zeta_n^{\\psi(gs)} \\right]"
        )
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_lambda(self):
        ref_rendered = render_equation("\\lambda_g = \\lambda_{g'}")
        align_rendered = render_equation("\\lambda_{g}=\\lambda_{g^{\\prime}}")
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_gemini(self):
        ref_rendered = render_equation("u \\in (R/\\operatorname{Ann}_R(x_i))^{\\times}")
        align_rendered = render_equation("u \\in\\left(R / \\operatorname{Ann}_{R}\\left(x_{i}\\right)\\right)^{\\times}")
        self.assertTrue(compare_rendered_equations(ref_rendered, align_rendered))

    def test_fraction_vs_divided_by(self):
        eq1 = render_equation("\\frac{a}{b}", use_cache=False)
        eq2 = render_equation("a / b", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_different_bracket_types(self):
        eq1 = render_equation("\\left[ a + b \\right]", use_cache=False)
        eq2 = render_equation("\\left\\{ a + b \\right\\}", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_inline_vs_display_style_fraction(self):
        eq1 = render_equation("\\frac{1}{2}", use_cache=False)
        eq2 = render_equation("\\displaystyle\\frac{1}{2}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_matrix_equivalent_forms(self):
        eq1 = render_equation("\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}", use_cache=False)
        eq2 = render_equation("\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_different_matrix_types(self):
        eq1 = render_equation("\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}", use_cache=False)
        eq2 = render_equation("\\begin{bmatrix} a & b \\\\ c & d \\end{bmatrix}", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_thinspace_vs_regular_space(self):
        eq1 = render_equation("a \\, b", use_cache=False)
        eq2 = render_equation("a \\: b", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    @unittest.skip("Currently these compare to the same thing, because they use the symbol 'x' with a different span class and thus font")
    def test_mathbf_vs_boldsymbol(self):
        eq1 = render_equation("\\mathbf{x}", use_cache=False)
        eq2 = render_equation("\\boldsymbol{x}", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_assert_subtle_square_root(self):
        eq1 = render_equation("A N'P' = \\int \\beta d\\alpha = \\frac{2}{3\\sqrt{3} a}\\int (\\alpha - 2a)^{\\frac{3}{2}} d\\alpha", use_cache=False)
        eq2 = render_equation("AN'P' = \\int \\beta \\, d\\alpha = \\frac{2}{3 \\sqrt{3a}} \\int (a - 2a)^{\\frac{3}{2}} d\\alpha")
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_text_added(self):
        eq1 = render_equation("A N'P' = \\int \\beta d\\alpha = \\frac{2}{3\\sqrt{3} a}\\int (\\alpha - 2a)^{\\frac{3}{2}} d\\alpha", use_cache=False)
        eq2 = render_equation("AN'P' = \\int \\beta  d\\alpha = \\frac{2}{3 \\sqrt{3} a} \\int (\\alpha - 2a)^{\\frac{3}{2}} d\\alpha")
        self.assertTrue(compare_rendered_equations(eq1, eq2))

        eq1 = render_equation("A N'P' = \\int \\beta d\\alpha = \\frac{2}{3\\sqrt{3} a}\\int (\\alpha - 2a)^{\\frac{3}{2}} d\\alpha", use_cache=False)
        eq2 = render_equation("\\text{area evolute } AN'P' = \\int \\beta  d\\alpha = \\frac{2}{3 \\sqrt{3} a} \\int (\\alpha - 2a)^{\\frac{3}{2}} d\\alpha")
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_tensor_notation_equivalent(self):
        eq1 = render_equation("T_{ij}^{kl}", use_cache=False)
        eq2 = render_equation("T^{kl}_{ij}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_partial_derivative_forms(self):
        eq1 = render_equation("\\frac{\\partial f}{\\partial x}", use_cache=False)
        eq2 = render_equation("\\frac{\\partial_f}{\\partial_x}", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_equivalent_sin_forms_diff_parens(self):
        eq1 = render_equation("\\sin(\\theta)", use_cache=False)
        eq2 = render_equation("\\sin \\theta", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_aligned_multiline_equation(self):
        eq1 = render_equation("\\begin{align*} a &= b \\\\ c &= d \\end{align*}", use_cache=False)
        eq2 = render_equation("\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_subscript_order_invariance(self):
        eq1 = render_equation("x_{i,j}", use_cache=False)
        eq2 = render_equation("x_{j,i}", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_hat_vs_widehat(self):
        eq1 = render_equation("\\hat{x}", use_cache=False)
        eq2 = render_equation("\\widehat{x}", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_equivalent_integral_bounds(self):
        eq1 = render_equation("\\int_{a}^{b} f(x) dx", use_cache=False)
        eq2 = render_equation("\\int\\limits_{a}^{b} f(x) dx", use_cache=False)
        # Could go either way honestly?
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_equivalent_summation_notation(self):
        eq1 = render_equation("\\sum_{i=1}^{n} x_i", use_cache=False)
        eq2 = render_equation("\\sum\\limits_{i=1}^{n} x_i", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_different_symbol_with_same_appearance(self):
        eq1 = render_equation("\\phi", use_cache=False)
        eq2 = render_equation("\\varphi", use_cache=False)
        self.assertFalse(compare_rendered_equations(eq1, eq2))

    def test_aligned_vs_gathered(self):
        eq1 = render_equation("\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}", use_cache=False)
        eq2 = render_equation("\\begin{gathered} a = b \\\\ c = d \\end{gathered}", use_cache=False)
        # Different whitespacing, should be invariant to that.
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_identical_but_with_color1(self):
        eq1 = render_equation("a + b", use_cache=False)
        eq2 = render_equation("\\color{black}{a + b}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_identical_but_with_color2(self):
        eq1 = render_equation("a + b", use_cache=False)
        eq2 = render_equation("\\color{black}{a} + \\color{black}{b}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

        eq1 = render_equation("a + b", use_cache=False)
        eq2 = render_equation("\\color{red}{a} + \\color{black}{b}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_newcommand_expansion(self):
        eq1 = render_equation("\\alpha + \\beta", use_cache=False)
        eq2 = render_equation("\\newcommand{\\ab}{\\alpha + \\beta}\\ab", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))

    def test_tech_report_examples(self):
        ref = render_equation("C_T \\left(u^T_n X^{\\text{Test}}_n,\\overline{ x}^{\\text{Test}}\\right)", use_cache=False)
        model_a = render_equation("C_{T}\\left(u_{n}^{T} X_{n}^{\\text{Test }}, \\overline{x}^{\\text {Test }}\\right)", use_cache=False)
        model_b = render_equation("C_T \\left(u^T_n X^{\\text{Test}}_n,\\overline{ \\text{x}}^{\\text{Test}}\\right)", use_cache=False)
        self.assertTrue(compare_rendered_equations(ref, model_a))
        self.assertTrue(compare_rendered_equations(ref, model_b))

    def test_viks_equation(self):
        eq1 = render_equation("s_{r,s}=\\begin{cases} 2 \\text{ if } r-s=2,4 \\text{ mod 4},\\\\ 1 \\text{ if } r-s=1,3 \\text{ mod 4}. \\end{cases}", use_cache=False)
        eq2 = render_equation("s_{r,s}=\\begin{cases} 2 & \\text{if } r-s=2,4 \\text{ mod } 4, \\\\ 1 & \\text{if } r-s=1,3 \\text{ mod } 4. \\end{cases}", use_cache=False)
        self.assertTrue(compare_rendered_equations(eq1, eq2))
 