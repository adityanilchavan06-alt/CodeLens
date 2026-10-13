"""Java syntax validation and a simple construct-coverage confidence score."""

from tree_sitter import Language, Parser
import tree_sitter_java


def validate_java(
    java_code: str, coverage: float | None = 1.0
) -> dict[str, object]:
    """Parse generated Java and report syntax errors with a 0-100 score."""
    language = Language(tree_sitter_java.language())
    parser = Parser(language)
    tree = parser.parse(java_code.encode("utf-8"))
    errors: list[str] = []
    _collect_errors(tree.root_node, errors)
    return {
        "is_valid": not errors,
        "errors": errors,
        "confidence": (
            round(max(0.0, min(100.0, coverage * 100.0)), 1)
            if coverage is not None
            else None
        ),
    }


def validate_code(
    source_code: str, target: str, coverage: float | None = 1.0
) -> dict[str, object]:
    """Parse generated source for its selected target language."""
    if target == "java":
        return validate_java(source_code, coverage)

    if target == "cpp":
        import tree_sitter_cpp

        language = Language(tree_sitter_cpp.language())
    elif target == "c":
        import tree_sitter_c

        language = Language(tree_sitter_c.language())
    else:
        raise ValueError(f"Unsupported target language: {target}")

    parser = Parser(language)
    tree = parser.parse(source_code.encode("utf-8"))
    errors: list[str] = []
    _collect_target_errors(tree.root_node, errors, target.upper())
    return {
        "is_valid": not errors,
        "errors": errors,
        "confidence": (
            round(max(0.0, min(100.0, coverage * 100.0)), 1)
            if coverage is not None
            else None
        ),
    }


def _collect_errors(node, errors: list[str]) -> None:
    if node.type == "ERROR" or node.is_missing:
        row, column = node.start_point
        errors.append(f"Line {row + 1}, column {column + 1}: invalid or missing Java syntax.")
    for child in node.children:
        _collect_errors(child, errors)


def _collect_target_errors(node, errors: list[str], language: str) -> None:
    if node.type == "ERROR" or node.is_missing:
        row, column = node.start_point
        errors.append(
            f"Line {row + 1}, column {column + 1}: invalid or missing {language} syntax."
        )
    for child in node.children:
        _collect_target_errors(child, errors, language)
