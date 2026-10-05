import pytest

from core.a2a.card import AGENT_CARD_PATH, build_extended_card, build_public_card
from core.a2a.config import CallerConfig
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry


def _skill(skill_id, allowed_origins=None):
    return SkillDefinition(
        skill_id=skill_id,
        description=f"does {skill_id}",
        input_schema={},
        output_schema={},
        allowed_origins=allowed_origins,
    )


@pytest.fixture
def registry(tmp_path):
    reg = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    reg.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[
                _skill("rigel.skill.code_generation"),
                _skill("ops.skill.deploy", ["goal:*"]),
                _skill("partner.skill", ["a2a:alpha"]),
                _skill("nobody.skill", []),
            ],
        )
    )
    reg.register(
        SkillManifest(
            agent_id="wormhole",
            agent_name="Wormhole",
            version="1",
            health_endpoint="http://wormhole:8000/health",
            skills=[_skill("wormhole.translator.translate")],
        )
    )
    return reg


def _ids(card):
    return [s["id"] for s in card["skills"]]


def test_well_known_path():
    assert AGENT_CARD_PATH == "/.well-known/agent-card.json"


def test_public_card_lists_only_unrestricted_skills(registry):
    card = build_public_card(registry, "https://galaxz.example")
    assert _ids(card) == ["rigel.skill.code_generation"]


def test_card_required_fields(registry):
    card = build_public_card(registry, "https://galaxz.example")
    assert card["name"] and card["description"] and card["version"]
    assert card["supportedInterfaces"] == [
        {"url": "https://galaxz.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ]
    assert card["capabilities"] == {"streaming": True, "pushNotifications": False, "extendedAgentCard": True}
    assert card["securitySchemes"] == {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}}
    assert card["securityRequirements"] == [{"schemes": {"bearer": {"list": []}}}]
    assert card["defaultInputModes"] == ["application/json"]
    assert card["defaultOutputModes"] == ["application/json"]
    skill = card["skills"][0]
    assert skill["name"] and skill["description"] and skill["tags"] == ["rigel"]


def test_extended_card_respects_origin_policy(registry):
    alpha = CallerConfig("t", "a2a:alpha")
    card = build_extended_card(registry, "https://galaxz.example", alpha)
    assert _ids(card) == ["partner.skill", "rigel.skill.code_generation"]
    beta = CallerConfig("t", "a2a:beta")
    assert _ids(build_extended_card(registry, "https://galaxz.example", beta)) == ["rigel.skill.code_generation"]


def test_extended_card_respects_caller_skill_allow_list(registry):
    scoped = CallerConfig("t", "a2a:alpha", skills=("partner.*",))
    assert _ids(build_extended_card(registry, "https://galaxz.example", scoped)) == ["partner.skill"]


def test_wormhole_skills_never_published(registry):
    caller = CallerConfig("t", "a2a:alpha")
    assert "wormhole.translator.translate" not in _ids(build_public_card(registry, "https://x"))
    assert "wormhole.translator.translate" not in _ids(build_extended_card(registry, "https://x", caller))


def test_duplicate_skill_ids_listed_once(registry):
    registry.register(
        SkillManifest(
            agent_id="rigel2",
            agent_name="Rigel 2",
            version="1",
            health_endpoint="http://rigel2:8000/health",
            skills=[_skill("rigel.skill.code_generation")],
        )
    )
    assert _ids(build_public_card(registry, "https://x")).count("rigel.skill.code_generation") == 1
