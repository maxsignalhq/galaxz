from core.evaluation import calibrate


def test_calibration_reports_reliability_bins_and_ece():
    records = [{"confidence": 0.9, "success": True}, {"confidence": 0.8, "success": False}] * 10
    report = calibrate(records, minimum_samples=2)
    assert report.sample_count == 20
    assert report.expected_calibration_error is not None
    assert report.insufficient_samples is False
    assert sum(item["count"] for item in report.bins) == 20


def test_small_samples_are_reported_not_overfit():
    report = calibrate([{"confidence": 1.0, "success": True}], minimum_samples=20)
    assert report.expected_calibration_error is None
    assert report.insufficient_samples is True
