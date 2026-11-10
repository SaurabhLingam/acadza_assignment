"""Parser tests. Raw snippets are copied verbatim from data/questions.json so the
tests exercise real production markup without depending on any question id."""
from engine.parse import (find_markers, html_to_text, locate_raw, normalize_answer,
                          split_options)

# --- the three MathML samples from docs/data-survey.md -----------------------

COS45 = ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mstyle displaystyle="true"><mrow><mrow>'
         '<mo stretchy="true" fence="true" form="prefix">&#x00028;</mo><mi> cos </mi><msup><mn> 45 </mn><mrow><mo>&#x02218;'
         '</mo></mrow></msup><mo>&#x0003D;</mo><mfrac><mrow><mn> 1 </mn></mrow><mrow><msqrt><mrow><mn> 2 </mn></mrow>'
         '</msqrt></mrow></mfrac><mo stretchy="true" fence="true" form="postfix">&#x00029;</mo></mrow></mrow></mstyle></math>')

FLUX = ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mrow><mfrac><mrow><mi> n </mi><mi> q </mi>'
        '</mrow><mrow><mn> 2 </mn><msub><mi> ε </mi><mrow><mn> 0 </mn></mrow></msub></mrow></mfrac></mrow></math>')

LCR = ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mstyle displaystyle="true"><mrow><mi>V</mi>'
       '<mo>&#x0003D;</mo><msqrt><mrow><msubsup><mi>V</mi><mrow><mi>R</mi></mrow><mrow><mn>2</mn></mrow></msubsup>'
       '<mo>&#x0002B;</mo><msup><mrow><mo stretchy="true" fence="true" form="prefix">&#x00028;</mo><msub><mi>V</mi>'
       '<mrow><mi>L</mi></mrow></msub><mo>&#x02212;</mo><msub><mi>V</mi><mrow><mi>C</mi></mrow></msub>'
       '<mo stretchy="true" fence="true" form="postfix">&#x00029;</mo></mrow><mrow><mn>2</mn></mrow></msup></mrow>'
       '</msqrt></mrow></mstyle></math><math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mstyle '
       'displaystyle="true"><mrow><mo>&#x0003D;</mo><msqrt><mrow><mo stretchy="false">&#x00028;</mo><mn>40</mn><msup>'
       '<mo stretchy="false">&#x00029;</mo><mrow><mn>2</mn></mrow></msup><mo>&#x0002B;</mo><mo stretchy="false">'
       '&#x00028;</mo><mn>60</mn><mo>&#x02212;</mo><mn>30</mn><msup><mo stretchy="false">&#x00029;</mo><mrow><mn>2'
       '</mn></mrow></msup></mrow></msqrt><mo>&#x0003D;</mo><mn>50</mn><mrow><mtext>&#x000A0;</mtext><mi '
       'mathvariant="normal">V</mi></mrow></mrow></mstyle></math>')


def test_mathml_degree_fraction_root():
    assert html_to_text(COS45) == "(cos 45° = 1/√2)"


def test_mathml_fraction_with_subscript_denominator():
    assert html_to_text(FLUX) == "nq/(2ε_0)"


def test_mathml_sqrt_subsup_and_fences():
    assert html_to_text(LCR) == "V = √(V_R^2+(V_L−V_C)^2) = √((40)^2+(60−30)^2) = 50 V"


# --- HTML sup / sub (outside MathML) -----------------------------------------

def test_html_sup_exponent_kept():
    # The throwaway converter dropped <sup>, turning 10^-5 into "10-5" (docs/ai-mistakes.md M-001).
    raw = '<span style="color:#000000">&nbsp;5.7 x 10<sup>-5</sup>/<sup>o</sup>C<br />'
    assert html_to_text(raw) == "5.7 x 10^-5/°C"


def test_html_sup_degree_and_sub():
    assert html_to_text("0<sup>o</sup>C and H<sub>2</sub>O and x<sup>n+1</sup>") == "0°C and H_2O and x^(n+1)"


def test_entities_zero_width_and_nbsp():
    assert html_to_text("<h3>a&nbsp;&nbsp;b​ c\r\n d &minus; e</h3>") == "a b c d − e"


