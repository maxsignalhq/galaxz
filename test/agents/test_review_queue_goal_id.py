from agents.andromeda.review_queue import ReviewQueue


def test_enqueue_records_goal_id(tmp_path):
    q = ReviewQueue(db_path=str(tmp_path / "rq.db"))
    q.enqueue(task_id="t1", task_type="s.a", confidence=0.3, payload={}, goal_id="g1")
    item = q.get_by_task_id("t1")
    assert item["goal_id"] == "g1"


def test_goal_id_defaults_none(tmp_path):
    q = ReviewQueue(db_path=str(tmp_path / "rq.db"))
    q.enqueue(task_id="t2", task_type="s.b", confidence=0.3, payload={})
    assert q.get_by_task_id("t2")["goal_id"] is None
