"""Simple symbol collection and type inference for the supported subset."""

import ast
from dataclasses import asdict, dataclass

from .parser import ParseError, build_ast


@dataclass
class Symbol:
    name: str
    inferred_type: str
    scope: str
    line: int


MATH_FUNCTIONS = {
    "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "degrees", "radians",
    "log", "log10", "log2", "exp", "floor", "ceil", "fabs", "pow",
    "gcd", "isclose",
}


class SemanticAnalyzer:
    def __init__(self) -> None:
        self.symbols: dict[tuple[str, str], Symbol] = {}
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.functions: set[str] = set()
        self.parameter_types: dict[tuple[str, str], str] = {}
        self.function_nodes: dict[str, ast.FunctionDef] = {}
        self.inferring_functions: set[str] = set()
        self.class_nodes: dict[str, ast.ClassDef] = {}
        self.current_class: str | None = None
        self.scope = "global"

    def analyze(self, tree: ast.Module) -> dict[str, list[dict[str, str | int]] | list[str]]:
        self.functions = {
            statement.name for statement in tree.body if isinstance(statement, ast.FunctionDef)
        }
        self.function_nodes = {
            statement.name: statement for statement in tree.body if isinstance(statement, ast.FunctionDef)
        }
        self.class_nodes = {
            statement.name: statement for statement in tree.body if isinstance(statement, ast.ClassDef)
        }
        for class_name, class_node in self.class_nodes.items():
            self._define(class_name, f"class:{class_name}", class_node.lineno)
        self._prepare_class_fields()
        self._prepare_function_parameters(tree)
        self._statements(tree.body)
        return {
            "symbols": [asdict(symbol) for symbol in self.symbols.values()],
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def _statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.asname:
                        self._define(alias.asname, "module", statement.lineno)
                    else:
                        self._define(alias.name.split(".", 1)[0], "module", statement.lineno)
            elif isinstance(statement, ast.ImportFrom):
                for alias in statement.names:
                    if alias.name == "*":
                        continue
                    imported_name = alias.asname or alias.name
                    self._define(imported_name, "function" if alias.name not in {"*"} else "module", statement.lineno)
            elif isinstance(statement, ast.Assign):
                value_type = self._expression_type(statement.value)
                for target in statement.targets:
                    self._assign(target, value_type)
            elif isinstance(statement, ast.AugAssign):
                value_type = self._expression_type(statement.value)
                current_type = self._expression_type(statement.target)
                self._assign(statement.target, self._combine(current_type, value_type, statement))
            elif isinstance(statement, ast.If):
                self._require_boolean(statement.test)
                self._statements(statement.body)
                self._statements(statement.orelse)
            elif isinstance(statement, ast.For):
                iterable_type = self._expression_type(statement.iter)
                item_type = (
                    "int"
                    if self._is_range(statement.iter)
                    else "str"
                    if iterable_type == "str"
                    else iterable_type[5:-1]
                    if iterable_type.startswith("list[")
                    else "unknown"
                )
                self._assign(statement.target, item_type)
                self._statements(statement.body)
                self._statements(statement.orelse)
            elif isinstance(statement, ast.Try):
                self._statements(statement.body)
                for handler in statement.handlers:
                    if handler.name:
                        self._define(handler.name, "class:Exception", handler.lineno)
                    self._statements(handler.body)
            elif isinstance(statement, ast.While):
                self._require_boolean(statement.test)
                self._statements(statement.body)
                self._statements(statement.orelse)
            elif isinstance(statement, ast.FunctionDef):
                self.functions.add(statement.name)
                self._define(statement.name, "function", statement.lineno)
                old_scope = self.scope
                self.scope = statement.name
                for argument in statement.args.args:
                    inferred = self.parameter_types.get((statement.name, argument.arg), "unknown")
                    self._define(argument.arg, inferred, statement.lineno)
                self._statements(statement.body)
                self.scope = old_scope
            elif isinstance(statement, ast.ClassDef):
                old_scope = self.scope
                old_class = self.current_class
                self.current_class = statement.name
                for method in statement.body:
                    if not isinstance(method, ast.FunctionDef):
                        continue
                    self.scope = f"{statement.name}.{method.name}"
                    self._define("self", f"class:{statement.name}", method.lineno)
                    for argument in method.args.args[1:]:
                        inferred = self.parameter_types.get(
                            (self.scope, argument.arg), "unknown"
                        )
                        self._define(argument.arg, inferred, method.lineno)
                    self._statements(method.body)
                self.scope = old_scope
                self.current_class = old_class
            elif isinstance(statement, ast.Return) and statement.value:
                self._expression_type(statement.value)
            elif isinstance(statement, ast.Expr):
                self._expression_type(statement.value)

    def _expression_type(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "None"
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, str):
                return "str"
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                self._expression_type(value)
            return "str"
        if isinstance(node, ast.FormattedValue):
            return self._expression_type(node.value)
        if isinstance(node, ast.Name):
            if node.id == "__name__":
                return "str"
            symbol = self.symbols.get((self.scope, node.id)) or self.symbols.get(("global", node.id))
            if (
                symbol is None
                and node.id not in self.functions
                and node.id not in self.class_nodes
                and node.id not in {
                    "range", "print", "input", "int", "float", "str", "sum",
                    "dict", "sorted", *MATH_FUNCTIONS,
                }
            ):
                self.errors.append(f"Line {node.lineno}: variable '{node.id}' is not defined.")
                return "unknown"
            return symbol.inferred_type if symbol else "function"
        if isinstance(node, ast.List):
            item_types = {self._expression_type(item) for item in node.elts}
            item_type = item_types.pop() if len(item_types) == 1 else "unknown"
            return f"list[{item_type}]"
        if isinstance(node, ast.Tuple):
            return "tuple[" + ",".join(
                self._expression_type(item) for item in node.elts
            ) + "]"
        if isinstance(node, ast.Dict):
            key_types = {self._expression_type(key) for key in node.keys if key is not None}
            value_types = {self._expression_type(value) for value in node.values}
            key_type = key_types.pop() if len(key_types) == 1 else "unknown"
            value_type = value_types.pop() if len(value_types) == 1 else "unknown"
            if key_type not in {"str", "int", "unknown"}:
                self.errors.append(
                    f"Line {node.lineno}: dictionary keys must be strings or integers."
                )
            return f"dict[{key_type},{value_type}]"
        if isinstance(node, ast.ListComp):
            generator = node.generators[0]
            iterable_type = self._expression_type(generator.iter)
            item_type = (
                iterable_type[5:-1]
                if iterable_type.startswith("list[")
                else "unknown"
            )
            target_names = [
                target
                for target in ast.walk(generator.target)
                if isinstance(target, ast.Name)
            ]
            saved_symbols = {
                (self.scope, target.id): self.symbols.get((self.scope, target.id))
                for target in target_names
            }
            if isinstance(generator.target, ast.Tuple) and item_type.startswith("entry["):
                pair = item_type[6:-1].split(",", 1)
                self._assign(generator.target, f"tuple[{','.join(pair)}]")
            elif isinstance(generator.target, ast.Name):
                self._assign(generator.target, item_type)
            result_type = self._expression_type(node.elt)
            for key, previous in saved_symbols.items():
                if previous is None:
                    self.symbols.pop(key, None)
                else:
                    self.symbols[key] = previous
            return f"list[{result_type}]"
        if isinstance(node, ast.Subscript):
            container_type = self._expression_type(node.value)
            if isinstance(node.slice, ast.Slice):
                self._validate_slice(node.slice, node)
                if container_type == "str":
                    return "str"
                if container_type.startswith("list["):
                    return container_type
                self.errors.append(
                    f"Line {node.lineno}: slices are supported only for strings and lists."
                )
                return "unknown"
            index_type = self._expression_type(node.slice)
            if container_type.startswith("dict["):
                key_type, value_type = self._dict_types(container_type)
                if key_type != "unknown" and index_type != key_type:
                    self.errors.append(
                        f"Line {node.lineno}: dictionary key has type {index_type}; "
                        f"expected {key_type}."
                    )
                return value_type
            if index_type != "int":
                self.errors.append(f"Line {node.lineno}: indexes must be integers.")
            if container_type.startswith("list["):
                return container_type[5:-1]
            if container_type == "str":
                return "str"
            return "unknown"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "range":
                for argument in node.args:
                    argument_type = self._expression_type(argument)
                    if argument_type != "int":
                        if argument_type == "str":
                            message = (
                                "range() arguments must be integers; input() returns text, "
                                "so convert it with int(input(...))."
                            )
                        else:
                            message = "range() arguments must be integers."
                        self.errors.append(f"Line {node.lineno}: {message}")
                return "range"
            if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
                list_type = self._expression_type(node.func.value)
                argument_types = [self._expression_type(argument) for argument in node.args]
                if list_type.startswith("list[") and argument_types:
                    item_type = list_type[5:-1]
                    actual_type = argument_types[0]
                    if item_type != "unknown" and actual_type not in {item_type, "unknown"}:
                        self.errors.append(
                            f"Line {node.lineno}: cannot append a {actual_type} value to a {item_type} list."
                        )
                    receiver = node.func.value
                    if (
                        item_type == "unknown"
                        and isinstance(receiver, ast.Subscript)
                        and not isinstance(receiver.slice, ast.Slice)
                    ):
                        self._refine_dictionary(
                            receiver.value,
                            self._expression_type(receiver.slice),
                            f"list[{actual_type}]",
                        )
                return "None"
            if isinstance(node.func, ast.Attribute):
                receiver_type = self._expression_type(node.func.value)
                if receiver_type == "str" and node.func.attr in {
                    "upper", "lower", "strip", "replace", "startswith", "endswith",
                    "find", "split",
                }:
                    for argument in node.args:
                        actual_type = self._expression_type(argument)
                        if actual_type != "str":
                            self.errors.append(
                                f"Line {node.lineno}: str.{node.func.attr}() arguments "
                                f"must be strings, got {actual_type}."
                            )
                    return "bool" if node.func.attr in {"startswith", "endswith"} else (
                        "int" if node.func.attr == "find"
                        else "list[str]" if node.func.attr == "split"
                        else "str"
                    )
                if receiver_type.startswith("dict[") and node.func.attr == "items":
                    key_type, value_type = self._dict_types(receiver_type)
                    return f"list[entry[{key_type},{value_type}]]"
                if receiver_type.startswith("str") and node.func.attr == "join":
                    for argument in node.args:
                        self._expression_type(argument)
                    return "str"
                if receiver_type.startswith("dict[") and node.func.attr == "get":
                    key_type, value_type = self._dict_types(receiver_type)
                    actual_type = self._expression_type(node.args[0])
                    if key_type != "unknown" and actual_type != key_type:
                        self.errors.append(
                            f"Line {node.lineno}: dictionary key has type {actual_type}; "
                            f"expected {key_type}."
                        )
                    for argument in node.args[1:]:
                        self._expression_type(argument)
                    if value_type == "unknown" and len(node.args) > 1:
                        return self._expression_type(node.args[1])
                    return value_type
                if receiver_type.startswith("list[") and node.func.attr == "append":
                    return "None"
                if receiver_type.startswith("class:"):
                    class_name = receiver_type.split(":", 1)[1]
                    class_node = self.class_nodes.get(class_name)
                    methods = {
                        method.name: method
                        for method in class_node.body
                        if isinstance(method, ast.FunctionDef)
                    } if class_node else {}
                    method = methods.get(node.func.attr)
                    if method is None or node.func.attr == "__init__":
                        self.errors.append(
                            f"Line {node.lineno}: class '{class_name}' has no method "
                            f"'{node.func.attr}'."
                        )
                        return "unknown"
                    expected_count = len(method.args.args) - 1
                    required_count = expected_count - len(method.args.defaults)
                    if not required_count <= len(node.args) <= expected_count:
                        self.errors.append(
                            f"Line {node.lineno}: method '{node.func.attr}' expects "
                            f"{required_count} to {expected_count} argument(s), "
                            f"but got {len(node.args)}."
                        )
                    for argument in node.args:
                        self._expression_type(argument)
                    return self._method_return_type(class_name, method)
                self.errors.append(
                    f"Line {node.lineno}: method calls need an instance of a supported class."
                )
                return "unknown"
            function_name = node.func.id if isinstance(node.func, ast.Name) else ""
            if function_name == "input":
                if len(node.args) > 1:
                    self.errors.append(
                        f"Line {node.lineno}: input() accepts at most one prompt."
                    )
                for argument in node.args:
                    argument_type = self._expression_type(argument)
                    if argument_type != "str":
                        self.errors.append(
                            f"Line {node.lineno}: input() prompt must be a string."
                        )
                return "str"
            if function_name in {"int", "float", "str"}:
                if len(node.args) != 1:
                    self.errors.append(
                        f"Line {node.lineno}: {function_name}() needs exactly one argument."
                    )
                    return {"int": "int", "float": "float", "str": "str"}[function_name]
                argument_type = self._expression_type(node.args[0])
                if function_name in {"int", "float"} and argument_type not in {
                    "int", "float", "str", "unknown",
                }:
                    self.errors.append(
                        f"Line {node.lineno}: {function_name}() cannot convert a {argument_type} value."
                    )
                return {"int": "int", "float": "float", "str": "str"}[function_name]
            if function_name in MATH_FUNCTIONS:
                for argument in node.args:
                    self._expression_type(argument)
                return "float"
            if function_name == "len":
                if len(node.args) != 1:
                    self.errors.append(
                        f"Line {node.lineno}: len() needs exactly one argument."
                    )
                    return "int"
                value_type = self._expression_type(node.args[0])
                if not (
                    value_type == "str"
                    or value_type.startswith("list[")
                    or value_type.startswith("dict[")
                ):
                    self.errors.append(
                        f"Line {node.lineno}: len() supports strings, lists, and dictionaries."
                    )
                return "int"
            if function_name == "sum":
                if len(node.args) != 1:
                    self.errors.append(
                        f"Line {node.lineno}: sum() needs exactly one iterable."
                    )
                    return "unknown"
                iterable_type = self._expression_type(node.args[0])
                if not iterable_type.startswith("list["):
                    self.errors.append(
                        f"Line {node.lineno}: sum() requires a list of numbers."
                    )
                    return "unknown"
                item_type = iterable_type[5:-1]
                if item_type not in {"int", "float", "unknown"}:
                    self.errors.append(
                        f"Line {node.lineno}: sum() requires a list of numbers."
                    )
                    return "unknown"
                return "float" if item_type == "float" else "int"
            if function_name == "sorted":
                if len(node.args) != 1:
                    self.errors.append(
                        f"Line {node.lineno}: sorted() needs exactly one iterable."
                    )
                    return "list[unknown]"
                iterable_type = self._expression_type(node.args[0])
                if not iterable_type.startswith("list["):
                    self.errors.append(
                        f"Line {node.lineno}: sorted() requires a list in this subset."
                    )
                    return "list[unknown]"
                return iterable_type
            if function_name == "dict":
                if len(node.args) != 1:
                    self.errors.append(
                        f"Line {node.lineno}: dict() needs one list of key-value pairs."
                    )
                    return "dict[unknown,unknown]"
                pairs_type = self._expression_type(node.args[0])
                if pairs_type.startswith("list[entry["):
                    return f"dict[{pairs_type[11:-2]}]"
                self.errors.append(
                    f"Line {node.lineno}: dict() requires a list of key-value pairs."
                )
                return "dict[unknown,unknown]"
            if function_name in self.class_nodes:
                class_node = self.class_nodes[function_name]
                constructor = next(
                    (
                        method for method in class_node.body
                        if isinstance(method, ast.FunctionDef) and method.name == "__init__"
                    ),
                    None,
                )
                expected_count = len(constructor.args.args) - 1 if constructor else 0
                required_count = (
                    expected_count - len(constructor.args.defaults)
                    if constructor
                    else 0
                )
                if not required_count <= len(node.args) <= expected_count:
                    self.errors.append(
                        f"Line {node.lineno}: constructor '{function_name}' expects "
                        f"{required_count} to {expected_count} argument(s), "
                        f"but got {len(node.args)}."
                    )
                for argument in node.args:
                    self._expression_type(argument)
                return f"class:{function_name}"
            if function_name == "print":
                for argument in node.args:
                    self._expression_type(argument)
                return "None"
            if function_name in self.functions:
                function = self.function_nodes[function_name]
                expected_count = len(function.args.args)
                required_count = expected_count - len(function.args.defaults)
                if not required_count <= len(node.args) <= expected_count:
                    self.errors.append(
                        f"Line {node.lineno}: function '{function_name}' expects "
                        f"{required_count} to {expected_count} argument(s), "
                        f"but got {len(node.args)}."
                    )
                for parameter, argument in zip(function.args.args, node.args):
                    expected_type = self.parameter_types.get(
                        (function_name, parameter.arg), "unknown"
                    )
                    actual_type = self._expression_type(argument)
                    if (
                        expected_type != "unknown"
                        and actual_type != "unknown"
                        and expected_type != actual_type
                        and {expected_type, actual_type} != {"int", "float"}
                    ):
                        self.errors.append(
                            f"Line {node.lineno}: argument for '{parameter.arg}' has type "
                            f"{actual_type}; expected {expected_type}."
                        )
                return self._function_return_type(function_name)
            for argument in node.args:
                self._expression_type(argument)
            self.errors.append(f"Line {node.lineno}: function '{function_name}' is not defined.")
            return "unknown"
        if isinstance(node, ast.BinOp):
            left = self._expression_type(node.left)
            right = self._expression_type(node.right)
            if isinstance(node.op, (ast.Div, ast.Pow)):
                if left in {"int", "float"} and right in {"int", "float"}:
                    return "float"
                if "unknown" in {left, right}:
                    self.errors.append(
                        f"Line {node.lineno}: cannot infer numeric operand types for this operation."
                    )
                else:
                    self.errors.append(
                        f"Line {node.lineno}: division and exponentiation need numeric operands."
                    )
                return "unknown"
            return self._combine(left, right, node)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                self._expression_type(node.operand)
                return "bool"
            operand_type = self._expression_type(node.operand)
            if operand_type not in {"int", "float"}:
                self.errors.append(
                    f"Line {node.lineno}: unary plus and minus need numeric operands."
                )
                return "unknown"
            return operand_type
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                self._require_boolean(value)
            return "bool"
        if isinstance(node, ast.Compare):
            left_type = self._expression_type(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right_type = self._expression_type(comparator)
                if isinstance(operator, (ast.In, ast.NotIn)):
                    if right_type.startswith("dict["):
                        key_type, _ = self._dict_types(right_type)
                        if key_type != "unknown" and left_type != key_type:
                            self.errors.append(
                                f"Line {node.lineno}: dictionary key has type {left_type}; "
                                f"expected {key_type}."
                            )
                    elif not (right_type.startswith("list[") or right_type == "str"):
                        self.errors.append(
                            f"Line {node.lineno}: the right side of 'in' must be a list, "
                            "string, or dictionary."
                        )
                    elif right_type == "str" and left_type not in {"str", "char"}:
                        self.errors.append(
                            f"Line {node.lineno}: string membership needs a string value on the left."
                        )
                    elif right_type.startswith("list["):
                        item_type = right_type[5:-1]
                        if item_type != "unknown" and left_type != item_type:
                            self.errors.append(
                                f"Line {node.lineno}: list membership value has type "
                                f"{left_type}; expected {item_type}."
                            )
                elif isinstance(operator, (ast.Eq, ast.NotEq)):
                    numeric_types = {"int", "float"}
                    if (
                        left_type != right_type
                        and "unknown" not in {left_type, right_type}
                        and not {left_type, right_type} <= numeric_types
                    ):
                        self.errors.append(
                            f"Line {node.lineno}: equality comparison has incompatible types "
                            f"'{left_type}' and '{right_type}'."
                        )
                elif isinstance(operator, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                    numeric_types = {"int", "float"}
                    if not (
                        left_type in numeric_types and right_type in numeric_types
                    ) and not (left_type == right_type == "str"):
                        self.errors.append(
                            f"Line {node.lineno}: ordered comparisons need matching number or string types."
                        )
                left_type = right_type
            return "bool"
        if isinstance(node, ast.Dict):
            return self._expression_type(node)
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "self" and self.current_class:
                field = self.symbols.get((self.current_class, node.attr))
                if field:
                    return field.inferred_type
                self.errors.append(
                    f"Line {node.lineno}: class '{self.current_class}' has no field '{node.attr}'."
                )
                return "unknown"
            receiver_type = self._expression_type(node.value)
            if receiver_type.startswith("class:"):
                class_name = receiver_type.split(":", 1)[1]
                field = self.symbols.get((class_name, node.attr))
                if field:
                    return field.inferred_type
                class_node = self.class_nodes.get(class_name)
                if class_node and any(
                    isinstance(method, ast.FunctionDef) and method.name == node.attr
                    for method in class_node.body
                ):
                    return "method"
                self.errors.append(
                    f"Line {node.lineno}: class '{class_name}' has no field or method '{node.attr}'."
                )
            return "unknown"
        return "unknown"

    def _assign(self, target: ast.expr, inferred_type: str) -> None:
        if isinstance(target, ast.Tuple):
            if inferred_type.startswith("entry["):
                inferred_type = f"tuple[{inferred_type[6:-1]}]"
            if not inferred_type.startswith("tuple["):
                self.errors.append(
                    f"Line {target.lineno}: unpacking assignment requires a tuple value."
                )
                return
            item_types = inferred_type[6:-1].split(",")
            if len(item_types) != len(target.elts):
                self.errors.append(
                    f"Line {target.lineno}: unpacking assignment has mismatched item counts."
                )
                return
            for item, item_type in zip(target.elts, item_types):
                self._assign(item, item_type)
            return
        if isinstance(target, ast.Name):
            key = (self.scope, target.id)
            old_symbol = self.symbols.get(key)
            if old_symbol and old_symbol.inferred_type not in {inferred_type, "unknown"} and inferred_type != "unknown":
                self.errors.append(
                    f"Line {target.lineno}: variable '{target.id}' changes type from "
                    f"{old_symbol.inferred_type} to {inferred_type}; Java variables have a fixed type."
                )
            self._define(target.id, inferred_type, target.lineno)
        elif isinstance(target, ast.Subscript):
            container_type = self._expression_type(target.value)
            if isinstance(target.slice, ast.Slice):
                self.errors.append(
                    f"Line {target.lineno}: slice assignment is not supported."
                )
                return
            index_type = self._expression_type(target.slice)
            if container_type.startswith("dict["):
                key_type, value_type = self._dict_types(container_type)
                if key_type != "unknown" and index_type != key_type:
                    self.errors.append(
                        f"Line {target.lineno}: dictionary key has type {index_type}; "
                        f"expected {key_type}."
                    )
                if value_type not in {"unknown", inferred_type} and inferred_type != "unknown":
                    self.errors.append(
                        f"Line {target.lineno}: cannot assign a {inferred_type} value "
                        f"to a {value_type} dictionary."
                    )
                self._refine_dictionary(
                    target.value,
                    index_type,
                    inferred_type,
                )
                return
            if not container_type.startswith("list["):
                self.errors.append(
                    f"Line {target.lineno}: indexed assignment requires a list variable."
                )
            elif index_type != "int":
                self.errors.append(f"Line {target.lineno}: list indexes must be integers.")
            else:
                item_type = container_type[5:-1]
                if item_type not in {"unknown", inferred_type} and inferred_type != "unknown":
                    self.errors.append(
                        f"Line {target.lineno}: cannot assign a {inferred_type} value to a {item_type} list."
                    )
        elif isinstance(target, ast.Attribute):
            if (
                isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and self.current_class
            ):
                key = (self.current_class, target.attr)
                old_symbol = self.symbols.get(key)
                if (
                    old_symbol
                    and old_symbol.inferred_type not in {inferred_type, "unknown"}
                    and inferred_type != "unknown"
                ):
                    self.errors.append(
                        f"Line {target.lineno}: field '{target.attr}' changes type from "
                        f"{old_symbol.inferred_type} to {inferred_type}."
                    )
                self.symbols[key] = Symbol(
                    target.attr, inferred_type, self.current_class, target.lineno
                )
            else:
                self.errors.append(
                    f"Line {target.lineno}: attributes can only be assigned through 'self' in a class method."
                )
        else:
            self.errors.append(f"Line {getattr(target, 'lineno', 1)}: unsupported assignment target.")

    def _refine_dictionary(
        self,
        target: ast.expr,
        key_type: str,
        value_type: str,
    ) -> None:
        symbol: Symbol | None = None
        if isinstance(target, ast.Name):
            symbol = (
                self.symbols.get((self.scope, target.id))
                or self.symbols.get(("global", target.id))
            )
        elif (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and self.current_class
        ):
            symbol = self.symbols.get((self.current_class, target.attr))
        if symbol is None or not symbol.inferred_type.startswith("dict["):
            return
        old_key, old_value = self._dict_types(symbol.inferred_type)
        if old_key == "unknown":
            old_key = key_type
        if old_value == "unknown":
            old_value = value_type
        elif old_value.startswith("list[") and old_value.endswith("[unknown]"):
            old_value = value_type if value_type.startswith("list[") else old_value
        symbol.inferred_type = f"dict[{old_key},{old_value}]"

    def _define(self, name: str, inferred_type: str, line: int) -> None:
        self.symbols[(self.scope, name)] = Symbol(name, inferred_type, self.scope, line)

    def _combine(self, left: str, right: str, node: ast.AST) -> str:
        if left == right and left in {"int", "float"}:
            return left
        if {left, right} <= {"int", "float"}:
            return "float"
        if (
            isinstance(node, (ast.BinOp, ast.AugAssign))
            and isinstance(node.op, ast.Mult)
            and {left, right} == {"str", "int"}
        ):
            return "str"
        if {left, right} <= {"str", "char"} and (
            isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
            or isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add)
        ):
            return "str"
        if "unknown" in {left, right}:
            self.errors.append(
                f"Line {getattr(node, 'lineno', 1)}: cannot infer a Java-compatible type "
                "for this arithmetic operation."
            )
            return "unknown"
        self.errors.append(
            f"Line {getattr(node, 'lineno', 1)}: incompatible types '{left}' and '{right}' "
            "for this arithmetic operation."
        )
        return "unknown"

    def _require_boolean(self, node: ast.expr) -> None:
        inferred_type = self._expression_type(node)
        if inferred_type not in {
            "bool", "int", "float", "str", "None", "unknown",
        } and not inferred_type.startswith(("list[", "dict[", "class:")):
            self.errors.append(
                f"Line {getattr(node, 'lineno', 1)}: condition type '{inferred_type}' "
                "cannot be converted to a boolean."
            )

    def _prepare_function_parameters(self, tree: ast.Module) -> None:
        functions = {
            statement.name: statement
            for statement in tree.body
            if isinstance(statement, ast.FunctionDef)
        }
        for statement in _module_scope_statements(tree.body):
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                if isinstance(target, ast.Name):
                    self._define(target.id, self._static_type(statement.value), statement.lineno)

        methods = {
            f"{class_name}.{method.name}": method
            for class_name, class_node in self.class_nodes.items()
            for method in class_node.body
            if isinstance(method, ast.FunctionDef)
        }
        method_scopes = {
            id(function): scope for scope, function in methods.items()
        }
        local_types_by_call: dict[int, dict[str, str]] = {}
        for function in [*functions.values(), *methods.values()]:
            local_types: dict[str, str] = {}
            parameter_offset = 1 if id(function) in method_scopes else 0
            for parameter in function.args.args[parameter_offset:]:
                name = parameter.arg.lower()
                if parameter.annotation is not None:
                    local_types[parameter.arg] = self._annotation_type(parameter.annotation)
                elif name in {
                    "s", "text", "string", "word", "sentence", "line",
                    "endpoint", "method", "ip_address", "timestamp",
                } or name.endswith(("_str", "_line", "_address")):
                    local_types[parameter.arg] = "str"
                elif name in {"arr", "array", "values", "numbers", "nums", "items", "list"}:
                    local_types[parameter.arg] = "list[int]"
            assignments = sorted(
                (
                    node for node in ast.walk(function)
                    if isinstance(node, ast.Assign)
                ),
                key=lambda node: node.lineno,
            )
            for assignment in assignments:
                inferred = self._static_type(assignment.value, local_types)
                for target in assignment.targets:
                    if isinstance(target, ast.Name):
                        local_types[target.id] = inferred
            for call in (
                node for node in ast.walk(function)
                if isinstance(node, ast.Call)
            ):
                local_types_by_call[id(call)] = local_types
        for function in [*functions.values(), *methods.values()]:
            method_scope = method_scopes.get(id(function))
            offset = 1 if method_scope is not None else 0
            parameters = function.args.args[offset:]
            defaults = function.args.defaults
            scope = method_scope or function.name
            for parameter in parameters:
                if parameter.annotation is not None:
                    self._merge_parameter_type(
                        (scope, parameter.arg),
                        self._annotation_type(parameter.annotation),
                    )
            for parameter, default in zip(parameters[len(parameters) - len(defaults):], defaults):
                self._merge_parameter_type(
                    (scope, parameter.arg),
                    self._static_type(default),
                )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                function = functions.get(node.func.id)
                if function is not None:
                    self._merge_call_arguments(
                        function.name,
                        function.args.args,
                        node.args,
                        local_types_by_call.get(id(node)),
                    )
                    class_node = self.class_nodes.get(node.func.id)
                    constructor = next(
                        (
                            method for method in class_node.body
                            if isinstance(method, ast.FunctionDef) and method.name == "__init__"
                        ),
                        None,
                    ) if class_node else None
                    if constructor:
                        self._merge_call_arguments(
                            f"{node.func.id}.__init__",
                            constructor.args.args[1:],
                            node.args,
                            local_types_by_call.get(id(node)),
                        )
                elif node.func.id in self.class_nodes:
                    class_node = self.class_nodes[node.func.id]
                    constructor = next(
                        (
                            method for method in class_node.body
                            if isinstance(method, ast.FunctionDef) and method.name == "__init__"
                        ),
                        None,
                    )
                    if constructor:
                        self._merge_call_arguments(
                            f"{node.func.id}.__init__",
                            constructor.args.args[1:],
                            node.args,
                            local_types_by_call.get(id(node)),
                        )
            elif isinstance(node.func, ast.Attribute):
                class_name = self._static_type(node.func.value)
                class_node = (
                    self.class_nodes.get(class_name.split(":", 1)[1])
                    if class_name.startswith("class:")
                    else None
                )
                if class_node:
                    method = next(
                        (
                            method for method in class_node.body
                            if isinstance(method, ast.FunctionDef)
                            and method.name == node.func.attr
                        ),
                        None,
                    )
                    if method:
                        self._merge_call_arguments(
                            f"{class_node.name}.{method.name}",
                            method.args.args[1:],
                            node.args,
                            local_types_by_call.get(id(node)),
                        )

        for function in [*functions.values(), *methods.values()]:
            scope = method_scopes.get(id(function), function.name)
            offset = 1 if id(function) in method_scopes else 0
            for parameter in function.args.args[offset:]:
                key = (scope, parameter.arg)
                if self.parameter_types.get(key) not in {None, "unknown"}:
                    continue
                name = parameter.arg.lower()
                if (
                    name in {
                        "s", "text", "string", "word", "sentence", "line",
                        "endpoint", "method", "ip_address", "timestamp",
                    }
                    or name.endswith(("_str", "_line", "_address"))
                ):
                    self.parameter_types[key] = "str"
                elif name in {"arr", "array", "values", "numbers", "nums", "items", "list"}:
                    self.parameter_types[key] = "list[int]"
                elif any(
                    isinstance(node, ast.If)
                    and isinstance(node.test, ast.Name)
                    and node.test.id == parameter.arg
                    for node in ast.walk(function)
                ):
                    self.parameter_types[key] = "bool"
                elif name in {
                    "a", "b", "c", "n", "i", "j", "k", "left", "right",
                    "low", "high", "mid", "target", "base", "exp", "year",
                } or any(
                    self._is_numeric_parameter_use(node, parameter.arg)
                    for node in ast.walk(function)
                ):
                    self.parameter_types[key] = "int"

    def _merge_call_arguments(
        self,
        scope: str,
        parameters: list[ast.arg],
        values: list[ast.expr],
        local_types: dict[str, str] | None = None,
    ) -> None:
        for parameter, value in zip(parameters, values):
            self._merge_parameter_type(
                (scope, parameter.arg),
                self._static_type(value, local_types),
            )

    @staticmethod
    def _is_numeric_parameter_use(node: ast.AST, name: str) -> bool:
        references = [
            child for child in ast.walk(node)
            if isinstance(child, ast.Name) and child.id == name
        ]
        if not references:
            return False
        if isinstance(node, (ast.BinOp, ast.AugAssign)):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
            return True
        if isinstance(node, ast.Compare):
            return any(
                isinstance(other, ast.Constant)
                and isinstance(other.value, (int, float))
                and not isinstance(other.value, bool)
                for other in [node.left, *node.comparators]
            )
        return False

    def _merge_parameter_type(self, key: tuple[str, str], inferred: str) -> None:
        previous = self.parameter_types.get(key)
        if previous is None or previous == inferred:
            self.parameter_types[key] = inferred
        elif inferred != "unknown":
            if {previous, inferred} <= {"int", "float"}:
                self.parameter_types[key] = "float"
            else:
                self.parameter_types[key] = "unknown"

    def _prepare_class_fields(self) -> None:
        for class_name, class_node in self.class_nodes.items():
            for method in class_node.body:
                if not isinstance(method, ast.FunctionDef):
                    continue
                for node in ast.walk(method):
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Attribute)
                        and isinstance(node.targets[0].value, ast.Name)
                        and node.targets[0].value.id == "self"
                    ):
                        field = node.targets[0]
                        if isinstance(node.value, ast.Name):
                            inferred = self.parameter_types.get(
                                (f"{class_name}.{method.name}", node.value.id),
                                self._static_type(node.value),
                            )
                        else:
                            inferred = self._static_type(node.value)
                        key = (class_name, field.attr)
                        existing = self.symbols.get(key)
                        if existing and existing.inferred_type not in {inferred, "unknown"}:
                            self.errors.append(
                                f"Line {field.lineno}: field '{field.attr}' has conflicting initial types."
                            )
                        self.symbols[key] = Symbol(
                            field.attr, inferred, class_name, field.lineno
                        )

    def _static_type(
        self,
        node: ast.expr,
        local_types: dict[str, str] | None = None,
    ) -> str:
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "None"
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, str):
                return "str"
        if isinstance(node, ast.JoinedStr):
            return "str"
        if isinstance(node, ast.Name):
            if local_types and node.id in local_types:
                return local_types[node.id]
            symbol = self.symbols.get(("global", node.id))
            return symbol.inferred_type if symbol else "unknown"
        if isinstance(node, ast.UnaryOp):
            return self._static_type(node.operand, local_types)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            builtin_types = {
                "input": "str",
                "int": "int",
                "float": "float",
                "str": "str",
            }
            if node.func.id in builtin_types:
                return builtin_types[node.func.id]
            if node.func.id == "len":
                return "int"
            if node.func.id in self.class_nodes:
                return f"class:{node.func.id}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver_type = self._static_type(node.func.value, local_types)
            if receiver_type == "str":
                if node.func.attr in {"strip", "replace", "join"}:
                    return "str"
                if node.func.attr == "split":
                    return "list[str]"
                if node.func.attr == "find":
                    return "int"
        if isinstance(node, ast.Subscript):
            container_type = self._static_type(node.value, local_types)
            if isinstance(node.slice, ast.Slice):
                if container_type.startswith("list["):
                    return container_type
                if container_type == "str":
                    return "str"
            if container_type.startswith("list["):
                return container_type[5:-1]
            if container_type == "str":
                return "str"
        if isinstance(node, ast.BinOp):
            left = self._static_type(node.left, local_types)
            right = self._static_type(node.right, local_types)
            if isinstance(node.op, (ast.Div, ast.Pow)) or "float" in {left, right}:
                return "float"
            return left if left == right else "unknown"
        if isinstance(node, ast.List):
            item_types = {self._static_type(item, local_types) for item in node.elts}
            return f"list[{item_types.pop()}]" if len(item_types) == 1 else "list[unknown]"
        if isinstance(node, ast.Dict):
            key_types = {
                self._static_type(key, local_types) for key in node.keys if key is not None
            }
            value_types = {self._static_type(value, local_types) for value in node.values}
            key_type = key_types.pop() if len(key_types) == 1 else "unknown"
            value_type = value_types.pop() if len(value_types) == 1 else "unknown"
            return f"dict[{key_type},{value_type}]"
        return "unknown"

    def _annotation_type(self, annotation: ast.expr) -> str:
        if isinstance(annotation, ast.Name):
            if annotation.id in self.class_nodes or annotation.id == "Exception":
                return f"class:{annotation.id}"
            return {
                "int": "int",
                "float": "float",
                "str": "str",
                "bool": "bool",
            }.get(annotation.id, "unknown")
        return "unknown"

    def _validate_slice(self, node: ast.Slice, parent: ast.AST) -> None:
        for bound in (node.lower, node.upper, node.step):
            if bound is not None and self._expression_type(bound) != "int":
                self.errors.append(
                    f"Line {getattr(parent, 'lineno', 1)}: slice bounds must be integers."
                )
        if node.step is not None and not (
            isinstance(node.step, ast.Constant) and node.step.value == 1
        ):
            self.errors.append(
                f"Line {getattr(parent, 'lineno', 1)}: slice steps other than 1 are not supported."
            )
        for bound in (node.lower, node.upper):
            if isinstance(bound, ast.UnaryOp) and isinstance(bound.op, ast.USub):
                self.errors.append(
                    f"Line {getattr(parent, 'lineno', 1)}: negative slice bounds are not supported."
                )

    @staticmethod
    def _dict_types(inferred_type: str) -> tuple[str, str]:
        key_type, _, value_type = inferred_type[5:-1].partition(",")
        return key_type, value_type

    def _method_return_type(self, class_name: str, method: ast.FunctionDef) -> str:
        old_scope = self.scope
        old_class = self.current_class
        self.scope = f"{class_name}.{method.name}"
        self.current_class = class_name
        try:
            return_types = [
                self._expression_type(node.value)
                for node in ast.walk(method)
                if isinstance(node, ast.Return) and node.value is not None
            ]
        finally:
            self.scope = old_scope
            self.current_class = old_class
        if not return_types:
            return "None"
        known_types = set(return_types) - {"unknown", "None"}
        if len(known_types) == 1:
            return known_types.pop()
        if known_types <= {"int", "float"}:
            return "float" if "float" in known_types else "int"
        if not known_types and "None" in return_types:
            return "None"
        return "unknown"

    def _function_return_type(self, name: str) -> str:
        if name in self.inferring_functions:
            return "unknown"
        function = self.function_nodes[name]
        old_scope = self.scope
        self.scope = name
        self.inferring_functions.add(name)
        try:
            return_types = [
                self._expression_type(node.value)
                for node in ast.walk(function)
                if isinstance(node, ast.Return) and node.value is not None
            ]
        finally:
            self.inferring_functions.remove(name)
            self.scope = old_scope
        if not return_types:
            return "None"
        known_types = set(return_types) - {"unknown", "None"}
        if len(known_types) == 1:
            return known_types.pop()
        if known_types <= {"int", "float"}:
            return "float" if "float" in known_types else "int"
        if not known_types and "None" in return_types:
            return "None"
        return "unknown"

    @staticmethod
    def _is_range(node: ast.expr) -> bool:
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range"


def _module_scope_statements(statements: list[ast.stmt]) -> list[ast.stmt]:
    result: list[ast.stmt] = []
    for statement in statements:
        result.append(statement)
        if isinstance(statement, ast.If):
            result.extend(_module_scope_statements(statement.body))
            result.extend(_module_scope_statements(statement.orelse))
    return result


def analyze_code(code: str) -> dict[str, list[dict[str, str | int]] | list[str]]:
    build_ast(code)
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ParseError(f"Line {exc.lineno or 1}: {exc.msg}") from exc
    return SemanticAnalyzer().analyze(tree)