def test_mover_ring_gives_angstrom():
    raw = '<math><mrow><mover><mrow><mi> A </mi></mrow><mrow><mo>∘</mo></mrow></mover></mrow></math>'
    assert html_to_text(raw) == "Å"


def test_lone_ampersand_alignment_marker_dropped():
    raw = '<math><mrow><mi>&amp;</mi><mi>P</mi><mo>=</mo><mn>0</mn></mrow></math>'
    assert html_to_text(raw) == "P = 0"


# --- option splitting --------------------------------------------------------

def test_split_plain_markers_with_unclosed_spans():
    raw = ('<h3><span style="color:#000000">Stem text</h3><h3>(A)<span> <span>100 N<br />(B)<span> 121 N'
           '<span><br />(C)<span> </span><span>99 N<br />(D)</span></span><span> </span><span>None of these</span></h3>')
    sq = split_options(raw)
    assert sq.letters == ("A", "B", "C", "D")
    assert sq.stem_text == "Stem text"
    assert sq.options_text == {"A": "100 N", "B": "121 N", "C": "99 N", "D": "None of these"}


def test_split_markers_inside_math():
    raw = ('<h3>Pick one</h3><h3><math><mrow><mo stretchy="false">(A)</mo></mrow></math> 3.1 V<br />'
           '<mspace linebreak="newline"> <math><mrow><mo stretchy="false">(B)</mo></mrow></math> 2.0 V<br />'
           '<mspace linebreak="newline"> <math><mrow><mo stretchy="false">(C)</mo></mrow></math> 5.1 V<br />'
           '<mspace linebreak="newline"> <math><mrow><mo stretchy="false">(D)</mo></mrow></math> 1.1 V'
           '</mspace></mspace></mspace></h3>')
    sq = split_options(raw)
    assert sq.letters == ("A", "B", "C", "D")
    assert sq.options_text["D"] == "1.1 V"


def test_assertion_label_is_not_an_option_marker():
    raw = ('Assertion (A): waves add. Reason (R): intensities add.<br/>(A) Both true<br/>(B) Both true, '
           'not explanation<br/>(C) A true, R false<br/>(D) A false, R true')
    sq = split_options(raw)
    assert sq.stem_text.startswith("Assertion (A): waves add.")
    assert sq.options_text["A"] == "Both true"
    assert sq.letters == ("A", "B", "C", "D")


def test_marker_inside_tag_attribute_ignored():
    assert [m.letter for m in find_markers('<span title="(A)">x</span>(A) a (B) b')] == ["A", "B"]


def test_three_options_and_blank_option():
    sq = split_options("Q?<br/>(A) 1<br/>(B) 2<br/>(C) 3")
    assert sq.letters == ("A", "B", "C")
    sq = split_options("Q?<br/>(A) 9:16<br/>(B) 2:3<br/>(C) <br />(D) 3:4")
    assert sq.options_text["C"] == ""


def test_integer_question_has_no_options():
    sq = split_options("Find (A) the value", has_options=False)
    assert sq.letters == () and sq.stem_text == "Find (A) the value"


# --- answers -------------------------------------------------------------------

def test_answer_normalisation():
    assert normalize_answer("scq", "C").values == ("C",)
    a = normalize_answer("mcq", ["A, B, D"])
    assert a.values == ("A", "B", "D") and "combined_string" in a.flags
    a = normalize_answer("mcq", ["", "B"])
    assert a.values == ("B",) and "empty_element" in a.flags
    assert normalize_answer("integerQuestion", "3113").values == ("3113",)
    assert "not_numeric" in normalize_answer("integerQuestion", "abc").flags
    assert "letter_without_option" in normalize_answer("scq", "D", ("A", "B", "C")).flags


# --- raw evidence ----------------------------------------------------------------

def test_locate_raw_unique_and_skips_attributes():
    raw = '<math display="inline">x</math> the line is inline here'
    sub, unique = locate_raw(raw, "line", whole_word=True)
    assert unique and "display" not in sub and raw.count(sub) == 1


def test_locate_raw_across_tags():
    raw = "green part of<span style='c'>leaf</span> with veins"
    sub, unique = locate_raw(raw, "ofleaf")
    assert unique and sub == "of<span style='c'>leaf"
