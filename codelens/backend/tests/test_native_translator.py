import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.native_translator import translate_native
from app.semantic import analyze_code
from app.translator import TranslationError
from app.validator import validate_code


client = TestClient(app)


@pytest.mark.parametrize("target", ["c", "cpp"])
def test_native_translator_generates_syntax_valid_code(target):
    source = (
        "def double(value):\n"
        "    return value * 2\n"
        "answer = double(21)\n"
        "if answer > 10:\n"
        "    print(answer)\n"
        "for index in range(3):\n"
        "    print(index)\n"
    )
    symbols = analyze_code(source)["symbols"]

    generated = translate_native(source, target, symbols)
    result = validate_code(generated, target)

    assert "double(" in generated
    assert "for (" in generated
    assert "printf(" in generated if target == "c" else "std::cout" in generated
    assert result["is_valid"], result["errors"]


@pytest.mark.parametrize("target", ["c", "cpp"])
def test_pipeline_translates_to_selected_native_target(target):
    response = client.post(
        "/api/pipeline",
        json={"code": "number = 7\nprint(number)", "target": target},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["translate"]["status"] == "success"
    assert result["translate"]["result"]["target"] == target
    assert result["validate"]["status"] == "success"
    assert result["validate"]["result"]["is_valid"] is True


def test_translate_route_returns_native_code_for_requested_target():
    response = client.post(
        "/api/translate",
        json={"code": "value = 4\nprint(value)", "target": "cpp"},
    )

    assert response.status_code == 200
    assert response.json()["target"] == "cpp"
    assert "std::cout" in response.json()["code"]


def test_native_translator_reports_unsupported_python_features():
    code = "class Example:\n    pass"

    with pytest.raises(TranslationError, match="Line 1: classes are not supported"):
        translate_native(code, "cpp", [])
