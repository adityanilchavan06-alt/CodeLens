from unittest.mock import Mock
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


client = TestClient(app)


def test_health_route():
    assert client.get("/health").json() == {"status": "ok"}


def test_samples_route_returns_sample_programs():
    response = client.get("/api/samples")
    assert response.status_code == 200
    assert len(response.json()) >= 15


def test_pipeline_maps_java_diagnostics_to_python_lines(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "translate",
        Mock(return_value={
            "java_code": "class Main {\n    invalid;\n}",
            "method": "rule-based",
            "coverage": 100.0,
            "source_map": [None, 3, None],
        }),
    )
    monkeypatch.setattr(
        main_module,
        "validate_generated_code",
        Mock(return_value={
            "is_valid": False,
            "errors": ["Line 2: invalid Java syntax"],
            "confidence": 1.0,
        }),
    )

    response = client.post(
        "/api/pipeline", json={"code": "x = 1\nprint(x)\nprint(2)"}
    )

    assert response.status_code == 200
    assert response.json()["validate"]["diagnostics"] == [{
        "source": "java",
        "severity": "error",
        "line": 2,
        "message": "invalid Java syntax",
        "python_line": 3,
    }]


def test_native_pipeline_returns_generated_to_python_line_map():
    code = "answer = 6 * 7\nprint(answer)"
    for target, print_marker in (
        ("cpp", "std::cout"),
        ("c", 'printf("%d\\n", answer)'),
    ):
        response = client.post(
            "/api/pipeline", json={"code": code, "target": target}
        )

        assert response.status_code == 200
        result = response.json()
        assert result["translate"]["status"] == "success", result["translate"]
        translation = result["translate"]["result"]
        generated_lines = translation["code"].splitlines()
        assert len(translation["source_map"]) == len(generated_lines)
        assert 1 in translation["source_map"]
        assert 2 in translation["source_map"]
        print_line = next(
            index for index, line in enumerate(generated_lines)
            if print_marker in line
        )
        assert translation["source_map"][print_line] == 2


def test_java_pipeline_line_map_stays_aligned_with_generated_code():
    response = client.post(
        "/api/pipeline", json={"code": "answer = 6 * 7\nprint(answer)"}
    )

    assert response.status_code == 200
    translation = response.json()["translate"]["result"]
    generated_lines = translation["java_code"].splitlines()
    assert len(translation["source_map"]) == len(generated_lines)
    print_line = next(
        index for index, line in enumerate(generated_lines)
        if "System.out.println" in line
    )
    assert translation["source_map"][print_line] == 2


def test_unsupported_native_dictionary_has_a_line_specific_diagnostic():
    response = client.post(
        "/api/pipeline",
        json={"code": 'values = {"answer": 42}', "target": "c"},
    )

    assert response.status_code == 200
    translation_stage = response.json()["translate"]
    assert translation_stage["status"] == "error"
    assert translation_stage["diagnostics"] == [{
        "source": "python",
        "severity": "error",
        "line": 1,
        "message": "dictionaries are not supported for C output.",
    }]


def test_java_pipeline_accepts_dictionary_literals_after_lexing():
    code = 'values = {"answer": 42}\nprint(values.get("answer"))'
    response = client.post("/api/pipeline", json={"code": code, "target": "java"})

    assert response.status_code == 200
    result = response.json()
    assert [result[stage]["status"] for stage in (
        "lex", "parse", "semantic", "translate", "validate"
    )] == ["success"] * 5, result
    assert 'values = mapOf("answer", 42);' in result["translate"]["result"]["java_code"]


