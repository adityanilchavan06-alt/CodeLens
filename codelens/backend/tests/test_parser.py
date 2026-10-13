import pytest

from app.parser import ParseError, build_ast


@pytest.mark.parametrize(
    "code,node_type",
    [
        ("x = 1", "Assign"),
        ("if x:\n    y = 1\nelse:\n    y = 2", "If"),
        ("for i in range(3):\n    print(i)", "For"),
        ("while x < 3:\n    x = x + 1", "While"),
        ("def add(a, b):\n    return a + b", "FunctionDef"),
        ("def greet(name='Ada'):\n    return name", "FunctionDef"),
        ("items = [1, 2]\nitems.append(3)", "Call"),
        ('name = "Ada"\nshort = name[0:2]', "Slice"),
        ('person = {"name": "Ada", "age": 36}\nprint(person["name"])', "Dict"),
        ('name = "Ada"\nprint(f"Hello, {name}!")', "JoinedStr"),
        ("class Student:\n    def show(self):\n        print('hi')", "ClassDef"),
        ("def greet(name: str):\n    return name", "FunctionDef"),
        ("try:\n    value = None\nexcept Exception as error:\n    print(error)", "Try"),
        ('lines = [f"{key}: {value}" for key, value in counts.items()]', "ListComp"),
        ('print(f"{average:.2f}")', "JoinedStr"),
    ],
)
def test_supported_syntax_becomes_nested_ast(code, node_type):
    result = build_ast(code)
    assert result["type"] == "Module"
    assert node_type in _node_types(result)


def test_parser_accepts_single_unfiltered_list_comprehensions():
    result = build_ast("values = [item for item in range(3)]")
    assert "ListComp" in _node_types(result)


@pytest.mark.parametrize(
    "code,message",
    [
        ("value = 1 if True else 2", "unsupported construct 'IfExp'"),
        ("while True:\n    break\nelse:\n    pass", "loop else clauses are not supported"),
        ("def outer():\n    def inner():\n        return 1", "nested function definitions are not supported"),
        ("def greet(name: list[str]):\n    return name", "decorators and annotations are not supported"),
        ("for value in 3:\n    print(value)", "for loops must use range"),
        ('print(f"{number:>5}")', "only fixed-point f-string formats"),
        ('print(f"{name!r}")', "f-string !r and !a conversions are not supported"),
        (
            "try:\n    pass\nexcept Exception as first:\n    pass\nexcept Exception as second:\n    pass",
            "only one except handler is supported",
        ),
        ("class Child(Base):\n    def show(self):\n        pass", "class inheritance"),
        ("class Student:\n    def show():\n        pass", "first parameter"),
        ("class Student:\n    name = 'Ada'", "classes may contain only method definitions"),
    ],
)
def test_parser_rejects_unsupported_features_with_a_line(code, message):
    with pytest.raises(ParseError, match=message):
        build_ast(code)


def test_parser_accepts_iteration_over_named_values():
    assert build_ast("def reverse(s):\n    for char in s:\n        print(char)\n")


def _node_types(node):
    return [node["type"]] + [
        descendant
        for child in node.get("children", [])
        for descendant in _node_types(child)
    ]
