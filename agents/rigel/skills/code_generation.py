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

    user_message = (
        f"Write complete {language} code for the following spec.\n"
        f"Output ONLY the code itself — no explanation, no markdown fences, no JSON.\n\n"
        f"Spec:\n{spec}"
        f"{context_block}"
    )

    code = llm_client(
        system=(
            "You are an expert software engineer. "
            "Output only raw code — no explanation, no markdown, no JSON wrapper."
        ),
        user=user_message,
    )

    # Strip any accidental markdown fences the model still adds
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

    return {
        "code": code,
        "language": language,
        "notes": "",
    }
