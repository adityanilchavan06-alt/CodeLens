"""Request and response models shared by the API routes."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, description="Python source code to analyze.")
    target: Literal["java", "cpp", "c"] = "java"


class JavaRequest(BaseModel):
    java_code: str = Field(min_length=1, description="Java source code to validate.")


class ExecutionRequest(BaseModel):
    python_code: str = Field(min_length=1, max_length=16_000)
    java_code: str = Field(min_length=1, max_length=32_000)
    stdin: str = Field(default="", max_length=4_000)
    source_map: list[int | None] | None = None


class Token(BaseModel):
    type: str
    value: str
    line: int
    column: int


class LexResponse(BaseModel):
    tokens: list[Token]


class ParseResponse(BaseModel):
    ast: dict[str, Any]


class Symbol(BaseModel):
    name: str
    inferred_type: str
    scope: str
    line: int


class SemanticResponse(BaseModel):
    symbols: list[Symbol]
    warnings: list[str]
    errors: list[str]


class TranslateResponse(BaseModel):
    java_code: str | None = None
    code: str | None = None
    target: Literal["java", "cpp", "c"] = "java"
    method: Literal["huggingface", "ml", "rule-based"]
    ast: dict[str, Any] | None = None
    model: str | None = None
    confidence: float | None = None
    coverage: float | None = None
    fallback_reason: str | None = None
    source_map: list[int | None] | None = None


class ValidateResponse(BaseModel):
    is_valid: bool
    errors: list[str]
    confidence: float | None


class StageResult(BaseModel):
    status: Literal["success", "error", "skipped"]
    result: dict[str, Any] | None = None
    error: str | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class PipelineResponse(BaseModel):
    lex: StageResult
    parse: StageResult
    semantic: StageResult
    translate: StageResult
    validation: StageResult = Field(alias="validate")