def test_log_analyzer_example_completes_the_java_pipeline(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("MODEL_PATH", raising=False)
    source = (
        Path(__file__).parent / "fixtures" / "log_analyzer.py"
    ).read_text(encoding="utf-8")

    response = client.post(
        "/api/pipeline",
        json={"code": source, "target": "java"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert [result[stage]["status"] for stage in (
        "lex", "parse", "semantic", "translate", "validate"
    )] == ["success"] * 5, result


def test_every_sample_completes_all_pipeline_stages():
    samples = client.get("/api/samples").json()
    for sample in samples:
        result = client.post("/api/pipeline", json={"code": sample["code"]}).json()
        assert [result[stage]["status"] for stage in (
            "lex", "parse", "semantic", "translate", "validate"
        )] == ["success"] * 5, f"{sample['name']}: {result}"


def test_pyramid_program_with_explicit_integer_input_completes_pipeline():
    code = (
        "x = int(input('Please enter the number of rows'))\n"
        "for i in range(x):\n"
        "    text = ''\n"
        "    for blank in range(x-i):\n"
        "        text += ' '\n"
        "    for star in range(i):\n"
        "        text += '*'\n"
        "    print(text)\n"
    )
    result = client.post("/api/pipeline", json={"code": code}).json()
    assert all(result[stage]["status"] == "success" for stage in (
        "lex", "parse", "semantic", "translate", "validate"
    ))


def test_student_class_example_completes_pipeline():
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
    result = client.post("/api/pipeline", json={"code": code}).json()
    assert all(result[stage]["status"] == "success" for stage in (
        "lex", "parse", "semantic", "translate", "validate"
    ))


def test_function_default_argument_can_be_omitted_in_pipeline(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("MODEL_PATH", raising=False)
    code = (
        "def greet(name, greeting='Hello'):\n"
        "    print(greeting + ', ' + name)\n"
        "greet('Ada')\n"
    )

    result = client.post("/api/pipeline", json={"code": code}).json()

    assert [result[stage]["status"] for stage in (
        "lex", "parse", "semantic", "translate", "validate"
    )] == ["success"] * 5, result
    assert (
        "public static void greet(String name, String greeting)"
        in result["translate"]["result"]["java_code"]
    )
    assert (
        'public static void greet(String name) {'
        in result["translate"]["result"]["java_code"]
    )
    assert 'greet("Ada");' in result["translate"]["result"]["java_code"]


def test_bank_account_example_with_defaults_and_main_guard_completes_pipeline(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("MODEL_PATH", raising=False)
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

    result = client.post("/api/pipeline", json={"code": code}).json()

    assert [result[stage]["status"] for stage in (
        "lex", "parse", "semantic", "translate", "validate"
    )] == ["success"] * 5, result
    assert result["translate"]["result"]["method"] == "rule-based"
    assert result["validate"]["result"]["is_valid"] is True


def test_each_compiler_route():
    code = "number = 2\nprint(number)"

    assert client.post("/api/lex", json={"code": code}).status_code == 200
    assert client.post("/api/parse", json={"code": code}).json()["ast"]["type"] == "Module"
    assert client.post("/api/semantic", json={"code": code}).json()["errors"] == []
    assert client.post("/api/translate", json={"code": code}).json()["method"] == "rule-based"
    pipeline = client.post("/api/pipeline", json={"code": code}).json()
    assert set(pipeline) == {"lex", "parse", "semantic", "translate", "validate"}
    assert pipeline["validate"]["result"]["confidence"] == 100.0


def test_pipeline_exposes_huggingface_ast_and_translated_java(monkeypatch):
    model_ast = {"type": "Module", "children": []}

    def fake_translate(code, tokens):
        assert code == "value = 1"
        assert tokens[0]["value"] == "value"
        return {
            "ast": model_ast,
            "java_code": "public class CodeLensProgram {}",
            "method": "huggingface",
            "model": "org/test-model",
        }

    monkeypatch.setattr("app.main.translate", fake_translate)

    result = client.post(
        "/api/pipeline", json={"code": "value = 1"}
    ).json()

    assert result["lex"]["result"]["tokens"]
    assert result["parse"]["result"]["ast"]["type"] == "Module"
    assert result["translate"]["result"]["ast"] == model_ast
    assert result["translate"]["result"]["java_code"] == "public class CodeLensProgram {}"
    assert result["translate"]["result"]["model"] == "org/test-model"
    assert result["validate"]["result"]["is_valid"] is True
    assert result["validate"]["result"]["confidence"] is None


def test_pipeline_keeps_earlier_results_if_later_stage_fails():
    result = client.post("/api/pipeline", json={"code": "print(missing)"}).json()

    assert result["lex"]["status"] == "success"
    assert result["parse"]["status"] == "success"
    assert result["semantic"]["status"] == "error"
    assert result["translate"]["status"] == "error"
    assert result["validate"]["status"] == "skipped"


def test_pipeline_reports_unsupported_syntax_with_completed_lexer_result():
    result = client.post("/api/pipeline", json={"code": "class Example:\n    pass"}).json()

    assert result["lex"]["status"] == "success"
    assert result["parse"]["status"] == "error"
    assert result["semantic"]["status"] == "skipped"


def test_lexer_error_is_a_clear_client_error():
    response = client.post("/api/lex", json={"code": "x = $"})
    assert response.status_code == 422
    assert "illegal character" in response.json()["detail"]


def test_java_validation_reports_invalid_syntax():
    result = client.post("/api/validate", json={"java_code": "public class {"}).json()
    assert result["is_valid"] is False
    assert result["errors"]
