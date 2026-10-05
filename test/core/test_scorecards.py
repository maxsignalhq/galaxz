import asyncio
import copy
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.scorecards import (
    MIN_TASKS,
    ScorecardError,
    ScorecardSigner,
    build_scorecards,
    generate_private_key_pem,
    load_signer,
    verify_envelope,
    wilson_interval,
)
from core.scorecards.signing import canonical_json
from orion.storage.event_log import EventLog

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


# ---- signing -------------------------------------------------------------


@pytest.fixture
def signer():
    return ScorecardSigner.from_pem(generate_private_key_pem())


def test_sign_and_verify_round_trip(signer):
    card = {"subject": {"agent_id": "rigel"}, "metrics": {"tasks": 3, "success_rate": 0.5}}
    envelope = signer.sign(card)
    assert envelope["signature"]["alg"] == "Ed25519"
    assert envelope["signature"]["kid"] == signer.kid
    assert verify_envelope(envelope, signer.public_key_b64) == card


def test_envelope_survives_json_transport(signer):
    envelope = json.loads(json.dumps(signer.sign({"a": 1.5, "b": ["x", None], "c": "é"})))
    assert verify_envelope(envelope, signer.public_key_b64) == {"a": 1.5, "b": ["x", None], "c": "é"}


def test_tampered_payload_is_rejected(signer):
    envelope = signer.sign({"metrics": {"success_rate": 0.1}})
    forged = canonical_json({"metrics": {"success_rate": 0.99}})
    import base64

    envelope["payload"] = base64.urlsafe_b64encode(forged).rstrip(b"=").decode()
    with pytest.raises(ScorecardError, match="does not match"):
        verify_envelope(envelope, signer.public_key_b64)


def test_edited_mirror_field_is_rejected_even_though_signature_is_valid(signer):
    envelope = signer.sign({"metrics": {"success_rate": 0.1}})
    envelope["scorecard"]["metrics"]["success_rate"] = 0.99
    with pytest.raises(ScorecardError, match="scorecard field"):
        verify_envelope(envelope, signer.public_key_b64)


def test_mirror_is_optional(signer):
    envelope = signer.sign({"x": 1})
    del envelope["scorecard"]
    assert verify_envelope(envelope, signer.public_key_b64) == {"x": 1}


def test_wrong_key_is_rejected(signer):
    other = ScorecardSigner.from_pem(generate_private_key_pem())
    envelope = signer.sign({"x": 1})
    with pytest.raises(ScorecardError, match="different key"):
        verify_envelope(envelope, other.public_key_b64)
    del envelope["signature"]["kid"]  # without the kid hint the signature itself must fail
    with pytest.raises(ScorecardError, match="does not match"):
        verify_envelope(envelope, other.public_key_b64)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.pop("payload"),
        lambda e: e.pop("signature"),
        lambda e: e["signature"].update(alg="HS256"),
        lambda e: e["signature"].pop("value"),
        lambda e: e["signature"].update(value="!!!not-base64!!!"),
        lambda e: e.update(payload="***"),
    ],
)
def test_malformed_envelopes_raise_scorecard_error(signer, mutate):
    envelope = copy.deepcopy(signer.sign({"x": 1}))
    mutate(envelope)
    with pytest.raises(ScorecardError):
        verify_envelope(envelope, signer.public_key_b64)


def test_non_object_envelope_and_bad_public_key(signer):
    with pytest.raises(ScorecardError):
        verify_envelope([1], signer.public_key_b64)
    with pytest.raises(ScorecardError, match="32-byte"):
        verify_envelope(signer.sign({"x": 1}), "AAAA")


def test_kid_is_stable_and_public_info_matches(signer):
    info = signer.public_key_info()
    assert info == {"alg": "Ed25519", "kid": signer.kid, "public_key": signer.public_key_b64}
    assert len(signer.kid) == 16


def test_load_signer_from_path_inline_or_nothing(tmp_path):
    pem = generate_private_key_pem()
    key_file = tmp_path / "k.pem"
    key_file.write_text(pem)
    assert load_signer({}) is None
    assert load_signer({"GALAXZ_SCORECARD_KEY_PATH": str(key_file)}).kid == ScorecardSigner.from_pem(pem).kid
    assert load_signer({"GALAXZ_SCORECARD_KEY": pem}).kid == ScorecardSigner.from_pem(pem).kid


def test_load_signer_fails_loudly_when_configured_badly(tmp_path):
    with pytest.raises(ScorecardError, match="cannot be read"):
        load_signer({"GALAXZ_SCORECARD_KEY_PATH": str(tmp_path / "missing.pem")})
    with pytest.raises(ScorecardError, match="valid PEM"):
        load_signer({"GALAXZ_SCORECARD_KEY": "not a key"})


def test_rsa_keys_are_refused():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(ScorecardError, match="Ed25519"):
        ScorecardSigner.from_pem(rsa_pem)


def test_non_finite_numbers_cannot_be_signed(signer):
    with pytest.raises(ValueError):
        signer.sign({"x": float("nan")})


# ---- metrics -------------------------------------------------------------


