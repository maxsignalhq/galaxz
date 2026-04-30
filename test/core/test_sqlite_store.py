import pytest

from core.pulsar.sqlite_store import SqliteStore

_AGENT = {
    "agent_id": "vega",
    "agent_name": "Vega QA Agent",
    "skills": [{"skill_id": "qa.test", "name": "QA Test"}],
}
_AGENT2 = {
    "agent_id": "rigel",
    "agent_name": "Rigel Eng Agent",
    "skills": [{"skill_id": "eng.code", "name": "Code Gen"}],
}


@pytest.fixture
def store(tmp_path):
    return SqliteStore(f"sqlite://{tmp_path}/pulsar.db")


# register_agent + get_agent

def test_register_and_get(store):
    store.register_agent("vega", _AGENT)
    assert store.get_agent("vega") == _AGENT


def test_get_missing_returns_none(store):
    assert store.get_agent("nonexistent") is None


def test_register_upserts(store):
    store.register_agent("vega", _AGENT)
    updated = {**_AGENT, "agent_name": "Vega QA v2"}
    store.register_agent("vega", updated)
    assert store.get_agent("vega")["agent_name"] == "Vega QA v2"
    assert len(store.list_agents()) == 1


# list_agents

def test_list_agents_empty(store):
    assert store.list_agents() == []


def test_list_agents_multiple(store):
    store.register_agent("vega", _AGENT)
    store.register_agent("rigel", _AGENT2)
    ids = {a["agent_id"] for a in store.list_agents()}
    assert ids == {"vega", "rigel"}


# deregister_agent

def test_deregister_removes_agent(store):
    store.register_agent("vega", _AGENT)
    store.deregister_agent("vega")
    assert store.get_agent("vega") is None
    assert store.list_agents() == []


def test_deregister_missing_is_noop(store):
    store.deregister_agent("nonexistent")  # must not raise


# get_agent_skills

def test_get_agent_skills(store):
    store.register_agent("vega", _AGENT)
    assert store.get_agent_skills("vega") == _AGENT["skills"]


def test_get_agent_skills_missing_agent(store):
    assert store.get_agent_skills("nonexistent") == []


def test_get_agent_skills_no_skills_key(store):
    store.register_agent("bare", {"agent_id": "bare"})
    assert store.get_agent_skills("bare") == []


# persistence across reconnect

def test_persists_across_reconnect(tmp_path):
    path = str(tmp_path / "pulsar.db")
    SqliteStore(f"sqlite://{path}").register_agent("vega", _AGENT)
    assert SqliteStore(f"sqlite://{path}").get_agent("vega") == _AGENT
