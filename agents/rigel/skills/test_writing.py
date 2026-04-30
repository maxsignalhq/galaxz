def test_writing(payload: dict, llm_client) -> dict:
    code = payload["code"]
    test_framework = payload.get("test_framework", "pytest")
    focus_areas = payload.get("focus_areas", [])

    focus_block = ""
    if focus_areas:
        focus_block = "\n\nFocus areas: " + ", ".join(focus_areas)

    user_message = (
        f"Write {test_framework} tests for the following code.{focus_block}\n"
        f"Output ONLY the test code — no explanation, no markdown fences, no JSON.\n\n"
        f"Code:\n{code}"
    )

    tests = llm_client(
        system=(
            "You are an expert in software testing. "
            "Output only raw test code — no explanation, no markdown, no JSON wrapper."
        ),
        user=user_message,
    )

    tests = tests.strip()
    if tests.startswith("```"):
        lines = tests.splitlines()
        tests = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

    test_count = tests.count("\ndef test_") + tests.count("\nasync def test_")
    if tests.startswith("def test_") or tests.startswith("async def test_"):
        test_count += 1

    return {
        "tests": tests,
        "test_framework": test_framework,
        "test_count": test_count,
    }
