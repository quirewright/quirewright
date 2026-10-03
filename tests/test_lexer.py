from quirewright.core.content.lexer import Lexer, Name, tokenize
from quirewright.core.pdfobj import Ref, parse_object


def kinds(data: bytes):
    return [(t.kind, t.value) for t in tokenize(data)]


def test_numbers_names_strings():
    toks = kinds(b"1 -2.5 .5 /Name /A#20B (str\\)x) <41 42> true null")
    assert toks[0] == ("num", 1)
    assert toks[1] == ("num", -2.5)
    assert toks[2] == ("num", 0.5)
    assert toks[3] == ("name", "Name")
    assert toks[4] == ("name", "A B")
    assert toks[5] == ("str", b"str)x")
    assert toks[6] == ("str", b"AB")
    assert toks[7] == ("bool", True)
    assert toks[8] == ("null", None)


def test_nested_strings_and_escapes():
    toks = kinds(b"(a(b)c) (\\101\\n) (line\r\nbreak)")
    assert toks[0][1] == b"a(b)c"
    assert toks[1][1] == b"A\n"
    assert toks[2][1] == b"line\nbreak"


def test_arrays_dicts_and_offsets():
    data = b"  [1 (x) /N] << /K 1 /L [2 3] >> Tj"
    toks = tokenize(data)
    assert toks[0].value == [1, b"x", Name("N")]
    assert toks[0].start == 2 and data[toks[0].start:toks[0].end] == b"[1 (x) /N]"
    assert toks[1].value == {"K": 1, "L": [2, 3]}
    assert toks[2].kind == "op" and toks[2].value == "Tj"


def test_comments_skipped():
    assert kinds(b"1 % comment\n2") == [("num", 1), ("num", 2)]


def test_inline_image_unfiltered():
    lx = Lexer(b"BI /W 2 /H 1 /BPC 8 /CS /G ID \x01\x02 EI Q")
    while (t := lx.next_token()) is not None:
        if t.value == "ID":
            assert lx.read_inline_image_data({"W": 2, "H": 1, "BPC": 8, "CS": "G"}) == b"\x01\x02"
            break
    assert lx.next_token().value == "Q"


def test_inline_image_filtered_search():
    lx = Lexer(b"BI /W 2 /H 1 /F /Fl ID abcEIdef EI\nQ")
    while (t := lx.next_token()) is not None:
        if t.value == "ID":
            assert lx.read_inline_image_data({"F": "Fl"}) == b"abcEIdef"
            break
    assert lx.next_token().value == "Q"


def test_parse_object_refs():
    obj = parse_object("<< /Type /Font /FontDescriptor 32 0 R /W [0 [600 603]] /Arr [1 0 R 2 0 R] >>")
    assert obj["FontDescriptor"] == Ref(32, 0)
    assert obj["Arr"] == [Ref(1, 0), Ref(2, 0)]
    assert obj["W"] == [0, [600, 603]]
    assert parse_object("5 0 obj << /A 1 >> endobj") == {"A": 1}
