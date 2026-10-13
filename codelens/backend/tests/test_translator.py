import pytest
import json
from pathlib import Path
from types import SimpleNamespace

from app.execution import compile_and_compare
from app.translator import (
    DEFAULT_HF_MODEL,
    TranslationError,
    translate,
    translate_rule_based,
)
from app.validator import validate_java


@pytest.mark.parametrize(
    "code",
    [
        "number = 7\nprint(number)",
        "price = 2.5\nprint(price)",
        "name = 'Ada'\nprint(name)",
        "ready = True\nprint(ready)",
        "if True:\n    print('yes')\nelse:\n    print('no')",
        "for i in range(3):\n    print(i)",
        "while False:\n    print('no')",
        "def double(value):\n    return value * 2\nprint(double(4))",
        "items = [1, 2]\nitems.append(3)\nprint(items[0])",
    ],
)
def test_rule_translation_produces_valid_java(code):
    java_code = translate_rule_based(code)
    result = validate_java(java_code)

    assert "public class CodeLensProgram" in java_code
    assert result["is_valid"], result["errors"]


def test_rule_translation_stops_for_undefined_variable():
    with pytest.raises(TranslationError, match="not defined"):
        translate_rule_based("print(missing)")


def test_missing_model_path_falls_back_with_explanation(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "missing-model"))
    result = translate("value = 1")
    assert result["method"] == "rule-based"
    assert "does not exist" in result["fallback_reason"]
    assert result["coverage"] == 100.0


def test_huggingface_translation_receives_backend_tokens_and_returns_ast(
    monkeypatch,
):
    expected_ast = {
        "type": "Module",
        "children": [{"type": "Assign", "line": 1}],
    }
    model_response = json.dumps({
        "ast": expected_ast,
        "java_code": "public class CodeLensProgram {}",
    })
    captured = {}

    class FakeInferenceClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def chat_completion(self, **kwargs):
            assert kwargs["response_format"] == {"type": "json_object"}
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=model_response)
                    )
                ]
            )

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("HF_MODEL", "org/test-model")
    monkeypatch.setattr("app.translator.InferenceClient", FakeInferenceClient)

    result = translate("value = 1")

    assert result["method"] == "huggingface"
    assert result["model"] == "org/test-model"
    assert result["ast"] == expected_ast
    assert result["java_code"] == "public class CodeLensProgram {}"
    assert captured["client"]["token"] == "test-token"
    assert captured["client"]["model"] == "org/test-model"
    prompt_data = json.loads(captured["messages"][1]["content"])
    assert prompt_data["python_code"] == "value = 1"
    assert [token["value"] for token in prompt_data["tokens"][:3]] == [
        "value", "=", "1"
    ]


def test_huggingface_model_uses_default_model_name(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.delenv("HF_MODEL", raising=False)

    class FakeInferenceClient:
        def __init__(self, **kwargs):
            assert kwargs["model"] == DEFAULT_HF_MODEL

        def chat_completion(self, **kwargs):
            assert kwargs["max_tokens"] > 0
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps({
                                "ast": {"type": "Module"},
                                "java_code": "class Program {}",
                            })
                        )
                    )
                ]
            )

    monkeypatch.setattr("app.translator.InferenceClient", FakeInferenceClient)

    assert translate("pass")["method"] == "huggingface"


def test_huggingface_translation_falls_back_on_invalid_response(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-token")

    class FakeInferenceClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 120

        def chat_completion(self, **kwargs):
            assert kwargs["max_tokens"] > 0
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="not JSON"))
                ]
            )

    monkeypatch.setattr("app.translator.InferenceClient", FakeInferenceClient)

    result = translate("value = 1")

    assert result["method"] == "rule-based"
    assert "did not return valid JSON" in result["fallback_reason"]
    assert "int value;" in result["java_code"]


def test_rule_translation_handles_string_comparison_and_list_membership():
    java_code = translate_rule_based(
        "names = ['Ada']\nif 'Ada' in names:\n    print('found')"
    )
    assert 'names.contains("Ada")' in java_code
    assert validate_java(java_code)["is_valid"]


def test_range_loop_with_zero_variable_step_throws_instead_of_running_forever():
    java_code = translate_rule_based(
        "step = 0\nfor index in range(5, 0, step):\n    print(index)"
    )

    assert "if (step == 0) {" in java_code
    assert (
        'throw new IllegalArgumentException("range() arg 3 must not be zero");'
        in java_code
    )
    assert java_code.index("if (step == 0)") < java_code.index("for (index = 5;")
    assert validate_java(java_code)["is_valid"]


def test_translates_string_methods_slices_and_dictionaries_to_valid_java():
    code = (
        'names = ["Ada", "Lin", "Sam"]\n'
        "short = names[0:2]\n"
        'person = {"count": len(short), "other": 2}\n'
        'person["count"] = len(short) + 1\n'
        'name = "Ada"\n'
        'print(name.upper())\n'
        'print(person.get("count"))\n'
        'print("count" in person)\n'
        'greeting = "hello-world"\n'
        'print(greeting.replace("-", "_").startswith("hello"))\n'
    )

    java_code = translate_rule_based(code)

    assert "sliceList(names, 0, 2)" in java_code
    assert "Map<String, Integer> person;" in java_code
    assert 'person.put("count", (_short.size() + 1));' in java_code
    assert "name.toUpperCase()" in java_code
    assert 'person.get("count")' in java_code
    assert 'person.containsKey("count")' in java_code
    assert 'greeting.replace("-", "_").startsWith("hello")' in java_code
    assert validate_java(java_code)["is_valid"]


