import textwrap

import pytest

from core.policy import (
    ALLOW,
    DENY,
    REQUIRE_REVIEW,
    PolicyConfigError,
    PolicyEngine,
    PolicyRule,
    load_policy,
    payload_digest,
)


def _engine(*rules):
    return PolicyEngine(tuple(rules))


def test_empty_policy_allows_everything_and_is_disabled():
    engine = PolicyEngine()
    assert engine.enabled is False
    assert engine.evaluate(["quasar.fs.write"], "a2a:x").action == ALLOW


def test_first_matching_rule_wins():
    engine = _engine(
        PolicyRule("quasar.fs.read", REQUIRE_REVIEW, reason="reads need review"),
        PolicyRule("quasar.fs.*", DENY),
    )
    read = engine.evaluate_skill("quasar.fs.read", "a2a:x")
    assert (read.action, read.reason, read.rule_index) == (REQUIRE_REVIEW, "reads need review", 0)
    write = engine.evaluate_skill("quasar.fs.write", "a2a:x")
    assert (write.action, write.rule_index) == (DENY, 1)
    assert write.reason == "policy rule 1"
    assert engine.evaluate_skill("rigel.skill.code_generation", "a2a:x").action == ALLOW


def test_origin_pattern_defaults_to_any_and_filters():
    engine = _engine(PolicyRule("ops.*", DENY, origin="a2a:*"))
    assert engine.evaluate_skill("ops.deploy", "a2a:partner").action == DENY
    assert engine.evaluate_skill("ops.deploy", "goal:123").action == ALLOW
    assert engine.evaluate_skill("ops.deploy", None).action == ALLOW
    assert _engine(PolicyRule("ops.*", DENY)).evaluate_skill("ops.deploy", None).action == DENY


def test_strictest_decision_wins_across_skills():
    engine = _engine(PolicyRule("a.*", REQUIRE_REVIEW), PolicyRule("b.*", DENY))
    assert engine.evaluate(["a.x"], "o").action == REQUIRE_REVIEW
    assert engine.evaluate(["a.x", "b.y"], "o").action == DENY
    assert engine.evaluate(["c.z", "a.x"], "o").action == REQUIRE_REVIEW


def test_payload_digest_is_stable_and_sensitive():
    base = payload_digest("o", "s", {"a": 1, "b": [1, 2]})
    assert base == payload_digest("o", "s", {"b": [1, 2], "a": 1})
    assert base != payload_digest("o2", "s", {"a": 1, "b": [1, 2]})
    assert base != payload_digest("o", "s2", {"a": 1, "b": [1, 2]})
    assert base != payload_digest("o", "s", {"a": 2, "b": [1, 2]})
    assert payload_digest(None, "s", {}) == payload_digest("", "s", {})


def _write(tmp_path, body):
    path = tmp_path / "policy.yaml"
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_shipped_default_policy_is_empty():
    assert load_policy("config/policy.yaml").enabled is False


def test_missing_file_or_null_rules_means_no_policy(tmp_path):
    assert load_policy(str(tmp_path / "nope.yaml")).enabled is False
    assert load_policy(_write(tmp_path, "rules:\n")).enabled is False
    assert load_policy(_write(tmp_path, "")).enabled is False


def test_load_policy_parses_rules(tmp_path):
    engine = load_policy(
        _write(
            tmp_path,
            """
            rules:
              - skill: "quasar.fs.*"
                origin: "a2a:*"
                action: require_review
                reason: "needs a human"
              - {skill: "quasar.shell.*", action: deny}
            """,
        )
    )
    assert engine.rules == (
        PolicyRule("quasar.fs.*", REQUIRE_REVIEW, "a2a:*", "needs a human"),
        PolicyRule("quasar.shell.*", DENY, "*", ""),
    )


def test_load_policy_path_comes_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXZ_POLICY_PATH", _write(tmp_path, "rules:\n  - {skill: x.*, action: deny}\n"))
    assert load_policy().enabled is True


@pytest.mark.parametrize(
    "body",
    [
        "rules: [",  # invalid yaml
        "- just\n- a list\n",  # top level not a mapping
        "rules: nope\n",  # rules not a list
        "rules:\n  - not-a-mapping\n",
        "rules:\n  - {action: deny}\n",  # missing skill
        "rules:\n  - {skill: '  ', action: deny}\n",
        "rules:\n  - {skill: a.*}\n",  # missing action
        "rules:\n  - {skill: a.*, action: allow}\n",  # allow is not a rule action
        "rules:\n  - {skill: a.*, action: Deny}\n",
        "rules:\n  - {skill: a.*, action: deny, actions: typo}\n",  # unknown key
        "rules:\n  - {skill: a.*, action: deny, origin: ''}\n",
        "rules:\n  - {skill: a.*, action: deny, reason: 5}\n",
    ],
)
def test_malformed_policy_fails_closed(tmp_path, body):
    with pytest.raises(PolicyConfigError):
        load_policy(_write(tmp_path, body))
