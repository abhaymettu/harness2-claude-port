from csvlite import parse, parse_line


def test_quoted_comma():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_quoted_comma_and_doubled_quote():
    assert parse_line('"say ""hi, there""",x') == ['say "hi, there"', "x"]


def test_several_quoted_commas():
    assert parse_line('"1,000","2,500,000",3') == ["1,000", "2,500,000", "3"]


def test_trailing_empty_field():
    assert parse_line("a,,c,") == ["a", "", "c", ""]


def test_quoted_empty_field():
    assert parse_line('"",x') == ["", "x"]


def test_rows_with_quoted_comma():
    assert parse('name,town\n"Vale, Orrin",Fenmore\n') == [{"name": "Vale, Orrin", "town": "Fenmore"}]


def test_header_with_quoted_comma():
    assert parse('"id","label, long"\n1,x\n') == [{"id": "1", "label, long": "x"}]


def test_blank_lines_skipped():
    assert parse("a,b\n\n1,2\n") == [{"a": "1", "b": "2"}]
