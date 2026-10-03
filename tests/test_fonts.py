from quirewright.core.fonts import FontInfo, builtin_font_name, parse_cmap
from quirewright.core.pdfobj import Resolver, parse_object


class FakeDoc:
    def __init__(self, objects: dict[int, str], streams: dict[int, bytes] | None = None):
        self.objects = objects
        self.streams = streams or {}

    def xref_object(self, xref, compressed=False):
        return self.objects[xref]

    def xref_stream(self, xref):
        return self.streams[xref]


def test_parse_cmap():
    data = b"""1 begincodespacerange <0000> <ffff> endcodespacerange
    2 beginbfchar <0001> <0050> <0002> <0072> endbfchar
    1 beginbfrange <0010> <0012> <0061> endbfrange
    1 beginbfrange <0020> <0021> [<0041> <00420043>] endbfrange"""
    ranges, mapping = parse_cmap(data)
    assert ranges[0].nbytes == 2
    assert mapping[1] == "P" and mapping[2] == "r"
    assert mapping[0x10] == "a" and mapping[0x12] == "c"
    assert mapping[0x20] == "A" and mapping[0x21] == "BC"


def test_simple_font_with_widths_and_differences():
    doc = FakeDoc({
        1: "<< /Type /Font /Subtype /TrueType /BaseFont /ABCDEF+Foo /FirstChar 65 /LastChar 67 /Widths [500 600 700] /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [66 /eacute] >> /FontDescriptor 2 0 R >>",
        2: "<< /Ascent 800 /Descent -200 /Flags 32 /FontFile2 3 0 R >>",
    })
    fi = FontInfo.load(doc, Resolver(doc), parse_object("1 0 R"), "F1")
    assert fi.is_subset and fi.embedded
    assert fi.width(65) == 0.5 and fi.width(67) == 0.7
    assert fi.ascent == 0.8 and fi.descent == -0.2
    assert fi.unicode(65) == "A" and fi.unicode(66) == "é"
    assert fi.encode("AéC") == b"ABC"
    assert fi.encode("Z") is None  # subset: only glyphs known to exist
    assert fi.decode(b"AB") == [(65, 1), (66, 1)]


def test_non_subset_simple_font_encodes_ascii():
    doc = FakeDoc({1: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"})
    fi = FontInfo.load(doc, Resolver(doc), parse_object("1 0 R"), "F1")
    assert fi.builtin == "helv"
    assert fi.encode("Hello") == b"Hello"
    assert 0.2 < fi.width(ord("H")) < 1.0
    assert fi.width(ord("i")) < fi.width(ord("W"))


def test_type0_font():
    doc = FakeDoc(
        {
            1: "<< /Type /Font /Subtype /Type0 /BaseFont /OZVTRD+DejaVuSans /Encoding /Identity-H /DescendantFonts [2 0 R] /ToUnicode 3 0 R >>",
            2: "<< /Subtype /CIDFontType2 /DW 1000 /W [ 0 [600 603 411] 5 7 500 ] /FontDescriptor 4 0 R >>",
            4: "<< /Ascent 900 /Descent -230 /FontFile2 9 0 R >>",
        },
        {3: b"1 begincodespacerange <0000> <ffff> endcodespacerange 2 beginbfchar <0001> <0050> <0002> <0072> endbfchar"},
    )
    fi = FontInfo.load(doc, Resolver(doc), parse_object("1 0 R"), "f0")
    assert fi.is_type0
    assert fi.decode(b"\x00\x01\x00\x02") == [(1, 2), (2, 2)]
    assert fi.width(1) == 0.603 and fi.width(6) == 0.5 and fi.width(99) == 1.0
    assert fi.unicode(1) == "P"
    assert fi.encode("Pr") == b"\x00\x01\x00\x02"
    assert fi.encode("x") is None
    assert fi.is_word_space(32, 2) is False


def test_builtin_name_mapping():
    assert builtin_font_name("Arial-BoldMT") == "hebo"
    assert builtin_font_name("TimesNewRomanPS-ItalicMT") == "tiit"
    assert builtin_font_name("CourierNew") == "cour"
    assert builtin_font_name("ABCDEF+Symbol") == "symb"
