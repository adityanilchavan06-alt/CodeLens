"""Rule-based generation for C and C++ from the supported Python subset."""

import ast

from .translator import TranslationError


_OPERATORS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "/",
    ast.Mod: "%",
    ast.Pow: None,
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.UAdd: "+",
    ast.USub: "-",
    ast.Not: "!",
    ast.And: "&&",
    ast.Or: "||",
}


class NativeTranslator:
    def __init__(self, code: str, target: str, symbols: list[dict]) -> None:
        self.code = code
        self.target = target
        self.symbols = {
            (str(symbol["scope"]), str(symbol["name"])): str(symbol["inferred_type"])
            for symbol in symbols
        }
        self.lines: list[str] = []
        self.source_map: list[int | None] = []
        self.indent = 0
        self.scope = "global"
        self.current_source_line: int | None = None
        self.char_iterators: set[str] = set()
        self.has_numeric_lists = False

    @property
    def cpp(self) -> bool:
        return self.target == "cpp"

    def translate(self) -> str:
        try:
            tree = ast.parse(self.code)
        except SyntaxError as exc:
            raise TranslationError(f"Line {exc.lineno or 1}: {exc.msg}") from exc

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                raise TranslationError(
                    f"Line {node.lineno}: classes are not supported for {self.target.upper()} output."
                )
            if isinstance(node, ast.ListComp):
                raise TranslationError(
                    f"Line {node.lineno}: list comprehensions are not supported for {self.target.upper()} output."
                )
            if isinstance(node, ast.Dict):
                raise TranslationError(
                    f"Line {node.lineno}: dictionaries are not supported for {self.target.upper()} output."
                )
        self.char_iterators = {
            node.target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and isinstance(node.iter, ast.Name)
            and any(
                name == node.target.id and inferred == "str"
                for (_, name), inferred in self.symbols.items()
            )
        }
        self.has_numeric_lists = any(
            inferred.startswith("list[")
            for inferred in self.symbols.values()
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                raise TranslationError(
                    f"Line {node.lineno}: f-strings are not supported for {self.target.upper()} output."
                )

        self._line("#include <stdio.h>")
        self._line("#include <stdlib.h>")
        self._line("#include <math.h>")
        if self.cpp:
            self._line("#include <iostream>")
            self._line("#include <string>")
            self._line("#include <limits>")
            self._line("#include <vector>")
            self._line("#include <utility>")
        else:
            self._line("#include <stdbool.h>")
            self._line("#include <string.h>")

        uses_input = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "input"
            for node in ast.walk(tree)
        )
        if uses_input:
            self._input_helpers()
        if self.has_numeric_lists and not self.cpp:
            self._line("typedef struct { int *data; size_t length; } PyIntArray;")
        if any(isinstance(node, ast.Tuple) for node in ast.walk(tree)) and not self.cpp:
            self._line("typedef struct { int first; int second; } PyIntPair;")
        if not self.cpp:
            self._string_helpers()

        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        global_names = [
            name for (scope, name), inferred in self.symbols.items()
            if scope == "global" and inferred not in {"function", "range"}
        ]
        for name in global_names:
            self._line(f"{self._type(self._symbol_type(name, 'global'))} {self._name(name)};")
        if global_names:
            self._line("")
        for function in functions:
            self._line(self._signature(function) + ";")
        if functions:
            self._line("")
        for function in functions:
            self._function(function)
        self.scope = "global"
        self.current_source_line = None
        self._line("int main(void) {")
        self.indent += 1
        for statement in tree.body:
            if isinstance(statement, ast.FunctionDef):
                continue
            if self._is_main_guard(statement):
                for guarded_statement in statement.body:
                    self._statement(guarded_statement)
                continue
            self._statement(statement)
        self._line("return 0;")
        self.indent -= 1
        self._line("}")
        return "\n".join(self.lines) + "\n"

    def _input_helpers(self) -> None:
        if self.cpp:
            self._line("static std::string read_line(const std::string& prompt) {")
            self.indent += 1
            self._line("std::cout << prompt;")
            self._line("std::string value;")
            self._line("std::getline(std::cin, value);")
            self._line("return value;")
            self.indent -= 1
            self._line("}")
            for name, ctype in (("read_int", "int"), ("read_double", "double")):
                self._line(f"static {ctype} {name}(const std::string& prompt) {{")
                self.indent += 1
                self._line("std::cout << prompt;")
                self._line(f"{ctype} value;")
                self._line("std::cin >> value;")
                self._line("std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\\n');")
                self._line("return value;")
                self.indent -= 1
                self._line("}")
        else:
            self._line("static char* read_line(const char* prompt) {")
            self.indent += 1
            self._line("static char value[4096];")
            self._line("printf(\"%s\", prompt);")
            self._line("if (fgets(value, sizeof(value), stdin) == NULL) return value;")
            self._line("value[strcspn(value, \"\\n\")] = '\\0';")
            self._line("return value;")
            self.indent -= 1
            self._line("}")
            for name, ctype, fmt in (("read_int", "int", "%d"), ("read_double", "double", "%lf")):
                self._line(f"static {ctype} {name}(const char* prompt) {{")
                self.indent += 1
                self._line(f"{ctype} value = 0;")
                self._line("printf(\"%s\", prompt);")
                self._line(f"if (scanf(\"{fmt}\", &value) != 1) exit(EXIT_FAILURE);")
                self._line("int character;")
                self._line("while ((character = getchar()) != '\\n' && character != EOF) {}")
                self._line("return value;")
                self.indent -= 1
                self._line("}")
        self._line("")

    def _string_helpers(self) -> None:
        self._line("static char *py_concat_strings(const char *left, const char *right) {")
        self.indent += 1
        self._line("size_t size = strlen(left) + strlen(right) + 1;")
        self._line("char *result = malloc(size);")
        self._line("if (result == NULL) exit(EXIT_FAILURE);")
        self._line("snprintf(result, size, \"%s%s\", left, right);")
        self._line("return result;")
        self.indent -= 1
        self._line("}")
        self._line("static char *py_concat_char_string(char left, const char *right) {")
        self.indent += 1
        self._line("size_t size = strlen(right) + 2;")
        self._line("char *result = malloc(size);")
        self._line("if (result == NULL) exit(EXIT_FAILURE);")
        self._line("result[0] = left;")
        self._line("memcpy(result + 1, right, size - 1);")
        self._line("return result;")
        self.indent -= 1
        self._line("}")
        self._line("static char *py_concat_string_char(const char *left, char right) {")
        self.indent += 1
        self._line("size_t size = strlen(left) + 2;")
        self._line("char *result = malloc(size);")
        self._line("if (result == NULL) exit(EXIT_FAILURE);")
        self._line("snprintf(result, size, \"%s%c\", left, right);")
        self._line("return result;")
        self.indent -= 1
        self._line("}")
        self._line("")

    def _function(self, node: ast.FunctionDef) -> None:
        self.scope = node.name
        self.current_source_line = node.lineno
        self._line(self._signature(node) + " {")
        self.indent += 1
        arguments = {argument.arg for argument in node.args.args}
        for (scope, name), inferred in self.symbols.items():
            if (
                scope == node.name
                and name not in arguments
                and name not in self.char_iterators
            ):
                self._line(f"{self._type(inferred)} {self._name(name)};")
        for statement in node.body:
            self._statement(statement)
        if self._return_type(node) == "void" and not any(
            isinstance(child, ast.Return) for child in ast.walk(node)
        ):
            self._line("return;")
        self.indent -= 1
        self._line("}")
        self._line("")
        self.scope = "global"

    def _signature(self, node: ast.FunctionDef) -> str:
        if node.args.defaults or node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            raise TranslationError(
                f"Line {node.lineno}: default and variadic function arguments are not supported in {self.target.upper()} output."
            )
        parameters = ", ".join(
            self._parameter_declaration(argument.arg, node.name)
            for argument in node.args.args
        ) or "void"
        return f"{self._return_type(node)} {self._name(node.name)}({parameters})"

    def _parameter_declaration(self, name: str, scope: str) -> str:
        inferred = self._symbol_type(name, scope)
        if inferred.startswith("list[") and self.cpp:
            return f"std::vector<int> {self._name(name)}"
        return f"{self._type(inferred)} {self._name(name)}"

    def _return_type(self, node: ast.FunctionDef) -> str:
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                return self._type(self._expr_type(child.value, node.name))
        return "void"

    def _statement(self, node: ast.stmt) -> None:
        self.current_source_line = getattr(node, "lineno", None)
        if isinstance(node, ast.Assign):
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Tuple)
                and self._expr_type(node.value, self.scope).startswith("tuple[")
            ):
                tuple_size = len(
                    self._expr_type(node.value, self.scope)[6:-1].split(",")
                )
                if len(node.targets[0].elts) != tuple_size or tuple_size != 2:
                    raise TranslationError(
                        f"Line {node.lineno}: tuple unpacking requires two matching items."
                    )
                if self.cpp:
                    temp = "__unpacked_values"
                    self._line(f"auto {temp} = {self._expr(node.value)};")
                    first, second = "first", "second"
                else:
                    temp = "__unpacked_values"
                    self._line(f"PyIntPair {temp} = {self._expr(node.value)};")
                    first, second = "first", "second"
                self._line(
                    f"{self._name(node.targets[0].elts[0].id)} = {temp}.{first};"
                )
                self._line(
                    f"{self._name(node.targets[0].elts[1].id)} = {temp}.{second};"
                )
                return
            if len(node.targets) != 1 or not isinstance(node.targets[0], (ast.Name, ast.Subscript)):
                raise TranslationError(f"Line {node.lineno}: unsupported assignment target.")
            self._line(f"{self._expr(node.targets[0])} = {self._expr(node.value)};")
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            operator = self._operator(node.op, node.lineno)
            self._line(f"{self._name(node.target.id)} {operator}= {self._expr(node.value)};")
        elif isinstance(node, ast.If):
            self._line(f"if ({self._expr(node.test)}) {{")
            self.indent += 1
            for statement in node.body:
                self._statement(statement)
            self.indent -= 1
            if node.orelse:
                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    nested = node.orelse[0]
                    self._line(f"}} else if ({self._expr(nested.test)}) {{")
                    self.indent += 1
                    for statement in nested.body:
                        self._statement(statement)
                    self.indent -= 1
                    if nested.orelse:
                        self._line("} else {")
                        self.indent += 1
                        for statement in nested.orelse:
                            self._statement(statement)
                        self.indent -= 1
                else:
                    self._line("} else {")
                    self.indent += 1
                    for statement in node.orelse:
                        self._statement(statement)
                    self.indent -= 1
            self._line("}")
        elif isinstance(node, ast.For):
            if isinstance(node.iter, ast.Call):
                self._range_loop(node)
            elif isinstance(node.iter, ast.Name) and isinstance(node.target, ast.Name):
                self._iterable_loop(node)
            else:
                raise TranslationError(
                    f"Line {node.lineno}: for loops must use range() or iterate over a variable."
                )
        elif isinstance(node, ast.While):
            self._line(f"while ({self._expr(node.test)}) {{")
            self.indent += 1
            for statement in node.body:
                self._statement(statement)
            self.indent -= 1
            self._line("}")
        elif isinstance(node, ast.Return):
            self._line("return;" if node.value is None else f"return {self._expr(node.value)};")
        elif isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "print":
                self._print(node.value)
            else:
                self._line(self._expr(node.value) + ";")
        elif isinstance(node, ast.Pass):
            self._line(";")
        else:
            raise TranslationError(
                f"Line {getattr(node, 'lineno', 1)}: unsupported statement '{type(node).__name__}'."
            )

    def _range_loop(self, node: ast.For) -> None:
        if not isinstance(node.target, ast.Name) or not (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
        ):
            raise TranslationError(f"Line {node.lineno}: for loops must use range() and a variable target.")
        args = node.iter.args
        if not 1 <= len(args) <= 3:
            raise TranslationError(f"Line {node.lineno}: range() needs one, two, or three arguments.")
        values = [self._expr(argument) for argument in args]
        start, stop, step = ("0", values[0], "1") if len(values) == 1 else (
            values[0], values[1], values[2] if len(values) == 3 else "1"
        )
        name = self._name(node.target.id)
        if len(values) == 3:
            message = "range() step must not be zero\\n"
            if self.cpp:
                self._line(f"if (({step}) == 0) {{ std::cerr << {self._string(message)}; std::exit(EXIT_FAILURE); }}")
            else:
                self._line(f"if (({step}) == 0) {{ fputs({self._string(message)}, stderr); exit(EXIT_FAILURE); }}")
        self._line(f"for ({name} = {start}; ({step}) > 0 ? {name} < {stop} : {name} > {stop}; {name} += {step}) {{")
        self.indent += 1
        for statement in node.body:
            self._statement(statement)
        self.indent -= 1
        self._line("}")

    def _iterable_loop(self, node: ast.For) -> None:
        iterable = self._name(node.iter.id)
        iterable_type = self._symbol_type(node.iter.id, self.scope)
        target = self._name(node.target.id)
        if iterable_type == "str":
            if self.cpp:
                self._line(f"for (char {target} : {iterable}) {{")
            else:
                index = f"__{target}_index"
                self._line(
                    f"for (size_t {index} = 0; {iterable}[{index}] != '\\0'; "
                    f"{index}++) {{"
                )
                self.indent += 1
                self._line(f"char {target} = {iterable}[{index}];")
                for statement in node.body:
                    self._statement(statement)
                self.indent -= 1
                self._line("}")
                return
        elif iterable_type.startswith("list["):
            if self.cpp:
                self._line(f"for (int {target} : {iterable}) {{")
            else:
                self._line(
                    f"for (size_t __{target}_index = 0; "
                    f"__{target}_index < {iterable}.length; __{target}_index++) {{"
                )
                self.indent += 1
                self._line(f"int {target} = {iterable}.data[__{target}_index];")
                for statement in node.body:
                    self._statement(statement)
                self.indent -= 1
                self._line("}")
                return
        else:
            raise TranslationError(
                f"Line {node.lineno}: for-loop value must be a string or list."
            )
        self.indent += 1
        for statement in node.body:
            self._statement(statement)
        self.indent -= 1
        self._line("}")

    def _print(self, node: ast.Call) -> None:
        ending = next(
            (
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "end"
            ),
            "\n",
        )
        if self.cpp:
            pieces = ["std::cout"]
            for index, argument in enumerate(node.args):
                if index:
                    pieces.append(' << " "')
                expression = self._expr(argument)
                if self._expr_type(argument, self.scope) == "bool":
                    expression = f"({expression} ? \"True\" : \"False\")"
                pieces.append(f" << {expression}")
            if ending and ending != "\n":
                pieces.append(f" << {self._string(ending)}")
            if ending == "\n":
                pieces.append(" << std::endl")
            pieces.append(";")
            self._line("".join(pieces))
            return
        formats = []
        arguments = []
        for argument in node.args:
            kind = self._expr_type(argument, self.scope)
            if kind == "str":
                formats.append("%s")
            elif kind == "float":
                formats.append("%g")
            elif kind == "bool":
                formats.append("%s")
            elif kind == "char":
                formats.append("%c")
            elif kind == "int":
                formats.append("%d")
            else:
                raise TranslationError(f"Line {node.lineno}: cannot print values of inferred type '{kind}' in C.")
            expression = self._expr(argument)
            if kind == "bool":
                expression = f"({expression} ? \"True\" : \"False\")"
            arguments.append(expression)
        format_string = " ".join(formats) + ending
        suffix = ", " + ", ".join(arguments) if arguments else ""
        self._line(f"printf({self._string(format_string)}{suffix});")

    def _expr(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return self._string(node.value)
            if node.value is None:
                raise TranslationError(f"Line {node.lineno}: None is not supported.")
            if isinstance(node.value, bool):
                return "true" if self.cpp else ("true" if node.value else "false")
            return repr(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.char_iterators:
                return self._name(node.id)
            return self._name(node.id)
        if isinstance(node, ast.BinOp):
            left, right = self._expr(node.left), self._expr(node.right)
            if isinstance(node.op, ast.Pow):
                return f"pow({left}, {right})"
            if isinstance(node.op, ast.Add) and not self.cpp:
                left_type = self._expr_type(node.left, self.scope)
                right_type = self._expr_type(node.right, self.scope)
                if left_type == "char" and right_type == "str":
                    return f"py_concat_char_string({left}, {right})"
                if left_type == "str" and right_type == "char":
                    return f"py_concat_string_char({left}, {right})"
                if left_type == right_type == "str":
                    return f"py_concat_strings({left}, {right})"
            return f"({left} {self._operator(node.op, node.lineno)} {right})"
        if isinstance(node, ast.UnaryOp):
            return f"({self._operator(node.op, node.lineno)}{self._expr(node.operand)})"
        if isinstance(node, ast.BoolOp):
            return "(" + f" {self._operator(node.op, node.lineno)} ".join(
                self._expr(value) for value in node.values
            ) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise TranslationError(f"Line {node.lineno}: chained comparisons are not supported.")
            operator = node.ops[0]
            left_type = self._expr_type(node.left, self.scope)
            right_type = self._expr_type(node.comparators[0], self.scope)
            if (
                not self.cpp
                and isinstance(operator, (ast.In, ast.NotIn))
                and left_type == "char"
                and right_type == "str"
            ):
                value = (
                    f"(strchr({self._expr(node.comparators[0])}, "
                    f"{self._expr(node.left)}) != NULL)"
                )
                return f"!{value}" if isinstance(operator, ast.NotIn) else value
            if not self.cpp and left_type == right_type == "str" and isinstance(
                operator, (ast.Eq, ast.NotEq)
            ):
                comparison = (
                    f"(strcmp({self._expr(node.left)}, "
                    f"{self._expr(node.comparators[0])}) == 0)"
                )
                return f"!{comparison}" if isinstance(operator, ast.NotEq) else comparison
            if isinstance(operator, (ast.In, ast.NotIn)) and right_type == "str":
                needle = self._expr(node.left)
                if left_type == "str":
                    needle = f"{needle}[0]"
                value = f"({self._expr(node.comparators[0])}.find({needle}) != std::string::npos)"
                return f"!{value}" if isinstance(operator, ast.NotIn) else value
            return f"({self._expr(node.left)} {self._operator(node.ops[0], node.lineno)} {self._expr(node.comparators[0])})"
        if isinstance(node, ast.Subscript):
            container = self._expr(node.value)
            if self._expr_type(node.value, self.scope).startswith("list[") and not self.cpp:
                container += ".data"
            return f"{container}[{self._expr(node.slice)}]"
        if isinstance(node, ast.Tuple):
            values = [self._expr(item) for item in node.elts]
            if len(values) != 2:
                raise TranslationError(f"Line {node.lineno}: only two-item tuples are supported.")
            if self.cpp:
                return f"std::make_pair({values[0]}, {values[1]})"
            return f"(PyIntPair){{{values[0]}, {values[1]}}}"
        if isinstance(node, ast.List):
            values = ", ".join(self._expr(item) for item in node.elts)
            if self.cpp:
                return f"std::vector<int>{{{values}}}"
            if not values:
                values = "0"
            return f"(PyIntArray){{(int[]){{{values}}}, {len(node.elts)}}}"
        if isinstance(node, ast.Call):
            if node.keywords:
                raise TranslationError(
                    f"Line {node.lineno}: keyword arguments are not supported in {self.target.upper()} output."
                )
            if isinstance(node.func, ast.Name):
                name = node.func.id
                if name in {"int", "float", "str"} and len(node.args) == 1:
                    arg = node.args[0]
                    if name == "int" and isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "input":
                        return f"read_int({self._input_prompt(arg)})"
                    if name == "float" and isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "input":
                        return f"read_double({self._input_prompt(arg)})"
                    if name == "str" and isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "input":
                        return f"read_line({self._input_prompt(arg)})"
                    if name == "str":
                        raise TranslationError(
                            f"Line {node.lineno}: str() conversion is only supported for input() in {self.target.upper()} output."
                        )
                    if self._expr_type(arg, self.scope) == "str":
                        raise TranslationError(
                            f"Line {node.lineno}: cannot convert a string variable with {name}() in {self.target.upper()} output."
                        )
                    return f"({self._type(name)} )({self._expr(arg)})"
                if name == "input":
                    return f"read_line({self._input_prompt(node)})"
                if name == "len" and len(node.args) == 1:
                    argument = node.args[0]
                    argument_code = self._expr(argument)
                    argument_type = self._expr_type(argument, self.scope)
                    if argument_type == "str":
                        return (
                            f"{argument_code}.size()"
                            if self.cpp
                            else f"(int)strlen({argument_code})"
                        )
                    if argument_type.startswith("list["):
                        return (
                            f"{argument_code}.size()"
                            if self.cpp
                            else f"(int){argument_code}.length"
                        )
                if name == "print":
                    raise TranslationError(f"Line {node.lineno}: print() must be a standalone statement.")
                return f"{self._name(name)}({', '.join(self._expr(arg) for arg in node.args)})"
        raise TranslationError(
            f"Line {getattr(node, 'lineno', 1)}: unsupported expression '{type(node).__name__}'."
        )

    def _input_prompt(self, node: ast.Call) -> str:
        if node.keywords:
            raise TranslationError(f"Line {node.lineno}: input() keyword arguments are not supported.")
        if not node.args:
            return self._string("")
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            raise TranslationError(f"Line {node.lineno}: input() prompt must be a string literal.")
        return self._expr(node.args[0])

    @staticmethod
    def _is_main_guard(node: ast.stmt) -> bool:
        return (
            isinstance(node, ast.If)
            and not node.orelse
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
        )

    def _expr_type(self, node: ast.expr, scope: str) -> str:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, str):
                return "str"
        if isinstance(node, ast.Name):
            if node.id in self.char_iterators:
                return "char"
            return self._symbol_type(node.id, scope)
        if isinstance(node, ast.Tuple):
            return "tuple[" + ",".join(
                self._expr_type(item, scope) for item in node.elts
            ) + "]"
        if isinstance(node, ast.List):
            item_types = {self._expr_type(item, scope) for item in node.elts}
            return f"list[{item_types.pop()}]" if len(item_types) == 1 else "list[int]"
        if isinstance(node, ast.Subscript):
            value_type = self._expr_type(node.value, scope)
            if value_type == "str":
                return "char"
            if value_type.startswith("list["):
                return value_type[5:-1]
            return "unknown"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "len":
                return "int"
            function = next(
                (
                    statement for statement in ast.parse(self.code).body
                    if isinstance(statement, ast.FunctionDef)
                    and statement.name == node.func.id
                ),
                None,
            )
            if function:
                return next(
                    (
                        self._expr_type(child.value, function.name)
                        for child in ast.walk(function)
                        if isinstance(child, ast.Return) and child.value is not None
                    ),
                    "void",
                )
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, (ast.Div, ast.Pow)):
                return "float"
            if "float" in {self._expr_type(node.left, scope), self._expr_type(node.right, scope)}:
                return "float"
            if isinstance(node.op, ast.Add) and self._expr_type(node.left, scope) == "str":
                return "str"
            return "int"
        if isinstance(node, (ast.Compare, ast.BoolOp)):
            return "bool"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"int", "float", "str"}:
                return {"int": "int", "float": "float", "str": "str"}[node.func.id]
            if node.func.id == "input":
                return "str"
            for child in ast.walk(ast.parse(self.code)):
                if isinstance(child, ast.FunctionDef) and child.name == node.func.id:
                    return next(
                        (
                            self._expr_type(returned.value, child.name)
                            for returned in ast.walk(child)
                            if isinstance(returned, ast.Return)
                            and returned.value is not None
                        ),
                        "void",
                    )
        if isinstance(node, ast.UnaryOp):
            return "bool" if isinstance(node.op, ast.Not) else self._expr_type(node.operand, scope)
        return "unknown"

    def _symbol_type(self, name: str, scope: str) -> str:
        return self.symbols.get((scope, name), self.symbols.get(("global", name), "unknown"))

    def _type(self, inferred: str) -> str:
        if inferred == "float":
            return "double"
        if inferred == "char":
            return "char"
        if inferred == "str":
            return "std::string" if self.cpp else "char*"
        if inferred.startswith("list["):
            return "std::vector<int>" if self.cpp else "PyIntArray"
        if inferred.startswith("tuple["):
            return "std::pair<int, int>" if self.cpp else "PyIntPair"
        if inferred == "bool":
            return "bool" if self.cpp else "bool"
        if inferred == "void":
            return "void"
        if inferred in {"int", "range"}:
            return "int"
        return "int"

    @staticmethod
    def _name(name: str) -> str:
        return f"py_{name}" if name in {
            "auto", "bool", "break", "case", "char", "class", "const",
            "continue", "default", "do", "double", "else", "enum",
            "extern", "false", "float", "for", "goto", "if", "inline",
            "int", "long", "namespace", "new", "nullptr", "private",
            "public", "return", "short", "signed", "sizeof", "static",
            "struct", "switch", "this", "true", "typedef", "union",
            "unsigned", "void", "volatile", "while",
        } else name

    @staticmethod
    def _string(value: str) -> str:
        import json
        return json.dumps(value, ensure_ascii=True)

    @staticmethod
    def _operator(operator: ast.operator | ast.cmpop | ast.boolop | ast.unaryop, line: int) -> str:
        result = _OPERATORS.get(type(operator), "==")
        if result is None:
            return "**"
        if type(operator) not in _OPERATORS:
            raise TranslationError(f"Line {line}: unsupported operator '{type(operator).__name__}'.")
        return result

    def _line(self, value: str) -> None:
        self.lines.append("    " * self.indent + value)
        self.source_map.append(self.current_source_line)


def translate_native(
    code: str, target: str, symbols: list[dict]
) -> str:
    return NativeTranslator(code, target, symbols).translate()


def translate_native_with_map(
    code: str, target: str, symbols: list[dict]
) -> tuple[str, list[int | None]]:
    translator = NativeTranslator(code, target, symbols)
    generated = translator.translate()
    return generated, translator.source_map
