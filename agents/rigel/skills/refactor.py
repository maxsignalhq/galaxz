def refactor(payload: dict, llm_client) -> dict:
    code = payload["code"]
    refactor_intent = payload["refactor_intent"]
    language = payload.get("language", "python")

    user_message = (
        f"Refactor the following {language} code.\n"
        f"Intent: {refactor_intent}\n"
        f"Output ONLY the refactored code — no explanation, no markdown fences, no JSON.\n\n"
        f"Code:\n{code}"
    )

    refactored = llm_client(
        system=(
            "You are an expert software engineer specializing in clean code. "
            "Output only raw refactored code — no explanation, no markdown, no JSON wrapper."
        ),
        user=user_message,
    )

    refactored = refactored.strip()
    if refactored.startswith("```"):
        lines = refactored.splitlines()
        refactored = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

    return {
        "refactored_code": refactored,
        "changes_made": [],
        "preserved_behavior": True,
    }