def test_wilson_interval_widens_for_small_samples():
    lo3, hi3 = wilson_interval(3, 3)
    lo3000, hi3000 = wilson_interval(3000, 3000)
    assert lo3 < 0.5 and hi3 == 1.0  # three wins prove little
    assert lo3000 > 0.99
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo, hi = wilson_interval(5, 10)
    assert 0.0 <= lo < 0.5 < hi <= 1.0


def _events_db(tmp_path, rows):
    path = str(tmp_path / "events.db")
    asyncio.run(EventLog().init_db(path))
    with sqlite3.connect(path) as conn:
        for i, row in enumerate(rows):
            conn.execute(
                "INSERT INTO events (id, task_id, skill_id, agent_id, domain, outcome, confidence, "
                "human_verified, latency_ms, created_at, quarantined) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"e{i}", f"t{i}", row.get("skill", "rigel.skill.code_generation"), row.get("agent", "rigel"),
                    "code", row.get("outcome", "success"), row.get("confidence", 0.9), row.get("verified", 0),
                    row.get("latency", 100), row.get("created", "2026-10-04 12:00:00"), row.get("quarantined", 0),
                ),
            )
    return path


def test_missing_database_has_no_scorecards(tmp_path):
    assert build_scorecards(str(tmp_path / "nope.db"), now=NOW) == []


def test_scorecard_metrics(tmp_path):
    rows = (
        [{"outcome": "success", "confidence": 0.9, "latency": 100 + i, "verified": 1 if i < 5 else 0} for i in range(20)]
        + [{"outcome": "fail", "confidence": 0.1, "latency": 500}] * 4
        + [{"outcome": "partial", "confidence": 0.5, "latency": 300}] * 4
    )
    [card] = build_scorecards(_events_db(tmp_path, rows), issuer="acme", now=NOW)
    assert card["version"] == "1.0" and card["issuer"] == "acme"
    assert card["subject"] == {"agent_id": "rigel", "skill_id": "rigel.skill.code_generation"}
    assert card["issued_at"] == "2026-10-05T12:00:00Z"
    assert card["window"] == {"from": "2026-09-05T12:00:00Z", "to": "2026-10-05T12:00:00Z", "days": 30}
    m = card["metrics"]
    assert m["tasks"] == 28
    assert m["success_rate"] == round(20 / 28, 4)
    assert m["fail_rate"] == round(4 / 28, 4) and m["partial_rate"] == round(4 / 28, 4)
    lo, hi = m["success_rate_ci95"]
    assert lo < m["success_rate"] < hi
    assert m["avg_confidence"] == round((20 * 0.9 + 4 * 0.1 + 4 * 0.5) / 28, 4)
    assert m["human_verified_rate"] == round(5 / 28, 4)
    assert m["latency_ms_p50"] == 113 and m["latency_ms_p95"] == 500
    assert card["sample"] == {"min_tasks": MIN_TASKS, "sufficient": True}


def test_small_samples_are_flagged_insufficient(tmp_path):
    [card] = build_scorecards(_events_db(tmp_path, [{}, {}, {}]), now=NOW)
    assert card["metrics"]["tasks"] == 3 and card["metrics"]["success_rate"] == 1.0
    assert card["sample"]["sufficient"] is False
    assert card["metrics"]["success_rate_ci95"][0] < 0.5


def test_quarantined_events_and_old_events_are_excluded(tmp_path):
    rows = [
        {"quarantined": 1, "outcome": "fail"},
        {"created": "2026-08-01 00:00:00", "outcome": "fail"},
        {"outcome": "success"},
    ]
    [card] = build_scorecards(_events_db(tmp_path, rows), now=NOW)
    assert card["metrics"]["tasks"] == 1 and card["metrics"]["success_rate"] == 1.0


def test_window_days_changes_what_is_counted(tmp_path):
    path = _events_db(tmp_path, [{"created": "2026-09-20 00:00:00"}, {"created": "2026-10-04 00:00:00"}])
    assert build_scorecards(path, days=30, now=NOW)[0]["metrics"]["tasks"] == 2
    assert build_scorecards(path, days=7, now=NOW)[0]["metrics"]["tasks"] == 1
    assert build_scorecards(path, days=1, now=NOW) == []


def test_scorecards_are_grouped_by_skill_and_agent_and_filterable(tmp_path):
    rows = [
        {"skill": "b.skill", "agent": "b"},
        {"skill": "a.skill", "agent": "a"},
        {"skill": "a.skill", "agent": "a2"},
    ]
    path = _events_db(tmp_path, rows)
    cards = build_scorecards(path, now=NOW)
    assert [(c["subject"]["skill_id"], c["subject"]["agent_id"]) for c in cards] == [
        ("a.skill", "a"),
        ("a.skill", "a2"),
        ("b.skill", "b"),
    ]
    only = build_scorecards(path, skill_id="b.skill", now=NOW)
    assert [c["subject"]["agent_id"] for c in only] == ["b"]


def test_null_latency_does_not_break_percentiles(tmp_path):
    [card] = build_scorecards(_events_db(tmp_path, [{"latency": None}, {"latency": 40}]), now=NOW)
    assert card["metrics"]["latency_ms_p50"] == 40


def test_all_null_latencies_give_null_percentiles(tmp_path):
    [card] = build_scorecards(_events_db(tmp_path, [{"latency": None}]), now=NOW)
    assert card["metrics"]["latency_ms_p50"] is None and card["metrics"]["latency_ms_p95"] is None
