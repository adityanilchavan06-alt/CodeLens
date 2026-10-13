from app.semantic import analyze_code


def test_semantic_analysis_infers_types_and_function_scope():
    result = analyze_code("count = 3\nname = 'Ada'\ndef show(flag):\n    local = flag")
    symbols = {(item["name"], item["scope"]): item["inferred_type"] for item in result["symbols"]}

    assert symbols[("count", "global")] == "int"
    assert symbols[("name", "global")] == "str"
    assert symbols[("local", "show")] == "unknown"
    assert result["errors"] == []


def test_semantic_analysis_reports_undefined_names_and_type_changes():
    result = analyze_code("value = 1\nvalue = 'text'\nprint(missing)")

    assert any("changes type" in error for error in result["errors"])
    assert any("missing" in error for error in result["errors"])


def test_semantic_analysis_checks_list_items_and_function_arguments():
    list_result = analyze_code("numbers = [1, 2]\nnumbers.append('three')")
    assert any("cannot append" in error for error in list_result["errors"])

    call_result = analyze_code("def double(value):\n    return value - 2\nresult = double('wrong')")
    assert any("incompatible types" in error for error in call_result["errors"])


def test_semantic_analysis_accepts_omitted_default_function_arguments():
    result = analyze_code(
        "def greet(name, greeting='Hello'):\n"
        "    print(greeting + ', ' + name)\n"
        "greet('Ada')"
    )

    assert result["errors"] == []


def test_semantic_analysis_still_checks_required_function_arguments():
    result = analyze_code(
        "def greet(name, greeting='Hello'):\n"
        "    print(greeting + ', ' + name)\n"
        "greet()"
    )

    assert any("expects 1 to 2 argument(s), but got 0" in error for error in result["errors"])


def test_semantic_analysis_accepts_python_truthy_conditions():
    result = analyze_code("count = 1\nif count:\n    print(count)")
    assert result["errors"] == []


def test_semantic_analysis_requires_numeric_operations_and_integer_indexes():
    arithmetic = analyze_code("value = 'text' / 2")
    assert any("need numeric operands" in error for error in arithmetic["errors"])

    indexing = analyze_code("items = [1, 2]\nvalue = items['first']")
    assert any("indexes must be integers" in error for error in indexing["errors"])


def test_semantic_analysis_understands_input_conversions_and_string_append():
    code = (
        "x = int(input('Rows: '))\n"
        "text = ''\n"
        "for i in range(x):\n"
        "    text += '*'\n"
    )
    result = analyze_code(code)
    symbols = {(symbol["name"], symbol["scope"]): symbol["inferred_type"] for symbol in result["symbols"]}
    assert symbols[("x", "global")] == "int"
    assert symbols[("text", "global")] == "str"
    assert result["errors"] == []


def test_semantic_analysis_explains_that_input_returns_text_for_range():
    result = analyze_code("x = input('Rows: ')\nfor i in range(x):\n    print(i)")
    assert any("input() returns text" in error and "int(input(...))" in error for error in result["errors"])


def test_semantic_analysis_tracks_class_fields_instances_and_methods():
    code = (
        "class Student:\n"
        "    def __init__(self):\n"
        "        self.name = ''\n"
        "        self.roll = -1\n"
        "    def update(self):\n"
        "        self.name = input('Name: ')\n"
        "        self.roll = int(input('Roll: '))\n"
        "    def show(self):\n"
        "        print(self.name)\n"
        "        print(self.roll)\n"
        "adi = Student()\n"
        "adi.update()\n"
        "adi.show()\n"
    )
    result = analyze_code(code)
    symbol_types = {
        (symbol["name"], symbol["scope"]): symbol["inferred_type"]
        for symbol in result["symbols"]
    }
    assert symbol_types[("adi", "global")] == "class:Student"
    assert symbol_types[("name", "Student")] == "str"
    assert symbol_types[("roll", "Student")] == "int"
    assert result["errors"] == []


def test_semantic_analysis_infers_and_checks_dictionaries_and_slices():
    code = (
        'names = ["Ada", "Lin"]\n'
        "short = names[0:1]\n"
        'person = {"age": 36, "score": 50}\n'
        'person["score"] = len(short)\n'
        'selected = person.get("age")\n'
        'found = "age" in person\n'
        'name = "Ada"\n'
        "uppercase = name.upper()\n"
    )
    result = analyze_code(code)
    symbols = {
        (symbol["name"], symbol["scope"]): symbol["inferred_type"]
        for symbol in result["symbols"]
    }

    assert symbols[("short", "global")] == "list[str]"
    assert symbols[("person", "global")] == "dict[str,int]"
    assert symbols[("selected", "global")] == "int"
    assert symbols[("found", "global")] == "bool"
    assert result["errors"] == []


def test_semantic_analysis_rejects_non_unit_slice_steps():
    result = analyze_code('name = "Ada"\npart = name[::2]')
    assert any("slice steps other than 1 are not supported" in error for error in result["errors"])
