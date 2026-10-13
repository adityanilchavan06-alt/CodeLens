import pytest

from app.lexer import LexerError, tokenize


def test_tokens_include_positions_and_indentation():
    tokens = tokenize("total = 4\nif total > 2:\n    print(total)")

    assert tokens[0] == {"type": "IDENTIFIER", "value": "total", "line": 1, "column": 1}
    assert any(token["type"] == "INDENT" for token in tokens)
    assert any(token["type"] == "DEDENT" for token in tokens)
    assert tokens[-1]["type"] == "EOF"


def test_lexer_skips_comments_and_blank_lines():
    tokens = tokenize("# comment\n\nx = 2 # inline")
    assert [token["value"] for token in tokens if token["type"] == "IDENTIFIER"] == ["x"]


def test_lexer_reports_illegal_character_location():
    with pytest.raises(LexerError, match="Line 1, column 5: illegal character"):
        tokenize("x = $")


def test_lexer_rejects_inconsistent_indentation():
    with pytest.raises(LexerError, match="indentation does not match"):
        tokenize("if True:\n    x = 1\n  y = 2")


def test_lexer_keeps_numeric_lexemes_and_accepts_decimal_exponents():
    tokens = tokenize("first = 1_000\nsecond = .5\nthird = 1.25e-3")
    numbers = [token["value"] for token in tokens if token["type"] == "NUMBER"]
    assert numbers == ["1_000", ".5", "1.25e-3"]


def test_lexer_recognizes_f_strings_as_single_tokens():
    tokens = tokenize('message = f"Hello, {name}!"')
    formatted_tokens = [token for token in tokens if token["type"] == "FSTRING"]
    assert formatted_tokens == [
        {"type": "FSTRING", "value": 'f"Hello, {name}!"', "line": 1, "column": 11}
    ]


def test_dictionary_braces_are_delimiter_tokens():
    tokens = tokenize('answer = {"value": 42}')
    assert [token["value"] for token in tokens[:7]] == [
        "answer", "=", "{", '"value"', ":", "42", "}"
    ]
    assert [token["type"] for token in tokens[2:7]] == [
        "DELIMITER", "STRING", "DELIMITER", "NUMBER", "DELIMITER"
    ]
