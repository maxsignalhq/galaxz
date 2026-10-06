"""Ed25519-signed scorecards with a detached payload (no canonicalization needed to verify)."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

KEY_PATH_ENV = "GALAXZ_SCORECARD_KEY_PATH"
KEY_PEM_ENV = "GALAXZ_SCORECARD_KEY"
ALG = "Ed25519"


class ScorecardError(ValueError):
    pass


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError, TypeError):
        raise ScorecardError("invalid base64") from None


def canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def _raw_public(key: ed25519.Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def generate_private_key_pem() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


class ScorecardSigner:
    def __init__(self, private_key: ed25519.Ed25519PrivateKey):
        self._key = private_key
        self._public_raw = _raw_public(private_key.public_key())

    @classmethod
    def from_pem(cls, pem: str | bytes) -> "ScorecardSigner":
        data = pem.encode() if isinstance(pem, str) else pem
        try:
            key = serialization.load_pem_private_key(data, password=None)
        except (ValueError, TypeError):
            raise ScorecardError("scorecard signing key is not a valid PEM private key") from None
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise ScorecardError("scorecard signing key must be an Ed25519 key")
        return cls(key)

    @property
    def kid(self) -> str:
        return key_id(self._public_raw)

    @property
    def public_key_b64(self) -> str:
        return _b64e(self._public_raw)

    def public_key_info(self) -> dict:
        return {"alg": ALG, "kid": self.kid, "public_key": self.public_key_b64}

    def sign(self, scorecard: dict) -> dict:
        payload = canonical_json(scorecard)
        return {
            "payload": _b64e(payload),
            "scorecard": scorecard,
            "signature": {"alg": ALG, "kid": self.kid, "value": _b64e(self._key.sign(payload))},
        }


def load_signer(environ=None) -> ScorecardSigner | None:
    """None when signing is not configured; raises ScorecardError when it is configured badly."""
    environ = os.environ if environ is None else environ
    path = environ.get(KEY_PATH_ENV)
    if path:
        try:
            with open(path, "rb") as f:
                return ScorecardSigner.from_pem(f.read())
        except OSError:
            raise ScorecardError("scorecard signing key file cannot be read") from None
    pem = environ.get(KEY_PEM_ENV)
    if pem:
        return ScorecardSigner.from_pem(pem)
    return None


def verify_envelope(envelope: dict, public_key: str) -> dict:
    """Return the verified scorecard; raise ScorecardError if anything does not check out."""
    if not isinstance(envelope, dict):
        raise ScorecardError("envelope must be an object")
    payload_b64 = envelope.get("payload")
    signature = envelope.get("signature")
    if not isinstance(payload_b64, str) or not isinstance(signature, dict):
        raise ScorecardError("envelope needs a payload and a signature")
    if signature.get("alg") != ALG:
        raise ScorecardError(f"unsupported signature algorithm {signature.get('alg')!r}")
    value = signature.get("value")
    if not isinstance(value, str):
        raise ScorecardError("signature has no value")
    public_raw = _b64d(public_key)
    if len(public_raw) != 32:
        raise ScorecardError("public key must be a raw 32-byte Ed25519 key")
    kid = signature.get("kid")
    if kid is not None and kid != key_id(public_raw):
        raise ScorecardError("signature was made by a different key")
    payload = _b64d(payload_b64)
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_raw).verify(_b64d(value), payload)
    except InvalidSignature:
        raise ScorecardError("signature does not match the payload") from None
    try:
        scorecard = json.loads(payload)
    except ValueError:
        raise ScorecardError("payload is not valid JSON") from None
    if "scorecard" in envelope and envelope["scorecard"] != scorecard:
        raise ScorecardError("scorecard field does not match the signed payload")
    return scorecard
