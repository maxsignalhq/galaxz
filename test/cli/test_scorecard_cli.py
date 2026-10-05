import json
import os
import stat

from click.testing import CliRunner

from cli.run import galaxz
from core.scorecards import ScorecardSigner


def _invoke(*args):
    return CliRunner().invoke(galaxz, list(args))


def test_keygen_writes_a_private_key_and_prints_the_public_key(tmp_path):
    out = tmp_path / "key.pem"
    result = _invoke("scorecard", "keygen", "--out", str(out))
    assert result.exit_code == 0, result.output
    signer = ScorecardSigner.from_pem(out.read_text())
    assert signer.kid in result.output and signer.public_key_b64 in result.output
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    assert "BEGIN PRIVATE KEY" not in result.output  # the secret is never echoed


def test_keygen_refuses_to_overwrite_an_existing_key(tmp_path):
    out = tmp_path / "key.pem"
    out.write_text("precious")
    result = _invoke("scorecard", "keygen", "--out", str(out))
    assert result.exit_code != 0 and "already exists" in result.output
    assert out.read_text() == "precious"


def _envelope_file(tmp_path, signer, card):
    path = tmp_path / "card.json"
    path.write_text(json.dumps(signer.sign(card)))
    return path


def test_verify_accepts_a_valid_envelope(tmp_path):
    signer = ScorecardSigner.from_pem(open(_keyfile(tmp_path)).read())
    path = _envelope_file(
        tmp_path, signer, {"issuer": "acme", "subject": {"agent_id": "rigel", "skill_id": "s"}, "metrics": {"tasks": 1}}
    )
    result = _invoke("scorecard", "verify", str(path), "--public-key", signer.public_key_b64)
    assert result.exit_code == 0, result.output
    assert "VALID: acme attests rigel / s" in result.output


def test_verify_rejects_tampering_and_wrong_keys(tmp_path):
    signer = ScorecardSigner.from_pem(open(_keyfile(tmp_path)).read())
    path = _envelope_file(tmp_path, signer, {"issuer": "acme", "metrics": {"tasks": 1}})
    envelope = json.loads(path.read_text())
    envelope["scorecard"]["metrics"]["tasks"] = 1000
    path.write_text(json.dumps(envelope))
    bad = _invoke("scorecard", "verify", str(path), "--public-key", signer.public_key_b64)
    assert bad.exit_code != 0 and "INVALID" in bad.output

    path2 = _envelope_file(tmp_path, signer, {"issuer": "acme"})
    other = ScorecardSigner.from_pem(open(_keyfile(tmp_path, "other.pem")).read())
    wrong = _invoke("scorecard", "verify", str(path2), "--public-key", other.public_key_b64)
    assert wrong.exit_code != 0 and "INVALID" in wrong.output


def _keyfile(tmp_path, name="key.pem"):
    out = tmp_path / name
    assert _invoke("scorecard", "keygen", "--out", str(out)).exit_code == 0
    return out
