"""Entry point for the CodeLens Translator API."""

import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .lexer import LexerError, tokenize
from .parser import ParseError, build_ast
from .schemas import (
    CodeRequest,
    ExecutionRequest,
    JavaRequest,
    LexResponse,
    ParseResponse,
    PipelineResponse,
    SemanticResponse,
    StageResult,
    TranslateResponse,
    ValidateResponse,
)
from .semantic import analyze_code
from .translator import TranslationError, translate
from .native_translator import translate_native_with_map
from .validator import validate_code as validate_generated_code
from .execution import ExecutionError, compile_and_compare

app = FastAPI(
    title="CodeLens Translator",
    description="A compiler-pipeline teaching app that translates Python to Java, C++, and C.",
    version="0.1.0",
)

SAMPLES_PATH = Path(__file__).resolve().parents[2] / "samples" / "examples.json"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root() -> dict[str, str]:
    """Return a small hello-world response to confirm the API is running."""
    return {"message": "Welcome to CodeLens Translator!"}


@app.get("/health")
def health_check() -> dict[str, str]:
    """Report that the API process is healthy."""
    return {"status": "ok"}


@app.get("/api/samples")
def get_samples() -> list[dict[str, str]]:
    """Return the project's checked-in examples for the UI sample selector."""
    with SAMPLES_PATH.open(encoding="utf-8") as sample_file:
        return json.load(sample_file)


def _api_error(error: Exception) -> HTTPException:
    """Convert expected compiler errors into readable client responses."""
    return HTTPException(status_code=422, detail=str(error))


def _diagnostics(messages: list[str], source: str) -> list[dict[str, object]]:
    diagnostics = []
    for message in messages:
        match = re.match(r"Line (\d+)(?:, column (\d+))?:\s*(.*)", message)
        diagnostic: dict[str, object] = {
            "source": source,
            "message": message,
            "severity": "error",
        }
        if match:
            diagnostic["line"] = int(match.group(1))
            if match.group(2):
                diagnostic["column"] = int(match.group(2))
            diagnostic["message"] = match.group(3)
        diagnostics.append(diagnostic)
    return diagnostics


@app.post("/api/lex", response_model=LexResponse)
def lex_code(request: CodeRequest) -> dict:
    try:
        return {"tokens": tokenize(request.code)}
    except LexerError as exc:
        raise _api_error(exc) from exc


@app.post("/api/parse", response_model=ParseResponse)
def parse_code(request: CodeRequest) -> dict:
    try:
        return {"ast": build_ast(request.code)}
    except ParseError as exc:
        raise _api_error(exc) from exc


@app.post("/api/semantic", response_model=SemanticResponse)
def semantic_code(request: CodeRequest) -> dict:
    try:
        return analyze_code(request.code)
    except ParseError as exc:
        raise _api_error(exc) from exc


@app.post("/api/translate", response_model=TranslateResponse)
def translate_code(request: CodeRequest) -> dict:
    try:
        if request.target == "java":
            return translate(request.code, tokenize(request.code))
        semantic = analyze_code(request.code)
        if semantic["errors"]:
            raise TranslationError("; ".join(semantic["errors"]))
        native_code, source_map = translate_native_with_map(
            request.code, request.target, semantic["symbols"]
        )
        return {
            "target": request.target,
            "code": native_code,
            "method": "rule-based",
            "coverage": 100.0,
            "source_map": source_map,
        }
    except (LexerError, ParseError, TranslationError) as exc:
        raise _api_error(exc) from exc


@app.post("/api/validate", response_model=ValidateResponse)
def validate_code(request: JavaRequest) -> dict:
    return validate_generated_code(request.java_code, "java")


@app.post("/api/execute")
def execute_code(request: ExecutionRequest, http_request: Request) -> dict:
    """Run code for local educational use; this is not a security sandbox."""
    if http_request.client is None or http_request.client.host not in {
        "127.0.0.1", "::1", "localhost",
    }:
        raise HTTPException(
            status_code=403,
            detail="Code execution is available only to local clients.",
        )
    try:
        result = compile_and_compare(
            request.python_code,
            request.java_code,
            request.stdin,
            request.source_map,
        )
    except (ExecutionError, ParseError) as exc:
        raise _api_error(exc) from exc
    return result