def test_function_return_type_flows_to_callers():
    java_code = translate_rule_based(
        "def double(value):\n    return value * 2\nresult = double(4)"
    )
    assert "public static int _double(int value)" in java_code
    assert "result = _double(4);" in java_code
    assert "private static int result;" in java_code
    assert validate_java(java_code)["is_valid"]


def test_list_item_assignment_generates_set_call():
    java_code = translate_rule_based("numbers = [1, 2]\nnumbers[0] = 9")
    assert "numbers.set(0, 9);" in java_code
    assert validate_java(java_code)["is_valid"]


def test_print_can_combine_multiple_arguments():
    java_code = translate_rule_based("print('total', 3)")
    assert 'System.out.println(String.valueOf("total") + " " + String.valueOf(3));' in java_code
    assert validate_java(java_code)["is_valid"]


def test_f_string_interpolates_string_and_numeric_values():
    java_code = translate_rule_based(
        'name = "Ada"\nscore = 98\nprint(f"{name} scored {score}!")'
    )
    assert 'String.valueOf(name) + " scored " + String.valueOf(score) + "!"' in java_code
    assert validate_java(java_code)["is_valid"]


def test_f_string_can_interpolate_supported_expressions():
    java_code = translate_rule_based('number = 4\nprint(f"Double is {number * 2}")')
    assert 'String.valueOf((number * 2))' in java_code
    assert validate_java(java_code)["is_valid"]


def test_input_int_conversion_and_nested_string_loops_generate_valid_java():
    code = (
        "x = int(input('Please enter the number of rows: '))\n"
        "for i in range(x):\n"
        "    text = ''\n"
        "    for blank in range(x-i):\n"
        "        text += ' '\n"
        "    for star in range(i):\n"
        "        text += '*'\n"
        "    print(text)\n"
    )
    java_code = translate_rule_based(code)

    assert "new Scanner(System.in)" in java_code
    assert "Integer.parseInt(readInput(" in java_code
    assert "for (i = 0; i < x; i += 1)" in java_code
    assert "text += \" \";" in java_code
    assert "text += \"*\";" in java_code
    assert validate_java(java_code)["is_valid"]


def test_student_class_with_constructor_fields_input_and_methods():
    code = (
        "class Student:\n"
        "    def __init__(self):\n"
        "        self.name = ''\n"
        "        self.roll = -1\n"
        "    def update(self):\n"
        "        self.name = input('Enter the name ')\n"
        "        self.roll = int(input('Enter the rollno'))\n"
        "    def show(self):\n"
        "        print(self.name)\n"
        "        print(self.roll)\n"
        "adi = Student()\n"
        "adi.update()\n"
        "adi.show()\n"
    )
    java_code = translate_rule_based(code)
    assert "public static class Student" in java_code
    assert "private String name;" in java_code
    assert "private int roll;" in java_code
    assert "public Student()" in java_code
    assert "this.name = readInput(" in java_code
    assert "this.roll = Integer.parseInt(readInput(" in java_code
    assert "adi = new Student();" in java_code
    assert "adi.update();" in java_code
    assert "adi.show();" in java_code
    assert validate_java(java_code)["is_valid"]


def test_bank_account_example_with_default_constructor_and_main_guard():
    code = (
        "class BankAccount:\n"
        "    def __init__(self, owner, balance=0.0):\n"
        "        self.owner = owner\n"
        "        self.balance = balance\n"
        "    def deposit(self, amount):\n"
        "        if amount > 0:\n"
        "            self.balance += amount\n"
        "            print(f'Deposited {amount}. New balance: {self.balance}')\n"
        "    def withdraw(self, amount):\n"
        "        if 0 < amount <= self.balance:\n"
        "            self.balance -= amount\n"
        "            print(f'Withdrew {amount}. New balance: {self.balance}')\n"
        "        else:\n"
        "            print('Insufficient funds or invalid amount.')\n"
        "if __name__ == '__main__':\n"
        "    account = BankAccount('Alice', 100.0)\n"
        "    account.deposit(50.0)\n"
        "    account.withdraw(30.0)\n"
    )

    java_code = translate_rule_based(code)
    result = validate_java(java_code)

    assert "public BankAccount(String owner, double balance)" in java_code
    assert "public BankAccount(String owner) {" in java_code
    assert "this(owner, 0.0);" in java_code
    assert "public void deposit(double amount)" in java_code
    assert "public void withdraw(double amount)" in java_code
    assert "if ((_name__.equals(\"__main__\")))" not in java_code
    assert "account = new BankAccount(\"Alice\", 100.0);" in java_code
    assert result["is_valid"], result["errors"]


def test_all_samples_match_expected_java_and_parse():
    samples_path = Path(__file__).resolve().parents[2] / "samples" / "examples.json"
    samples = json.loads(samples_path.read_text(encoding="utf-8"))

    assert len(samples) >= 15
    for sample in samples:
        java_code = translate_rule_based(sample["code"])
        assert sample["expected_java"] in java_code, sample["name"]
        result = validate_java(java_code)
        assert result["is_valid"], f"{sample['name']}: {result['errors']}"


def test_log_analyzer_example_translates_to_valid_java():
    source_path = Path(__file__).parent / "fixtures" / "log_analyzer.py"
    source = source_path.read_text(encoding="utf-8")
    java_code = translate_rule_based(source)
    result = compile_and_compare(source, java_code)

    assert "splitWhitespace" in java_code
    assert "sortedEntries" in java_code
    assert "String.format(Locale.ROOT, \"%.2f\"" in java_code
    assert result["compile"]["status"] == "success", result["compile"]
    assert result["comparison"] == {"status": "match", "equal": True}
