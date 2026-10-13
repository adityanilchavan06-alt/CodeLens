"""A small, hand-written lexer for the Python subset used by CodeLens.

The lexer turns source characters into tokens and tracks indentation, line,
and column information. It is deliberately separate from Python's parser so
the lexical-analysis stage is visible for the compiler-design project.
"""

from dataclasses import asdict, dataclass
import re


KEYWORDS = {
    "and", "def", "elif", "else", "False", "for", "if", "in", "not",
    "or", "return", "True", "while",
}
NUMBER_PATTERN = re.compile(
    r"(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?"
)


@dataclass
class Token:
    type: str
    value: str
    line: int
    column: int

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


class LexerError(ValueError):
    """An invalid character or indentation level in the source code."""


class Lexer:
    def __init__(self, code: str) -> None:
        self.code = code
        self.tokens: list[Token] = []
        self.indents = [0]

    def tokenize(self) -> list[dict[str, str | int]]:
        """Return token records, including logical newlines and dedents."""
        for line_number, source_line in enumerate(self.code.splitlines(), 1):
            line = source_line.rstrip("\r\n")
            stripped = line.lstrip(" \t")
            if not stripped or stripped.startswith("#"):
                continue

            indentation = len(line) - len(stripped)
            if "\t" in line[:indentation]:
                raise LexerError(f"Line {line_number}, column 1: tabs are not supported for indentation.")
            self._adjust_indentation(indentation, line_number)
            self._scan_line(stripped, line_number, indentation)
            self.tokens.append(Token("NEWLINE", "\\n", line_number, len(line) + 1))

        final_line = max(len(self.code.splitlines()), 1)
        while len(self.indents) > 1:
            self.indents.pop()
            self.tokens.append(Token("DEDENT", "", final_line, 1))
        self.tokens.append(Token("EOF", "", final_line, 1))
        return [token.as_dict() for token in self.tokens]

    def _adjust_indentation(self, indentation: int, line_number: int) -> None:
        if indentation > self.indents[-1]:
            self.indents.append(indentation)
            self.tokens.append(Token("INDENT", "", line_number, 1))
        elif indentation < self.indents[-1]:
            while len(self.indents) > 1 and indentation < self.indents[-1]:
                self.indents.pop()
                self.tokens.append(Token("DEDENT", "", line_number, indentation + 1))
            if indentation != self.indents[-1]:
                raise LexerError(
                    f"Line {line_number}, column 1: indentation does not match an outer block."
                )

    def _scan_line(self, line: str, line_number: int, indent: int) -> None:
        index = 0
        while index < len(line):
            char = line[index]
            column = indent + index + 1
            if char.isspace():
                index += 1
                continue
            if char == "#":
                break
            if (
                char in {"f", "F"}
                and index + 1 < len(line)
                and line[index + 1] in {"'", '"'}
            ):
                index = self._scan_string(
                    line, line_number, index + 1, indent, prefix_start=index
                )
                continue
            if char.isalpha() or char == "_":
                end = index + 1
                while end < len(line) and (line[end].isalnum() or line[end] == "_"):
                    end += 1
                value = line[index:end]
                token_type = "KEYWORD" if value in KEYWORDS else "IDENTIFIER"
                self.tokens.append(Token(token_type, value, line_number, column))
                index = end
                continue
            if char.isdigit() or (char == "." and index + 1 < len(line) and line[index + 1].isdigit()):
                match = NUMBER_PATTERN.match(line, index)
                if match is None:
                    raise LexerError(f"Line {line_number}, column {column}: invalid number.")
                value = match.group()
                self.tokens.append(Token("NUMBER", value, line_number, column))
                index = match.end()
                continue
            if char in {"'", '"'}:
                index = self._scan_string(line, line_number, index, indent)
                continue

            operator = next(
                (item for item in ("==", "!=", "<=", ">=", "**", "//", "+=", "-=")
                 if line.startswith(item, index)),
                None,
            )
            if operator:
                self.tokens.append(Token("OPERATOR", operator, line_number, column))
                index += len(operator)
            elif char in "+-*/%<>=(),:[]{}" or char == ".":
                token_type = "DELIMITER" if char in "(),:[]{}" or char == "." else "OPERATOR"
                self.tokens.append(Token(token_type, char, line_number, column))
                index += 1
            else:
                raise LexerError(
                    f"Line {line_number}, column {column}: illegal character {char!r}."
                )

    def _scan_string(
        self,
        line: str,
        line_number: int,
        start: int,
        indent: int,
        prefix_start: int | None = None,
    ) -> int:
        quote = line[start]
        index = start + 1
        while index < len(line):
            if line[index] == "\\":
                index += 2
            elif line[index] == quote:
                token_start = start if prefix_start is None else prefix_start
                value = line[token_start:index + 1]
                token_type = "FSTRING" if prefix_start is not None else "STRING"
                self.tokens.append(Token(token_type, value, line_number, indent + token_start + 1))
                return index + 1
            else:
                index += 1
        raise LexerError(
            f"Line {line_number}, column {indent + start + 1}: unterminated string literal."
        )


def tokenize(code: str) -> list[dict[str, str | int]]:
    """Convenience function used by the API and unit tests."""
    return Lexer(code).tokenize()
