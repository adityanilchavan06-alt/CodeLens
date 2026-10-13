import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.execution import compile_and_compare
from app.main import app


client = TestClient(app)

ALGORITHM_EXAMPLES = """\
print("Hello, World!")

def add(a, b):
    return a + b

def is_even(n):
    if n % 2 == 0:
        return True
    else:
        return False

def max_of_three(a, b, c):
    if a >= b and a >= c:
        return a
    elif b >= a and b >= c:
        return b
    else:
        return c

def factorial(n):
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        print(a, end=" ")
        temp = a + b
        a = b
        b = temp

def is_prime(n):
    if n <= 1:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True

def reverse_string(s):
    reversed_str = ""
    for char in s:
        reversed_str = char + reversed_str
    return reversed_str

def is_palindrome(s):
    left = 0
    right = len(s) - 1
    while left < right:
        if s[left] != s[right]:
            return False
        left += 1
        right -= 1
    return True

def sum_array(arr):
    total = 0
    for i in range(len(arr)):
        total += arr[i]
    return total

def max_in_array(arr):
    max_val = arr[0]
    for i in range(1, len(arr)):
        if arr[i] > max_val:
            max_val = arr[i]
    return max_val

def linear_search(arr, target):
    for i in range(len(arr)):
        if arr[i] == target:
            return i
    return -1

def binary_search(arr, target):
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1

def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                temp = arr[j]
                arr[j] = arr[j + 1]
                arr[j + 1] = temp
    return arr

def count_vowels(s):
    count = 0
    vowels = "aeiouAEIOU"
    for i in range(len(s)):
        if s[i] in vowels:
            count += 1
    return count

def calculate_power(base, exp):
    result = 1
    for _ in range(exp):
        result *= base
    return result

def swap(a, b):
    a = a + b
    b = a - b
    a = a - b
    return a, b

def celsius_to_fahrenheit(c):
    return (c * 9.0 / 5.0) + 32.0

def gcd(a, b):
    while b != 0:
        temp = b
        b = a % b
        a = temp
    return a

def is_leap_year(year):
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return True
    return False
"""

ALGORITHM_CALLS = """
values = [3, 1, 2]
print(sum_array(values))
print(max_in_array(values))
print(linear_search(values, 1))
sorted_values = bubble_sort(values)
print(sorted_values[0], sorted_values[1], sorted_values[2])
print(reverse_string("desserts"))
print(count_vowels("hello"))
print(gcd(48, 18))
print(add(2, 3))
print(is_even(4))
print(max_of_three(3, 9, 4))
print(factorial(5))
print(is_prime(17))
print(is_palindrome("level"))
print(binary_search([1, 3, 5, 7], 7))
print(calculate_power(2, 5))
print(celsius_to_fahrenheit(0))
first, second = swap(2, 3)
print(first, second)
print(is_leap_year(2000))
fibonacci(5)
"""


@pytest.mark.parametrize("target", ["java", "cpp", "c"])
def test_all_twenty_standard_algorithms_translate_and_validate(target):
    response = client.post(
        "/api/pipeline",
        json={"code": ALGORITHM_EXAMPLES, "target": target},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["parse"]["status"] == "success", result["parse"]
    assert result["semantic"]["status"] == "success", result["semantic"]
    assert result["translate"]["status"] == "success", result["translate"]
    assert result["validate"]["result"]["is_valid"], result["validate"]


@pytest.mark.parametrize(
    ("target", "compiler", "standard"),
    [("cpp", "g++", "c++17"), ("c", "gcc", "c11")],
)
def test_native_algorithm_output_compiles_and_runs(target, compiler, standard):
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        pytest.skip(f"{compiler} is not installed.")

    response = client.post(
        "/api/pipeline",
        json={"code": ALGORITHM_EXAMPLES, "target": target},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    generated = result["translate"]["result"]["code"]

    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / ("generated.cpp" if target == "cpp" else "generated.c")
        executable = Path(directory) / "generated.exe"
        source_path.write_text(generated, encoding="utf-8")
        compilation = subprocess.run(
            [
                compiler_path, f"-std={standard}", str(source_path), "-lm",
                "-o", str(executable),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert compilation.returncode == 0, compilation.stderr
        execution = subprocess.run(
            [str(executable)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert execution.returncode == 0, execution.stderr
        assert execution.stdout == "Hello, World!\n"


def test_java_algorithm_output_compiles_runs_and_matches_python():
    response = client.post(
        "/api/pipeline",
        json={"code": ALGORITHM_EXAMPLES, "target": "java"},
    )
    assert response.status_code == 200, response.text
    generated = response.json()["translate"]["result"]["java_code"]

    result = compile_and_compare(ALGORITHM_EXAMPLES, generated)

    assert result["compile"]["status"] == "success", result["compile"]
    assert result["python"]["status"] == "success", result["python"]
    assert result["java"]["status"] == "success", result["java"]
    assert result["comparison"] == {"status": "match", "equal": True}


@pytest.mark.parametrize(
    ("target", "compiler", "standard"),
    [("cpp", "g++", "c++17"), ("c", "gcc", "c11")],
)
def test_array_and_string_algorithm_calls_work_in_native_output(
    target, compiler, standard
):
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        pytest.skip(f"{compiler} is not installed.")

    program = ALGORITHM_EXAMPLES + ALGORITHM_CALLS
    response = client.post(
        "/api/pipeline",
        json={"code": program, "target": target},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["translate"]["status"] == "success", result["translate"]
    generated = result["translate"]["result"]["code"]

    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / ("generated.cpp" if target == "cpp" else "generated.c")
        executable = Path(directory) / "generated.exe"
        source_path.write_text(generated, encoding="utf-8")
        compilation = subprocess.run(
            [
                compiler_path, f"-std={standard}", str(source_path), "-lm",
                "-o", str(executable),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert compilation.returncode == 0, compilation.stderr
        execution = subprocess.run(
            [str(executable)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert execution.returncode == 0, execution.stderr
        assert execution.stdout == (
            "Hello, World!\n6\n3\n1\n1 2 3\nstressed\n2\n6\n5\nTrue\n9\n"
            "120\nTrue\nTrue\n3\n32\n32\n3 2\nTrue\n0 1 1 2 3 "
        )


def test_java_array_and_string_algorithm_calls_match_python():
    program = ALGORITHM_EXAMPLES + ALGORITHM_CALLS
    response = client.post(
        "/api/pipeline",
        json={"code": program, "target": "java"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["translate"]["status"] == "success", result["translate"]

    execution = compile_and_compare(
        program,
        result["translate"]["result"]["java_code"],
    )

    assert execution["compile"]["status"] == "success", execution["compile"]
    assert execution["comparison"] == {"status": "match", "equal": True}
