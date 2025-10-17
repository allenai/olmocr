#!/usr/bin/env python3
"""
Extract inner-most spans and their bounding boxes, and the MathML output,
from rendered LaTeX equations using Playwright and KaTeX.
Caching is maintained via a SHA1-based hash stored in a sqlite database.

Requirements:
    pip install playwright
    python -m playwright install chromium

    Place katex.min.css and katex.min.js in the same directory as this script
"""

import atexit
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import threading
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# --- New SQLite Cache Implementation ---


class EquationCache:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Use the same cache directory as before
            cache_dir = pathlib.Path.home() / ".cache" / "olmocr" / "bench" / "equations"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cache_dir / "cache.db")
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            # Added an 'error' column to store rendering errors
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS equations (
                    eq_hash TEXT PRIMARY KEY,
                    mathml TEXT,
                    spans TEXT,
                    error TEXT
                )
            """
            )
            conn.commit()
            conn.close()

    def load(self, eq_hash: str) -> Optional["RenderedEquation"]:
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT mathml, spans, error FROM equations WHERE eq_hash = ?", (eq_hash,))
            row = c.fetchone()
            conn.close()
        if row:
            mathml, spans_json, error = row
            if error:
                # In error cases, we return an instance with error set and no spans.
                return RenderedEquation(mathml=mathml, spans=[], error=error)
            else:
                spans_data = json.loads(spans_json)
                spans = [
                    SpanInfo(
                        text=s["text"],
                        bounding_box=BoundingBox(
                            x=s["boundingBox"]["x"],
                            y=s["boundingBox"]["y"],
                            width=s["boundingBox"]["width"],
                            height=s["boundingBox"]["height"],
                        ),
                    )
                    for s in spans_data
                ]
                return RenderedEquation(mathml=mathml, spans=spans)
        return None

    def save(self, eq_hash: str, rendered_eq: "RenderedEquation"):
        spans_data = [
            {
                "text": span.text,
                "boundingBox": {
                    "x": span.bounding_box.x,
                    "y": span.bounding_box.y,
                    "width": span.bounding_box.width,
                    "height": span.bounding_box.height,
                },
            }
            for span in rendered_eq.spans
        ]
        spans_json = json.dumps(spans_data)
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO equations (eq_hash, mathml, spans, error) VALUES (?, ?, ?, ?)",
                (eq_hash, rendered_eq.mathml, spans_json, rendered_eq.error),
            )
            conn.commit()
            conn.close()

    def clear(self):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM equations")
            conn.commit()
            conn.close()


# Global instance of EquationCache
equation_cache = EquationCache()

# --- End SQLite Cache Implementation ---


@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float


@dataclass
class SpanInfo:
    text: str
    bounding_box: BoundingBox


@dataclass
class RenderedEquation:
    mathml: str
    spans: List[SpanInfo]
    error: Optional[str] = None  # New field to store error messages if rendering fails


def get_equation_hash(equation, bg_color="white", text_color="black", font_size=24):
    """
    Calculate SHA1 hash of the equation string and rendering parameters.
    """
    params_str = f"{equation}|{bg_color}|{text_color}|{font_size}"
    return hashlib.sha1(params_str.encode("utf-8")).hexdigest()


# Thread-local storage for browser instances in the executor threads
_thread_local = threading.local()

# Global thread pool executor with a fixed number of threads
# Each thread will maintain its own Playwright instance
_render_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="playwright-render")


def _cleanup_executor():
    """Cleanup function to shutdown the executor on exit."""
    _render_executor.shutdown(wait=False)


# Register cleanup at exit
atexit.register(_cleanup_executor)


def _cleanup_playwright(playwright, browser):
    print("Cleaning up", playwright)
    try:
        browser.close()
    except Exception:
        pass
    try:
        playwright.stop()
    except Exception:
        pass


class _BrowserOwner:
    def __init__(self):
        p = sync_playwright().start()
        b = p.chromium.launch()
        self.p = p
        self.browser = b
        self._closed = False
        # Important: don't capture `self` or globals in the finalizer
        self._finalizer = weakref.finalize(self, _cleanup_playwright, p, b)

    def close_now(self):
        if not self._closed:
            self._closed = True
            self._finalizer()  # idempotent; runs at most once


def _get_thread_local_browser():
    """Get or create a browser instance for the current thread."""
    owner = getattr(_thread_local, "owner", None)
    if owner is None:
        owner = _BrowserOwner()
        _thread_local.owner = owner
    return owner


def _render_in_executor(equation, bg_color, text_color, font_size, use_cache, debug_dom, eq_hash):
    """
    Function to be run in the executor thread pool.
    Each thread maintains its own Playwright instance.
    """
    owner = _get_thread_local_browser()
    ctx = owner.browser.new_context(viewport={"width": 800, "height": 400})
    try:
        return _do_render(ctx, equation, bg_color, text_color, font_size, debug_dom)
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def _do_render(context, equation, bg_color, text_color, font_size, debug_dom):
    """
    Internal rendering function that uses a provided browser context.
    """
    # Escape the equation for use in a JavaScript string.
    escaped_equation = json.dumps(equation)

    # Get local paths for KaTeX files.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    katex_css_path = os.path.join(script_dir, "katex.min.css")
    katex_js_path = os.path.join(script_dir, "katex.min.js")

    if not os.path.exists(katex_css_path) or not os.path.exists(katex_js_path):
        raise FileNotFoundError(f"KaTeX files not found. Please ensure katex.min.css and katex.min.js are in {script_dir}")

    # Create a new page.
    page = context.new_page()

    # Basic HTML structure for rendering.
    page_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: {bg_color};
                color: {text_color};
            }}
            #equation-container {{
                padding: 0;
                font-size: {font_size}px;
            }}
        </style>
    </head>
    <body>
        <div id="equation-container"></div>
    </body>
    </html>
    """
    page.set_content(page_html)
    page.add_style_tag(path=katex_css_path)
    page.add_script_tag(path=katex_js_path)
    page.wait_for_load_state("networkidle", timeout=0)

    katex_loaded = page.evaluate("typeof katex !== 'undefined'")
    if not katex_loaded:
        page.close()
        raise RuntimeError("KaTeX library failed to load. Check your katex.min.js file.")

    try:
        error_message = page.evaluate(
            f"""
        () => {{
            try {{
                katex.render({escaped_equation}, document.getElementById("equation-container"), {{
                    displayMode: true,
                    throwOnError: true
                }});
                return null;
            }} catch (error) {{
                console.error("KaTeX error:", error.message);
                return error.message;
            }}
        }}
        """
        )
    except PlaywrightError as ex:
        print(escaped_equation)
        error_message = str(ex)
        page.close()
        raise

    if error_message:
        print(f"Error rendering equation: '{equation}'")
        print(error_message)
        # Return error result
        page.close()
        return RenderedEquation(mathml=error_message, spans=[], error=error_message)

    page.wait_for_selector(".katex", state="attached", timeout=0)

    if debug_dom:
        katex_dom_html = page.evaluate(
            """
        () => {
            return document.getElementById("equation-container").innerHTML;
        }
        """
        )
        print("\n===== KaTeX DOM HTML =====")
        print(katex_dom_html)

    # Extract inner-most spans with non-whitespace text.
    spans_info = page.evaluate(
        """
    () => {
        const spans = Array.from(document.querySelectorAll('span'));
        const list = [];
        spans.forEach(span => {
            if (span.children.length === 0 && /\\S/.test(span.textContent)) {
                const rect = span.getBoundingClientRect();
                list.push({
                    text: span.textContent.trim(),
                    boundingBox: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    }
                });
            }
        });
        return list;
    }
    """
    )

    if debug_dom:
        print("\n===== Extracted Span Information =====")
        print(spans_info)

    # Extract MathML output (if available) from the KaTeX output.
    mathml = page.evaluate(
        """
        () => {
            const mathElem = document.querySelector('.katex-mathml math');
            return mathElem ? mathElem.outerHTML : "";
        }
        """
    )

    page.close()

    rendered_eq = RenderedEquation(
        mathml=mathml,
        spans=[
            SpanInfo(
                text=s["text"],
                bounding_box=BoundingBox(
                    x=s["boundingBox"]["x"],
                    y=s["boundingBox"]["y"],
                    width=s["boundingBox"]["width"],
                    height=s["boundingBox"]["height"],
                ),
            )
            for s in spans_info
        ],
    )

    return rendered_eq


