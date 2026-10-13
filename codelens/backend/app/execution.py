"""Local-only Java compilation and Python/Java output comparison."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from .parser import build_ast
from .semantic import analyze_code


MAX_SOURCE_BYTES = 32_000
MAX_INPUT_BYTES = 4_000
MAX_OUTPUT_BYTES = 64_000
COMPILE_TIMEOUT_SECONDS = 10
RUN_TIMEOUT_SECONDS = 4


class ExecutionError(ValueError):
    """An execution request exceeds limits or is not valid supported Python."""


def _execution_environment() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP",
        "JAVA_HOME", "PATHEXT",
    }
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in allowed
    }
    if os.name != "nt":
        environment["PATH"] = os.environ.get("PATH", "")
        environment["HOME"] = os.environ.get("HOME", "")
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


@lru_cache(maxsize=1)
def _java_tools() -> tuple[str, str]:
    """Resolve the real JDK binaries instead of Windows' spawning PATH shims."""
    try:
        details = subprocess.run(
            [shutil.which("java") or "java", "-XshowSettings:properties", "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
            env=_execution_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExecutionError(f"Could not locate a working Java JDK: {exc}") from exc
    properties = details.stdout + details.stderr
    home = re.search(r"^\s*java\.home\s*=\s*(.+?)\s*$", properties, re.MULTILINE)
    if not home:
        raise ExecutionError(
            "Could not locate the active JDK home; install a JDK with java and javac."
        )
    jdk_bin = Path(home.group(1)) / "bin"
    java = jdk_bin / ("java.exe" if os.name == "nt" else "java")
    javac = jdk_bin / ("javac.exe" if os.name == "nt" else "javac")
    if not java.is_file() or not javac.is_file():
        raise ExecutionError(
            "The active Java installation is not a JDK with both java and javac."
        )
    return str(java), str(javac)


def _run_limited(
    command: list[str],
    *,
    cwd: Path,
    stdin: str = "",
    timeout: int,
) -> dict[str, Any]:
    output = bytearray()
    output_limit_exceeded = threading.Event()
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        env=_execution_environment(),
    )
    assert process.stdout is not None

    def collect_output() -> None:
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                return
            remaining = MAX_OUTPUT_BYTES - len(output)
            if len(chunk) > remaining:
                output.extend(chunk[:max(remaining, 0)])
                output_limit_exceeded.set()
                process.kill()
                return
            output.extend(chunk)

    reader = threading.Thread(target=collect_output, daemon=True)
    reader.start()
    timeout_exceeded = False
    try:
        if process.stdin is not None:
            process.stdin.write(stdin.encode("utf-8"))
            process.stdin.close()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timeout_exceeded = True
            process.kill()
            process.wait()
    except BrokenPipeError:
        process.wait(timeout=1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=1)
        if reader.is_alive():
            process.stdout.close()

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    text = output.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if output_limit_exceeded.is_set():
        return {
            "status": "error",
            "output": text,
            "error": f"Output exceeded the {MAX_OUTPUT_BYTES}-byte limit.",
            "return_code": process.returncode,
            "duration_ms": duration_ms,
        }
    if timeout_exceeded:
        return {
            "status": "timeout",
            "output": text,
            "error": f"Execution exceeded the {timeout}-second time limit.",
            "return_code": process.returncode,
            "duration_ms": duration_ms,
        }
    return {
        "status": "success" if process.returncode == 0 else "error",
        "output": text,
        "error": None if process.returncode == 0 else "Process exited with a non-zero status.",
        "return_code": process.returncode,
        "duration_ms": duration_ms,
    }


def compile_and_compare(
    python_code: str,
    java_code: str,
    stdin: str = "",
    source_map: list[int | None] | None = None,
) -> dict[str, Any]:
    """Compile and run Java, run the equivalent Python source, and compare output."""
    if len(python_code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ExecutionError(f"Python source exceeds the {MAX_SOURCE_BYTES}-byte limit.")
    if len(java_code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ExecutionError(f"Java source exceeds the {MAX_SOURCE_BYTES}-byte limit.")
    if len(stdin.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ExecutionError(f"Input exceeds the {MAX_INPUT_BYTES}-byte limit.")

    java, javac = _java_tools()
    build_ast(python_code)
    semantic = analyze_code(python_code)
    if semantic["errors"]:
        raise ExecutionError(
            "Cannot run the Python reference until semantic errors are fixed: "
            + "; ".join(semantic["errors"])
        )

    with tempfile.TemporaryDirectory(prefix="codelens-run-") as temporary:
        workdir = Path(temporary)
        source_file = workdir / "CodeLensProgram.java"
        source_file.write_text(java_code, encoding="utf-8")
        compilation = _run_limited(
            [javac, "-proc:none", "-encoding", "UTF-8", "-d", str(workdir), str(source_file)],
            cwd=workdir,
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
        compilation["diagnostics"] = []
        for match in re.finditer(
            r"CodeLensProgram\.java:(\d+):\s*(?:(error|warning):\s*)?([^\r\n]+)",
            compilation["output"],
        ):
            line = int(match.group(1))
            diagnostic = {
                "source": "java",
                "line": line,
                "severity": "error" if match.group(2) == "error" else "warning",
                "message": match.group(3),
            }
            if source_map and line <= len(source_map):
                python_line = source_map[line - 1]
                if python_line is not None:
                    diagnostic["python_line"] = python_line
            compilation["diagnostics"].append(diagnostic)
        compilation["output"] = compilation["output"].replace(
            str(source_file), source_file.name
        )
        result: dict[str, Any] = {"compile": compilation, "python": None, "java": None}
        if compilation["status"] != "success":
            result["comparison"] = None
            return result

        python_file = workdir / "reference.py"
        python_file.write_text(python_code, encoding="utf-8")
        result["python"] = _run_limited(
            [sys.executable, "-I", str(python_file)],
            cwd=workdir,
            stdin=stdin,
            timeout=RUN_TIMEOUT_SECONDS,
        )
        result["java"] = _run_limited(
            [java, "-cp", str(workdir), "CodeLensProgram"],
            cwd=workdir,
            stdin=stdin,
            timeout=RUN_TIMEOUT_SECONDS,
        )
        python_result = result["python"]
        java_result = result["java"]
        comparable = (
            python_result["status"] == "success"
            and java_result["status"] == "success"
        )
        result["comparison"] = {
            "status": (
                "match" if python_result["output"] == java_result["output"]
                else "different"
            ) if comparable else "unavailable",
            "equal": python_result["output"] == java_result["output"] if comparable else None,
        }
        return result