@app.post("/api/pipeline", response_model=PipelineResponse)
def run_pipeline(request: CodeRequest) -> dict:
    """Run each stage independently and preserve completed stage results."""
    output = {
        "lex": StageResult(status="skipped", error="Not run because an earlier stage failed.").model_dump(),
        "parse": StageResult(status="skipped", error="Not run because an earlier stage failed.").model_dump(),
        "semantic": StageResult(status="skipped", error="Not run because an earlier stage failed.").model_dump(),
        "translate": StageResult(status="skipped", error="Not run because an earlier stage failed.").model_dump(),
        "validate": StageResult(status="skipped", error="Not run because an earlier stage failed.").model_dump(),
    }
    try:
        tokens = tokenize(request.code)
        output["lex"] = StageResult(status="success", result={"tokens": tokens}).model_dump()
    except LexerError as exc:
        output["lex"] = StageResult(
            status="error",
            error=str(exc),
            diagnostics=_diagnostics([str(exc)], "python"),
        ).model_dump()
        return output

    try:
        parsed_ast = build_ast(request.code)
        output["parse"] = StageResult(status="success", result={"ast": parsed_ast}).model_dump()
    except ParseError as exc:
        output["parse"] = StageResult(
            status="error",
            error=str(exc),
            diagnostics=_diagnostics([str(exc)], "python"),
        ).model_dump()
        return output

    try:
        semantic = analyze_code(request.code)
        semantic_status = "error" if semantic["errors"] else "success"
        output["semantic"] = StageResult(
            status=semantic_status,
            result=semantic,
            diagnostics=_diagnostics(semantic["errors"], "python"),
        ).model_dump()
        if semantic["errors"]:
            output["translate"] = StageResult(
                status="error",
                error="Translation stopped because semantic errors were found.",
                diagnostics=_diagnostics(semantic["errors"], "python"),
            ).model_dump()
            return output
    except ParseError as exc:
        output["semantic"] = StageResult(
            status="error",
            error=str(exc),
            diagnostics=_diagnostics([str(exc)], "python"),
        ).model_dump()
        return output

    try:
        if request.target == "java":
            translated = translate(request.code, tokens)
        else:
            native_code, source_map = translate_native_with_map(
                request.code, request.target, semantic["symbols"]
            )
            translated = {
                "target": request.target,
                "code": native_code,
                "method": "rule-based",
                "coverage": 100.0,
                "source_map": source_map,
            }
        output["translate"] = StageResult(status="success", result=translated).model_dump()
    except (ParseError, TranslationError) as exc:
        output["translate"] = StageResult(
            status="error",
            error=str(exc),
            diagnostics=_diagnostics([str(exc)], "python"),
        ).model_dump()
        return output

    if translated["method"] == "huggingface":
        score = None
    elif translated["method"] == "ml":
        score = translated.get("confidence")
    else:
        score = translated.get("coverage", 0)
    generated_code = str(translated.get("code", translated.get("java_code", "")))
    validation = validate_generated_code(
        generated_code,
        request.target,
        coverage=None if score is None else float(score) / 100,
    )
    validation_status = "success" if validation["is_valid"] else "error"
    validation_error = "; ".join(validation["errors"]) if validation["errors"] else None
    validation_diagnostics = _diagnostics(validation["errors"], "java")
    source_map = translated.get("source_map")
    if isinstance(source_map, list):
        for diagnostic in validation_diagnostics:
            line = diagnostic.get("line")
            if isinstance(line, int) and 1 <= line <= len(source_map):
                python_line = source_map[line - 1]
                if python_line is not None:
                    diagnostic["python_line"] = python_line
    output["validate"] = StageResult(
        status=validation_status,
        result=validation,
        error=validation_error,
        diagnostics=validation_diagnostics,
    ).model_dump()
    return output