def render_equation(
    equation,
    bg_color="white",
    text_color="black",
    font_size=24,
    use_cache=True,
    debug_dom=False,
):
    """
    Render a LaTeX equation using Playwright and KaTeX, extract the inner-most span elements
    along with their bounding boxes, and extract the MathML output generated by KaTeX.

    This function uses a ThreadPoolExecutor with a fixed number of threads to prevent
    resource leaks from unbounded thread creation.
    """
    # Calculate hash for caching.
    eq_hash = get_equation_hash(equation, bg_color, text_color, font_size)

    # Try to load from SQLite cache.
    if use_cache:
        cached = equation_cache.load(eq_hash)
        if cached is not None:
            return cached

    # Submit the rendering task to the thread pool executor
    future = _render_executor.submit(_render_in_executor, equation, bg_color, text_color, font_size, use_cache, debug_dom, eq_hash)

    # Wait for the result
    rendered_eq = future.result()

    # Save to cache if successful and caching is enabled
    if use_cache and rendered_eq and not rendered_eq.error:
        equation_cache.save(eq_hash, rendered_eq)

    return rendered_eq


def compare_rendered_equations(reference: RenderedEquation, hypothesis: RenderedEquation) -> bool:
    """
    Compare two RenderedEquation objects.
    First, check if the normalized MathML of the hypothesis is contained within that of the reference.
    If not, perform a neighbor-based matching on the spans.
    """
    from bs4 import BeautifulSoup

    def extract_inner(mathml: str) -> str:
        try:
            soup = BeautifulSoup(mathml, "xml")
            semantics = soup.find("semantics")
            if semantics:
                inner_parts = [str(child) for child in semantics.contents if getattr(child, "name", None) != "annotation"]
                return "".join(inner_parts)
            else:
                return str(soup)
        except Exception as e:
            print("Error parsing MathML with BeautifulSoup:", e)
            print(mathml)
            return mathml

    def normalize(s: str) -> str:
        return re.sub(r"\s+", "", s)

    reference_inner = normalize(extract_inner(reference.mathml))
    hypothesis_inner = normalize(extract_inner(hypothesis.mathml))
    if reference_inner in hypothesis_inner:
        return True

    H, R = reference.spans, hypothesis.spans
    H = [span for span in H if span.text != "\u200b"]
    R = [span for span in R if span.text != "\u200b"]

    def expand_span_info(span_info: SpanInfo) -> list[SpanInfo]:
        total_elems = len(span_info.text)
        return [
            SpanInfo(
                c,
                BoundingBox(
                    span_info.bounding_box.x + (span_info.bounding_box.width * index) / total_elems,
                    span_info.bounding_box.y,
                    span_info.bounding_box.width / total_elems,
                    span_info.bounding_box.height,
                ),
            )
            for index, c in enumerate(span_info.text)
        ]

    H = [span for sublist in H for span in expand_span_info(sublist)]
    R = [span for sublist in R for span in expand_span_info(sublist)]

    candidate_map = {}
    for i, hspan in enumerate(H):
        candidate_map[i] = [j for j, rsp in enumerate(R) if rsp.text == hspan.text]
        if not candidate_map[i]:
            return False

    def compute_neighbors(spans, tol=5):
        neighbors = {}
        for i, span in enumerate(spans):
            cx = span.bounding_box.x + span.bounding_box.width / 2
            cy = span.bounding_box.y + span.bounding_box.height / 2
            up = down = left = right = None
            up_dist = down_dist = left_dist = right_dist = None
            for j, other in enumerate(spans):
                if i == j:
                    continue
                ocx = other.bounding_box.x + other.bounding_box.width / 2
                ocy = other.bounding_box.y + other.bounding_box.height / 2
                if ocy < cy and abs(ocx - cx) <= tol:
                    dist = cy - ocy
                    if up is None or dist < up_dist:
                        up = j
                        up_dist = dist
                if ocy > cy and abs(ocx - cx) <= tol:
                    dist = ocy - cy
                    if down is None or dist < down_dist:
                        down = j
                        down_dist = dist
                if ocx < cx and abs(ocy - cy) <= tol:
                    dist = cx - ocx
                    if left is None or dist < left_dist:
                        left = j
                        left_dist = dist
                if ocx > cx and abs(ocy - cy) <= tol:
                    dist = ocx - cx
                    if right is None or dist < right_dist:
                        right = j
                        right_dist = dist
            neighbors[i] = {"up": up, "down": down, "left": left, "right": right}
        return neighbors

    hyp_neighbors = compute_neighbors(H)
    ref_neighbors = compute_neighbors(R)

    n = len(H)
    used = [False] * len(R)
    assignment = {}

    def backtrack(i):
        if i == n:
            return True
        for cand in candidate_map[i]:
            if used[cand]:
                continue
            assignment[i] = cand
            used[cand] = True
            valid = True
            for direction in ["up", "down", "left", "right"]:
                hyp_nb = hyp_neighbors[i].get(direction)
                ref_nb = ref_neighbors[cand].get(direction)
                if hyp_nb is not None:
                    expected_text = H[hyp_nb].text
                    if ref_nb is None:
                        valid = False
                        break
                    if hyp_nb in assignment:
                        if assignment[hyp_nb] != ref_nb:
                            valid = False
                            break
                    else:
                        if R[ref_nb].text != expected_text:
                            valid = False
                            break
            if valid:
                if backtrack(i + 1):
                    return True
            used[cand] = False
            del assignment[i]
        return False

    return backtrack(0)


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


if __name__ == "__main__":
    unittest.main()
