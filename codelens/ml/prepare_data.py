"""Convert paired Python/Java examples into CodeT5 training records.

Input JSONL rows have the shape {"python_code": "...", "java_code": "..."}.
The output records contain serialized lexer tokens and AST JSON as model input.
"""

import argparse
import json
from pathlib import Path
import sys


BACKEND_PATH = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_PATH))

from app.lexer import tokenize
from app.parser import build_ast


def prepare(input_path: Path, output_path: Path) -> int:
    """Write valid source-target pairs and fail clearly for invalid records."""
    written = 0
    with input_path.open(encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as output:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if "python_code" not in record or "java_code" not in record:
                raise ValueError(f"Input line {line_number} needs python_code and java_code fields.")
            serialized = {
                "tokens": tokenize(record["python_code"]),
                "ast": build_ast(record["python_code"]),
            }
            output.write(json.dumps({
                "input": json.dumps(serialized, ensure_ascii=False, separators=(",", ":")),
                "target": record["java_code"],
            }, ensure_ascii=False) + "\n")
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSONL file containing paired Python and Java.")
    parser.add_argument("--output", type=Path, required=True, help="Destination JSONL file for model training.")
    arguments = parser.parse_args()
    rows = prepare(arguments.input, arguments.output)
    print(f"Prepared {rows} training examples in {arguments.output}.")


if __name__ == "__main__":
    main()
