import json


def debug_triage(payload: dict, llm_client) -> dict:
    error_trace = payload["error_trace"]
    context = payload.get("context", "")
    language = payload.get("language", "")

    language_hint = f" ({language})" if language else ""
    context_block = f"\n\nAdditional context:\n{context}" if context else ""

    user_message = (
        f"Triage the following error{language_hint}.{context_block}\n\n"
        f"Error trace:\n{error_trace}\n\n"
        "You MUST respond with ONLY this JSON object and nothing else — no explanation, no markdown, no code fences:\n"
        '{"root_cause_hypothesis": "<hypothesis>", "confidence": 0.0, "suggested_fix_approach": "<approach>", "next_step": "code_generation"}'
    )

    response = llm_client(
        system=(
            "You are an expert debugger. "
            "You always respond with a single valid JSON object and nothing else. "
            "Never use markdown. Never add explanation outside the JSON."
        ),
        user=user_message,
    )

    parsed = json.loads(response)
    return {
        "root_cause_hypothesis": parsed["root_cause_hypothesis"],
        "confidence": float(parsed.get("confidence", 0.5)),
        "suggested_fix_approach": parsed.get("suggested_fix_approach", ""),
        "next_step": parsed.get("next_step", "manual_review"),
    }
