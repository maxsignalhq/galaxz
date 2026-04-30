import json


def scaffold(payload: dict, llm_client) -> dict:
    project_type = payload["project_type"]
    stack = payload["stack"]
    features = payload.get("features", [])

    features_block = ""
    if features:
        features_block = "\n\nRequired features: " + ", ".join(features)

    user_message = (
        f"Scaffold a {project_type} project using {stack}.{features_block}\n\n"
        "You MUST respond with ONLY this JSON object and nothing else — no explanation, no markdown, no code fences:\n"
        '{"file_tree": {}, "files": [{"path": "<path>", "content": "<content>"}], "instructions": "<setup instructions>"}'
    )

    response = llm_client(
        system=(
            "You are an expert software architect. "
            "You always respond with a single valid JSON object and nothing else. "
            "Never use markdown. Never add explanation outside the JSON."
        ),
        user=user_message,
    )

    parsed = json.loads(response)
    return {
        "file_tree": parsed.get("file_tree", {}),
        "files": parsed.get("files", []),
        "instructions": parsed.get("instructions", ""),
    }
