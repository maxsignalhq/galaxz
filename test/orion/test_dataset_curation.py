from datetime import datetime, timezone
import json

import pytest

from core.contracts import OutcomeType
from orion.core.dataset_store import DatasetStore
from orion.pipeline.dataset_curation import DatasetCurator
from orion.pipeline.signal_extraction import SignalRecord
from test.conftest import make_feedback_event


@pytest.mark.asyncio
async def test_dataset_curator_writes_success_and_correction_examples(tmp_path):
    store = DatasetStore(str(tmp_path / "datasets"))
    curator = DatasetCurator(store, min_quality_score=0.85)

    high_quality = make_feedback_event(
        task_category="qa.auth",
        confidence_score=0.94,
        agent_output={
            "input": {"request": "login"},
            "output": {"response": "jwt"},
        },
    )
    correction = make_feedback_event(
        task_category="qa.auth",
        outcome=OutcomeType.corrected,
        confidence_score=0.55,
        human_verified=True,
        human_correction={"output": "return 400 for invalid password"},
        agent_output={
            "input": {"password": "invalid"},
            "output": {"response": "return 200"},
        },
    )
    low_quality = make_feedback_event(
        task_category="qa.auth",
        confidence_score=0.80,
        agent_output={
            "input": {"request": "slow login"},
            "output": {"response": "retry"},
        },
    )

    signal = SignalRecord(
        domain="qa.auth",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        total_events=3,
        completed_count=2,
        failed_count=0,
        escalated_count=0,
        corrected_count=1,
        avg_confidence=0.7633,
        correction_rate=0.3333,
        escalation_rate=0.0,
        high_quality_events=[high_quality, low_quality],
        correction_pairs=[(correction, correction.human_correction)],
    )

    result = await curator.curate(signal)
    stats = store.stats("vega")
    examples = store._buffers["vega"]

    assert result.examples_added == 2
    assert result.success_examples == 1
    assert result.correction_examples == 1
    assert result.skipped == 1
    assert stats["buffered"] == 2
    assert {example["quality_weight"] for example in examples} == {1.0, 0.94}

    for example in examples:
        assert json.loads(example["prompt"])
        assert json.loads(example["completion"])
        assert example["domain"] == "vega"

    correction_example = next(example for example in examples if example["human_verified"])
    assert json.loads(correction_example["completion"]) == {
        "output": "return 400 for invalid password"
    }
