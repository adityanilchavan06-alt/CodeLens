# Optional CodeT5 fine-tuning

The web app does not need this step or the ML dependencies: it always has a
rule-based translator. These scripts are for a teammate who has paired
Python-to-Java training data and access to a GPU when available.

## Prepare the training data

Create a UTF-8 JSONL file with one pair per line:

```json
{"python_code":"answer = 6 * 7\nprint(answer)","java_code":"import java.util.ArrayList;\nimport java.util.Arrays;\nimport java.util.List;\n\npublic class CodeLensProgram {\n    public static void main(String[] args) {\n        int answer = (6 * 7);\n        System.out.println(answer);\n    }\n}\n"}
```

From the project root:

```powershell
python -m pip install -r ml\requirements.txt
python ml\prepare_data.py --input data\pairs.jsonl --output data\prepared.jsonl
python ml\train.py --data data\prepared.jsonl --output trained-codet5
```

Training uses `Salesforce/codet5-small` unless `--base-model` is supplied.
The input is a JSON serialization of the lexer tokens and nested Python AST.
The expected target is a complete Java source file, including the
`CodeLensProgram` wrapper.

## Use a hosted Hugging Face model

The backend can send the source code and backend-generated lexer tokens to a
hosted chat model. The model returns a JSON object containing a Python AST and
complete Java source. The backend checks the response shape and validates the
generated Java syntax. Set a Hugging Face access token in the backend's
environment; never put the token in frontend code:

```powershell
$env:HF_TOKEN = "hf_your_token"
$env:HF_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
```

`HF_MODEL` is optional; the shown model is the default. The selected model must
be available to your Hugging Face Inference Providers account. Restart the
backend after setting these variables. If the token is absent or the hosted
request fails, the API reports the reason and uses the rule-based translator.
Hosted providers do not return comparable token-level confidence scores, so
the validation panel reports confidence as unavailable for this mode.

## Use a locally fine-tuned model

Set `MODEL_PATH` to the local training output directory before starting the
backend. The model and tokenizer load only when the first translation request
arrives. If the path, optional packages, or model cannot be loaded, the API
reports a fallback reason and uses rule-based translation.

```powershell
$env:MODEL_PATH = "D:\models\trained-codet5"
```

The validation confidence for model output is the mean probability of its
generated tokens. This is a generation confidence indicator, not a guarantee
that the translation is semantically correct.
