from orion.core.weights_loader import RoutingWeightsLoader


def test_routing_weights_loader_reads_seed_file():
    loader = RoutingWeightsLoader("orion/config/routing_weights.yaml")

    assert loader.last_version() == 0
    assert loader.is_cold_start("rigel.skill.code_generation") is True
    assert loader.get_weights("rigel.skill.code_generation") == {"vega": 0.0, "rigel": 1.0}
    assert loader.get_weights("missing.skill") == {}


def test_routing_weights_loader_reload_picks_up_version_change(tmp_path):
    weights_path = tmp_path / "routing_weights.yaml"
    weights_path.write_text(
        """
version: 0
source: seed
weights:
  rigel.skill.code_generation:{ vega: 0.0, rigel: 1.0 }
""".strip(),
        encoding="utf-8",
    )
    loader = RoutingWeightsLoader(str(weights_path))

    weights_path.write_text(
        """
version: 1
source: orion
weights:
  rigel.skill.code_generation:{ vega: 1.0, rigel: 0.0 }
""".strip(),
        encoding="utf-8",
    )
    loader.reload()

    assert loader.last_version() == 1
    assert loader.is_cold_start("rigel.skill.code_generation") is False
    assert loader.source == "orion"
    assert loader.get_weights("rigel.skill.code_generation") == {"vega": 1.0, "rigel": 0.0}
