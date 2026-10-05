import ast
import json
import re


def _fallback_filename(code: str, spec: str, language: str) -> str:
    # Older/custom providers may still return raw code instead of metadata.
    name = ""
    if language == "python":
        try:
            tree = ast.parse(code)
            name = next((node.name for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), "")
        except SyntaxError:
            pass
    if not name:
        spec = spec.split("Current user message:\n")[-1].split("\n\nPrior Task UI session context:")[0]
        words = re.findall(r"[a-z0-9]+", spec.lower())
        name = "_".join(w for w in words if w not in {
            "create", "generate", "write", "build", "a", "an", "the", "code", "python",
            "program", "function", "that", "to", "for", "in", "of", "please",
        })[:60].rstrip("_") or "generated_module"
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    extension = {"python": ".py", "javascript": ".js", "typescript": ".ts",
                 "java": ".java", "go": ".go", "rust": ".rs", "html": ".html",
                 "css": ".css", "bash": ".sh", "c": ".c", "cpp": ".cpp"}.get(language, ".txt")
    return name + extension


def code_generation(payload: dict, llm_client) -> dict:
    spec = payload["spec"]
    language = payload.get("language", "python")
    context_files = payload.get("context_files", [])

    context_block = ""
    if context_files:
        parts = []
        for f in context_files:
            parts.append(f"# {f.get('path', 'file')}\n{f.get('content', '')}")
        context_block = "\n\nExisting code for conventions:\n" + "\n\n".join(parts)

    memory = payload.get("memory", [])
    if memory:
        context_block += "\n\nRelevant memory:\n" + "\n".join(f"- {m['content']}" for m in memory)

    user_message = (
        f"Write complete {language} code for the following spec.\n"
        "Honor every language and version requirement in the spec exactly. "
        "Unless the spec explicitly requests Python 2, target Python 3. "
        "For example, Python 2 requires Python 2 syntax such as `print value`, "
        "not Python 3-only syntax such as `print(value)`.\n"
        "The result must be directly runnable and must implement the concrete values "
        "in the spec. Do not invent undefined variables or placeholder names. "
        "For a request to add 2 + 2 in Python 2, output exactly `print 2 + 2`.\n"
        'Return a JSON object with "filename" and "code" strings. Choose a concise, '
        'meaningful filename describing the specific domain and purpose of THIS request, '
        'as a developer would. Use snake_case for Python modules. Never use output.py '
        'or main.py as a generic default. Use the correct extension for the language, '
        'honor a filename explicitly requested in the current spec, and use a relative path. '
        'The code field must contain only source code. No markdown fences.\n\n'
        f"Spec:\n{spec}"
        f"{context_block}"
    )

    code = llm_client(
        system=(
            "You are an expert software engineer. "
            "Preserve explicitly requested language versions and runtime compatibility. "
            "Generate complete runnable code with no undefined placeholders. "
            "Return JSON containing a meaningful filename and the complete source code."
        ),
        user=user_message,
    )

    # Strip any accidental markdown fences the model still adds
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

    filename = None
    try:
        response = json.loads(code)
    except json.JSONDecodeError:
        response = None
    if isinstance(response, dict) and isinstance(response.get("code"), str):
        code = response["code"]
        filename = response.get("filename")
    if not isinstance(filename, str) or not filename.strip() or filename in {"output.py", "main.py"}:
        filename = _fallback_filename(code, spec, language)

    return {
        "filename": filename,
        "code": code,
        "language": language,
        "notes": "",
    }
