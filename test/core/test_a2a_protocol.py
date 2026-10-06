from core.a2a import protocol as p


def test_rpc_error_carries_code_and_reason():
    body = p.rpc_error(7, p.task_not_found())
    assert body == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {
            "code": -32050,
            "message": "Task not found or not accessible",
            "data": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "TASK_NOT_FOUND",
                        "domain": "a2a-protocol.org",
                    }
                ]
            },
        },
    }


def test_rpc_error_without_reason_has_no_data():
    body = p.rpc_error(None, p.parse_error())
    assert body["error"] == {"code": -32700, "message": "Parse error"}
    assert body["id"] is None


def test_error_factories_use_expected_codes():
    assert p.task_not_cancelable().code == -32051
    assert p.unsupported_operation().code == -32052
    assert p.version_not_supported().code == -32055
    assert p.invalid_params("bad").code == -32602
    assert p.invalid_request("big").code == -32600


def test_rpc_result_envelope():
    assert p.rpc_result("a", {"x": 1}) == {"jsonrpc": "2.0", "id": "a", "result": {"x": 1}}


def test_make_task_minimal():
    task = p.make_task("abc", p.STATE_WORKING)
    assert task["id"] == "abc"
    assert task["contextId"] == "abc"
    assert task["status"]["state"] == "TASK_STATE_WORKING"
    assert task["status"]["timestamp"].endswith("Z")
    assert "message" not in task["status"]
    assert "artifacts" not in task


def test_make_task_with_message_and_artifacts():
    artifact = {"artifactId": "r", "parts": [{"data": {"k": 1}}]}
    task = p.make_task("abc", p.STATE_FAILED, context_id="ctx", message_text="nope", artifacts=[artifact])
    assert task["contextId"] == "ctx"
    msg = task["status"]["message"]
    assert msg["role"] == "ROLE_AGENT"
    assert msg["parts"] == [{"text": "nope"}]
    assert msg["messageId"]
    assert task["artifacts"] == [artifact]


def test_state_sets():
    assert p.STATE_COMPLETED in p.TERMINAL_STATES
    assert p.STATE_INPUT_REQUIRED not in p.TERMINAL_STATES
    assert p.STATE_INPUT_REQUIRED in p.STOP_STATES
    assert p.STATE_WORKING not in p.STOP_STATES
