from __future__ import annotations

import numpy as np

from nuboard.alerts import check_series


def _steps(n):
    return np.arange(n, dtype="i8")


def test_quiet_noisy_loss_has_no_alerts():
    rng = np.random.default_rng(0)
    s = _steps(20_000)
    loss = 2 + 3 * np.exp(-s / 3000) + rng.normal(0, 0.03, len(s))
    assert check_series("train/loss", 0, s, loss) == []


def test_spike_is_found_once():
    rng = np.random.default_rng(1)
    s = _steps(10_000)
    loss = 2 + rng.normal(0, 0.02, len(s))
    loss[6000:6005] += 3
    alerts = check_series("train/loss", 0, s, loss)
    assert [a["kind"] for a in alerts] == ["spike"]
    assert 5900 <= alerts[0]["step"] <= 6005 and alerts[0]["value"] > 4


def test_nonfinite_reports_first_step():
    s = _steps(100)
    v = np.ones(100)
    v[40] = np.inf
    v[60:] = np.nan
    (alert,) = check_series("acc", 1, s, v)
    assert alert["kind"] == "nonfinite" and alert["step"] == 40 and alert["rank"] == 1
    assert alert["count"] == 41


def test_throughput_drop():
    rng = np.random.default_rng(2)
    s = _steps(5000)
    tps = 1000 + rng.normal(0, 10, len(s))
    tps[3000:3400] = 400
    (alert,) = check_series("sys/tokens_per_sec", 0, s, tps)
    assert alert["kind"] == "drop" and 2990 <= alert["step"] <= 3010
    assert 3390 <= alert["end_step"] <= 3400
    # ramp-up at the start of a run is not a drop
    tps[:100] = 50
    assert all(a["step"] > 100 for a in check_series("fps", 0, s, tps))
