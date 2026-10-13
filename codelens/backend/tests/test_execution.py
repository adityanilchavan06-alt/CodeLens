from fastapi.testclient import TestClient

from app.execution import compile_and_compare
from app.main import app
from app.translator import translate_rule_based


def test_generated_java_compiles_and_matches_python_output():
    python_code = "total = 40 + 2\nprint(total)\n"

    result = compile_and_compare(
        python_code,
        translate_rule_based(python_code),
    )

    assert result["compile"]["status"] == "success", result["compile"]
    assert result["python"]["status"] == "success", result["python"]
    assert result["java"]["status"] == "success", result["java"]
    assert result["comparison"] == {"status": "match", "equal": True}
    assert result["python"]["output"] == result["java"]["output"] == "42\n"


def test_execution_reports_output_differences_for_edited_java():
    python_code = "print(42)\n"
    java_code = (
        "public class CodeLensProgram {"
        " public static void main(String[] args) { System.out.println(41); }"
        "}"
    )

    result = compile_and_compare(python_code, java_code)

    assert result["compile"]["status"] == "success", result["compile"]
    assert result["comparison"] == {"status": "different", "equal": False}
    assert result["python"]["output"] == "42\n"
    assert result["java"]["output"] == "41\n"


def test_java_compiler_diagnostics_map_back_to_python_lines():
    python_code = "print(1)\n"
    java_code = (
        "public class CodeLensProgram {\n"
        "    public static void main(String[] args) {\n"
        "        int value = ;\n"
        "    }\n"
        "}\n"
    )

    result = compile_and_compare(
        python_code,
        java_code,
        source_map=[None, None, 8, None, None],
    )

    assert result["compile"]["status"] == "error"
    diagnostic = result["compile"]["diagnostics"][0]
    assert diagnostic["source"] == "java"
    assert diagnostic["line"] == 3
    assert diagnostic["python_line"] == 8


def test_execution_compares_supported_dict_slice_and_string_method_program():
    python_code = (
        'names = ["Ada", "Lin", "Sam"]\n'
        "short_names = names[0:2]\n"
        'person = {"count": len(short_names), "other": 2}\n'
        'person["count"] = len(short_names) + 1\n'
        'name = "Ada"\n'
        'print(name.upper())\n'
        'print(person.get("count"))\n'
        'print("count" in person)\n'
    )

    result = compile_and_compare(python_code, translate_rule_based(python_code))

    assert result["compile"]["status"] == "success", result["compile"]
    assert result["comparison"] == {"status": "match", "equal": True}
    assert result["python"]["output"] == "ADA\n3\nTrue\n"


def test_execution_passes_program_input_to_both_runtimes():
    python_code = "name = input('Name: ')\nprint('Hi', name)\n"

    result = compile_and_compare(
        python_code,
        translate_rule_based(python_code),
        "Ada\n",
    )

    assert result["comparison"] == {"status": "match", "equal": True}
    assert result["python"]["output"] == result["java"]["output"] == "Name: Hi Ada\n"


def test_execution_times_out_long_running_programs(monkeypatch):
    import app.execution as execution_module

    monkeypatch.setattr(execution_module, "RUN_TIMEOUT_SECONDS", 1)
    python_code = "while True:\n    pass\n"
    result = compile_and_compare(python_code, translate_rule_based(python_code))

    assert result["python"]["status"] == "timeout"
    assert result["java"]["status"] == "timeout"
    assert result["comparison"] == {"status": "unavailable", "equal": None}


def test_execution_rejects_oversized_input():
    import pytest

    from app.execution import ExecutionError

    with pytest.raises(ExecutionError, match="Input exceeds"):
        compile_and_compare(
            "print(1)",
            translate_rule_based("print(1)"),
            "x" * 4_001,
        )


def test_execution_endpoint_is_local_only_and_runs_the_code():
    client = TestClient(app, client=("127.0.0.1", 50000))
    python_code = "print('hello')\n"

    response = client.post(
        "/api/execute",
        json={
            "python_code": python_code,
            "java_code": translate_rule_based(python_code),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["comparison"] == {"status": "match", "equal": True}


def test_execution_endpoint_rejects_non_loopback_clients():
    client = TestClient(app, client=("192.0.2.1", 50000))

    response = client.post(
        "/api/execute",
        json={
            "python_code": "print(1)",
            "java_code": translate_rule_based("print(1)"),
        },
    )

    assert response.status_code == 403
