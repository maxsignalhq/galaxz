import threading

import pytest
from cryptography.fernet import Fernet

from core.secrets import SecretScope, SecretStore
from core.secrets.resolver import SecretResolutionError, SecretResolver, redact_structure

SKILL = "quasar.github.create_issue"


class Provider:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


@pytest.fixture
def store(tmp_path):
    return SecretStore(tmp_path / "secrets.db", Provider(Fernet.generate_key()))


def _resolver(store, org="org-1"):
    return SecretResolver(lambda: store, organization_id=org)


def _put(store, value="tok-123", *, org="org-1", repo="repo-1", task="*", skill=SKILL):
    return store.put(value, SecretScope(org, repo, task, skill))["secret_id"]


def _ref(secret_id):
    return "${{ secrets." + secret_id + " }}"


def test_wildcard_task_scope_matches_any_task_but_not_other_scopes(store):
    secret_id = _put(store)
    assert store.resolve(secret_id, SecretScope("org-1", "repo-1", "any-task", SKILL)) == "tok-123"
    for other in (
        SecretScope("org-2", "repo-1", "t", SKILL),
        SecretScope("org-1", "repo-2", "t", SKILL),
        SecretScope("org-1", "repo-1", "t", "quasar.github.other"),
    ):
        with pytest.raises(PermissionError):
            store.resolve(secret_id, other)


def test_exact_task_scope_still_enforced(store):
    secret_id = _put(store, task="task-1")
    assert store.resolve(secret_id, SecretScope("org-1", "repo-1", "task-1", SKILL)) == "tok-123"
    with pytest.raises(PermissionError):
        store.resolve(secret_id, SecretScope("org-1", "repo-1", "task-2", SKILL))


def test_store_is_usable_from_other_threads(store):
    secret_id = _put(store)
    seen = []
    thread = threading.Thread(
        target=lambda: seen.append(store.resolve(secret_id, SecretScope("org-1", "repo-1", "t", SKILL)))
    )
    thread.start()
    thread.join()
    assert seen == ["tok-123"]


def test_payload_without_references_is_returned_unchanged_and_never_opens_the_store():
    def explode():
        raise AssertionError("store must not be opened")

    payload = {"a": "plain", "n": [1, {"b": "x"}]}
    resolved, values = SecretResolver(explode, organization_id="org-1").resolve(
        payload, skill_id=SKILL, repository_id="repo-1", task_id="t"
    )
    assert resolved == payload and values == []


def test_references_resolve_in_nested_payload_and_input_is_not_mutated(store):
    secret_id = _put(store)
    payload = {"token": _ref(secret_id), "args": {"list": [_ref(secret_id), "keep"]}}
    resolved, values = _resolver(store).resolve(payload, skill_id=SKILL, repository_id="repo-1", task_id="t")
    assert resolved == {"token": "tok-123", "args": {"list": ["tok-123", "keep"]}}
    assert values == ["tok-123"]
    assert payload["token"] == _ref(secret_id)


def test_reference_embedded_in_a_larger_string_is_not_resolved(store):
    secret_id = _put(store)
    payload = {"h": "Bearer " + _ref(secret_id)}
    resolved, values = _resolver(store).resolve(payload, skill_id=SKILL, repository_id="repo-1", task_id="t")
    assert resolved == payload and values == []


def test_non_tool_skill_is_refused_without_decrypting(store):
    secret_id = _put(store, skill="rigel.skill.code_generation")
    with pytest.raises(SecretResolutionError) as err:
        _resolver(store).resolve(
            {"k": _ref(secret_id)}, skill_id="rigel.skill.code_generation", repository_id="repo-1", task_id="t"
        )
    assert err.value.reason == "secret_not_permitted_for_skill"


@pytest.mark.parametrize(
    "kwargs",
    [{"repository_id": "repo-2"}, {"skill_id": "quasar.github.other"}],
)
def test_scope_mismatch_is_reference_unavailable(store, kwargs):
    secret_id = _put(store)
    args = {"skill_id": SKILL, "repository_id": "repo-1", "task_id": "t", **kwargs}
    with pytest.raises(SecretResolutionError) as err:
        _resolver(store).resolve({"k": _ref(secret_id)}, **args)
    assert err.value.reason == "secret_reference_unavailable"


def test_unknown_id_is_reference_unavailable(store):
    with pytest.raises(SecretResolutionError) as err:
        _resolver(store).resolve({"k": _ref("nope")}, skill_id=SKILL, repository_id="repo-1", task_id="t")
    assert err.value.reason == "secret_reference_unavailable"


def test_store_failure_is_store_unavailable():
    def broken():
        raise RuntimeError("GALAXZ_SECRETS_KEY is not configured")

    with pytest.raises(SecretResolutionError) as err:
        SecretResolver(broken, organization_id="org-1").resolve(
            {"k": _ref("x")}, skill_id=SKILL, repository_id="repo-1", task_id="t"
        )
    assert err.value.reason == "secret_store_unavailable"
    assert "GALAXZ_SECRETS_KEY" not in str(err.value)


def test_redact_structure_walks_values_but_leaves_other_types():
    data = {"a": "tok-123", "b": ["x tok-123 y", 7, None, {"c": "tok-123"}], "tok-123": "key stays"}
    assert redact_structure(data, ["tok-123"]) == {
        "a": "[REDACTED]",
        "b": ["x [REDACTED] y", 7, None, {"c": "[REDACTED]"}],
        "tok-123": "key stays",
    }


def test_redact_structure_with_no_values_is_identity():
    data = {"a": "x"}
    assert redact_structure(data, []) is data


def test_goal_payload_substitution_leaves_secret_references_untouched():
    from uuid import uuid4

    from core.contracts import PlannedTask
    from core.goals.substitution import resolve_payload

    reference = "${{ secrets.abc-123 }}"
    task = PlannedTask(project_id=uuid4(), goal_id=uuid4(), skill=SKILL, payload={"token": reference, "n": [reference]})
    assert resolve_payload(task, {}) == {"token": reference, "n": [reference]}
