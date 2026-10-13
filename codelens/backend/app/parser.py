"""Python AST conversion and supported-subset checks."""

import ast
from typing import Any


class ParseError(ValueError):
    """A syntax error or construct outside the supported Python subset."""


SUPPORTED_NODES = {
    ast.Module, ast.Assign, ast.Name, ast.Constant, ast.JoinedStr, ast.FormattedValue,
    ast.BinOp, ast.UnaryOp, ast.ClassDef,
    ast.BoolOp, ast.Compare, ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler,
    ast.FunctionDef, ast.Lambda, ast.ListComp, ast.comprehension,
    ast.Return, ast.Call, ast.Expr, ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice, ast.Attribute,
    ast.arguments, ast.keyword, ast.Pass, ast.Import, ast.ImportFrom, ast.alias,
    ast.Load, ast.Store, ast.arg, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE,     ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.AugAssign,
    ast.Add, ast.Sub,
}


def build_ast(code: str) -> dict[str, Any]:
    """Parse code with Python's grammar and return a readable nested JSON tree."""
    try:
        root = ast.parse(code)
    except SyntaxError as exc:
        raise ParseError(f"Line {exc.lineno or 1}: {exc.msg}") from exc

    for node in ast.walk(root):
        if type(node) not in SUPPORTED_NODES:
            line = getattr(node, "lineno", 1)
            raise ParseError(f"Line {line}: unsupported construct '{type(node).__name__}'.")
        if isinstance(node, ast.Constant) and node.value is not None and not isinstance(
            node.value, (str, int, float, bool)
        ):
            raise ParseError(f"Line {node.lineno}: unsupported literal value '{node.value}'.")
        if isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            raise ParseError(
                f"Line {node.lineno}: dictionary unpacking is not supported."
            )
        if isinstance(node, ast.FormattedValue):
            if node.format_spec is not None:
                format_spec = "".join(
                    value.value
                    for value in node.format_spec.values
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                )
                if not (
                    format_spec.startswith(".")
                    and format_spec.endswith("f")
                    and format_spec[1:-1].isdigit()
                ):
                    raise ParseError(
                        f"Line {node.lineno}: only fixed-point f-string formats "
                        "such as '.2f' are supported."
                    )
            if node.conversion not in {-1, ord("s")}:
                raise ParseError(
                    f"Line {node.lineno}: f-string !r and !a conversions are not supported."
                )
        if isinstance(node, ast.ClassDef):
            if node not in root.body:
                raise ParseError(f"Line {node.lineno}: nested class definitions are not supported.")
            if node.bases or node.keywords or node.decorator_list:
                raise ParseError(
                    f"Line {node.lineno}: class inheritance, metaclass arguments, and decorators are not supported."
                )
            if not node.body or any(not isinstance(item, ast.FunctionDef) for item in node.body):
                raise ParseError(
                    f"Line {node.lineno}: classes may contain only method definitions."
                )
            for method in node.body:
                if not method.args.args or method.args.args[0].arg != "self":
                    raise ParseError(
                        f"Line {method.lineno}: instance methods must take 'self' as their first parameter."
                    )
        if isinstance(node, ast.Call) and not isinstance(node.func, (ast.Name, ast.Attribute)):
            raise ParseError(f"Line {node.lineno}: unsupported construct 'indirect function call'.")
        if isinstance(node, ast.keyword):
            parent = next(
                (
                    candidate for candidate in ast.walk(root)
                    if isinstance(candidate, ast.Call) and node in candidate.keywords
                ),
                None,
            )
            allowed_print_end = (
                parent
                and isinstance(parent.func, ast.Name)
                and parent.func.id == "print"
                and node.arg == "end"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            allowed_sorted_option = (
                parent
                and isinstance(parent.func, ast.Name)
                and parent.func.id == "sorted"
                and (
                    node.arg == "key"
                    and isinstance(node.value, ast.Lambda)
                    and len(node.value.args.args) == 1
                    or node.arg == "reverse"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, bool)
                )
            )
            if not (allowed_print_end or allowed_sorted_option):
                raise ParseError(f"Line {node.lineno}: keyword arguments are not supported.")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "append" and len(node.args) != 1:
                raise ParseError(f"Line {node.lineno}: list.append() needs exactly one value.")
            if node.func.attr in {"upper", "lower", "strip"} and node.args:
                raise ParseError(
                    f"Line {node.lineno}: str.{node.func.attr}() does not take arguments in this subset."
                )
            if node.func.attr == "split" and len(node.args) > 1:
                raise ParseError(f"Line {node.lineno}: str.split() accepts at most one argument.")
            if node.func.attr in {"startswith", "endswith", "find"} and len(node.args) != 1:
                raise ParseError(
                    f"Line {node.lineno}: str.{node.func.attr}() needs exactly one argument."
                )
            if node.func.attr == "replace" and len(node.args) != 2:
                raise ParseError(
                    f"Line {node.lineno}: str.replace() needs exactly two arguments."
                )
            if node.func.attr == "get" and not 1 <= len(node.args) <= 2:
                raise ParseError(
                    f"Line {node.lineno}: dict.get() needs one or two arguments."
                )
        if (
            isinstance(node, ast.Attribute)
            and node.attr != "append"
            and not isinstance(
                node.value,
                (ast.Name, ast.Subscript, ast.Constant, ast.Attribute),
            )
            and not (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
            )
        ):
            raise ParseError(f"Line {node.lineno}: unsupported attribute '{node.attr}'.")
        if isinstance(node, (ast.For, ast.While)) and node.orelse:
            raise ParseError(f"Line {node.lineno}: loop else clauses are not supported.")
        if isinstance(node, ast.For) and not (
            isinstance(node.target, (ast.Name, ast.Tuple))
            and (
                isinstance(node.iter, ast.Name)
                or (
                    isinstance(node.iter, ast.Call)
                    and (
                        isinstance(node.iter.func, ast.Name)
                        and node.iter.func.id == "range"
                        or isinstance(node.iter.func, ast.Attribute)
                        and node.iter.func.attr == "items"
                    )
                )
            )
        ):
            raise ParseError(
                f"Line {node.lineno}: for loops must use range(), iterate over a variable, "
                "or iterate over dictionary items."
            )
        if isinstance(node, ast.Try) and (
            node.orelse or node.finalbody or len(node.handlers) != 1
        ):
            raise ParseError(
                f"Line {node.lineno}: only one except handler is supported; "
                "try else and finally clauses are not supported."
            )
        if isinstance(node, ast.ExceptHandler) and (
            not isinstance(node.type, ast.Name)
            or node.type.id != "Exception"
            or node.name is None
        ):
            raise ParseError(
                f"Line {node.lineno}: exception handlers must use 'except Exception as name'."
            )
        if isinstance(node, ast.Lambda) and (
            len(node.args.args) != 1 or node.args.vararg or node.args.kwarg
        ):
            raise ParseError(
                f"Line {node.lineno}: lambda expressions must have exactly one parameter."
            )
        if isinstance(node, ast.ListComp) and (
            len(node.generators) != 1
            or node.generators[0].ifs
            or not isinstance(node.generators[0].target, (ast.Name, ast.Tuple))
        ):
            raise ParseError(
                f"Line {node.lineno}: list comprehensions must have one unfiltered generator."
            )
        if isinstance(node, ast.FunctionDef):
            arguments = node.args
            if (
                node.decorator_list
                or node.returns
                or arguments.kw_defaults
                or arguments.vararg
                or arguments.kwarg
                or arguments.posonlyargs
                or any(
                    argument.annotation is not None
                    and not isinstance(argument.annotation, ast.Name)
                    for argument in arguments.args
                )
            ):
                raise ParseError(f"Line {node.lineno}: decorators and annotations are not supported.")
            if any(
                isinstance(child, ast.FunctionDef) and child is not node
                for child in ast.walk(node)
            ):
                raise ParseError(f"Line {node.lineno}: nested function definitions are not supported.")

    return _node_to_dict(root)


def _node_to_dict(node: ast.AST) -> dict[str, Any]:
    children = []
    fields: dict[str, Any] = {}
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            children.append(_node_to_dict(value))
        elif isinstance(value, list):
            children.extend(_node_to_dict(item) for item in value if isinstance(item, ast.AST))
        elif value is not None:
            fields[field_name] = value
    result: dict[str, Any] = {"type": type(node).__name__}
    if hasattr(node, "lineno"):
        result["line"] = node.lineno
    if fields:
        result["fields"] = fields
    if children:
        result["children"] = children
    return result
