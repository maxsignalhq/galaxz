import pytest

from core.contracts import OutcomeType
from orion.pipeline.signal_extraction import SignalExtractor
from orion.storage.event_log import EventLog
from test.conftest import make_feedback_event


@pytest.mark.asyncio
async def test_signal_extractor_deduplicates_by_highest_confidence(tmp_path):
    event_log = EventLog()
    await event_log.init_db(str(tmp_path / "events.db"))

    duplicate_low = make_feedback_event(
        task_category="qa.auth",
        input_hash="same-input",
        confidence_score=0.61,
    )
    duplicate_high = make_feedback_event(
        task_category="qa.auth",
        input_hash="same-input",
        confidence_score=0.96,
    )
    failed = make_feedback_event(
        task_category="qa.auth",
        input_hash="failed-input",
        outcome=OutcomeType.failed,
        confidence_score=0.30,
    )
    corrected = make_feedback_event(
        task_category="qa.auth",
        input_hash="corrected-input",
        outcome=OutcomeType.corrected,
        confidence_score=0.75,
        human_correction={"output": "Use bounded retry"},
    )

    for event in (duplicate_low, duplicate_high, failed, corrected):
        await event_log.append(event)

    signal = await SignalExtractor(event_log).extract("qa.auth")

    assert signal.total_events == 3
    assert signal.completed_count == 1
    assert signal.failed_count == 1
    assert signal.corrected_count == 1
    assert signal.avg_confidence == pytest.approx(round((0.96 + 0.30 + 0.75) / 3, 4))
    assert [event.task_id for event in signal.high_quality_events] == [duplicate_high.task_id]
    assert signal.correction_pairs[0][0].task_id == corrected.task_id
    assert signal.correction_pairs[0][1] == {"output": "Use bounded retry"}
