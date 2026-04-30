import json


def pr_review(payload: dict, llm_client) -> dict:
    diff = payload["diff"]
    codebase_context = payload.get("codebase_context", "")

    context_block = f"\n\nCodebase context:\n{codebase_context}" if codebase_context else ""

    user_message = (
        f"Review this pull request diff.{context_block}\n\n"
        f"Diff:\n{diff}\n\n"
        "You MUST respond with ONLY this JSON object and nothing else — no explanation, no markdown, no code fences:\n"
        '{"findings": [{"severity": "high|medium|low", "file": "<file>", "line": null, "issue": "<issue>", "suggestion": "<suggestion>"}], "summary": "<summary>", "approved": false}'
    )

    response = llm_client(
        system=(
            "You are a senior code reviewer. "
            "You always respond with a single valid JSON object and nothing else. "
            "Never use markdown. Never add explanation outside the JSON."
        ),
        user=user_message,
    )

    parsed = json.loads(response)
    return {
        "findings": parsed.get("findings", []),
        "summary": parsed.get("summary", ""),
        "approved": bool(parsed.get("approved", False)),
    }
