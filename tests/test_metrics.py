from unittest.mock import patch

from olmocr.metrics import MetricsKeeper


def test_recent_rate_expires_without_new_samples():
    with patch("olmocr.metrics.time.time", return_value=0) as clock:
        metrics = MetricsKeeper(window=10)
        metrics.add_metrics(tokens=100)
        clock.return_value = 11
        row = next(line for line in str(metrics).splitlines() if line.startswith("tokens"))
        assert float(row.split()[-1]) == 0
        assert metrics.get_total_metrics() == {"tokens": 100}


def test_recent_rate_keeps_only_samples_inside_window():
    with patch("olmocr.metrics.time.time", return_value=0) as clock:
        metrics = MetricsKeeper(window=10)
        metrics.add_metrics(tokens=100)
        clock.return_value = 5
        metrics.add_metrics(tokens=20)
        clock.return_value = 11
        row = next(line for line in str(metrics).splitlines() if line.startswith("tokens"))
        assert float(row.split()[-1]) == 2
        assert metrics.get_total_metrics() == {"tokens": 120}
