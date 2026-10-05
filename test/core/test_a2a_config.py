import textwrap

from core.a2a.config import A2AConfig, CallerConfig, load_a2a_config


def _write(tmp_path, body: str):
    path = tmp_path / "a2a.yaml"
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_missing_file_gives_empty_config(tmp_path):
    cfg = load_a2a_config(str(tmp_path / "nope.yaml"), environ={})
    assert cfg == A2AConfig()


def test_shipped_default_is_empty():
    cfg = load_a2a_config("config/a2a.yaml", environ={})
    assert cfg.callers == () and cfg.agents == ()


def test_caller_loaded_with_token_from_env(tmp_path):
    path = _write(
        tmp_path,
        """
        callers:
          - token_env: PARTNER_TOKEN
            origin: "a2a:partner-x"
            skills: ["rigel.*"]
        """,
    )
    cfg = load_a2a_config(path, environ={"PARTNER_TOKEN": "s3cret"})
    assert cfg.callers == (CallerConfig(token="s3cret", origin="a2a:partner-x", skills=("rigel.*",)),)


def test_caller_with_unset_env_is_ignored(tmp_path, caplog):
    path = _write(tmp_path, 'callers:\n  - {token_env: MISSING, origin: "a2a:x"}\n')
    cfg = load_a2a_config(path, environ={})
    assert cfg.callers == ()
    assert "MISSING" in caplog.text


def test_caller_origin_must_use_a2a_prefix(tmp_path):
    path = _write(tmp_path, 'callers:\n  - {token_env: T, origin: "goal:abc"}\n')
    assert load_a2a_config(path, environ={"T": "x"}).callers == ()


def test_caller_missing_fields_or_bad_skills_skipped(tmp_path):
    path = _write(
        tmp_path,
        """
        callers:
          - {origin: "a2a:x"}
          - {token_env: T}
          - {token_env: T, origin: "a2a:y", skills: "rigel.*"}
          - not-a-mapping
        """,
    )
    assert load_a2a_config(path, environ={"T": "x"}).callers == ()


def test_authenticate_accepts_valid_bearer_only():
    cfg = A2AConfig(callers=(CallerConfig("tok-a", "a2a:a"), CallerConfig("tok-b", "a2a:b")))
    assert cfg.authenticate("Bearer tok-b").origin == "a2a:b"
    assert cfg.authenticate("bearer tok-a").origin == "a2a:a"
    assert cfg.authenticate("Bearer wrong") is None
    assert cfg.authenticate("Bearer ") is None
    assert cfg.authenticate("tok-a") is None
    assert cfg.authenticate("") is None
    assert A2AConfig().authenticate("Bearer tok-a") is None


def test_allows_skill_uses_fnmatch():
    assert CallerConfig("t", "a2a:a").allows_skill("anything")
    scoped = CallerConfig("t", "a2a:a", skills=("rigel.*",))
    assert scoped.allows_skill("rigel.skill.code_generation")
    assert not scoped.allows_skill("vega.skill.x")
    assert not CallerConfig("t", "a2a:a", skills=()).allows_skill("rigel.x")


def test_agents_loaded_and_validated(tmp_path):
    path = _write(
        tmp_path,
        """
        agents:
          - name: translator
            url: https://agents.example.com/
            token_env: TR_TOKEN
            timeout_s: 15
            allowed_origins: ["goal:*"]
          - {name: "Bad Name", url: "https://x.example"}
          - {name: nourl, url: "ftp://x.example"}
          - {name: plain, url: "http://localhost:9000"}
        """,
    )
    cfg = load_a2a_config(path, environ={"TR_TOKEN": "tok"})
    assert [a.name for a in cfg.agents] == ["translator", "plain"]
    translator = cfg.agents[0]
    assert translator.url == "https://agents.example.com"
    assert translator.token == "tok"
    assert translator.timeout_s == 15.0
    assert translator.allowed_origins == ["goal:*"]
    assert cfg.agents[1].token is None
    assert cfg.agents[1].timeout_s == 60.0
    assert cfg.agents[1].allowed_origins is None
