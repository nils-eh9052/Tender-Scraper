"""Tests for src.health_monitor.anomalies

Spec-mandated test cases:
- FR: tender_count=13, newest_pub="2021-12-17" → pub_date_stale_60d fires (info)
- AU-ATM: tender_count=0, only 1 run → NO zero_tender_streak_3
- CA: tender_count=0 for 3 consecutive runs, 30d_mean=74 → zero_tender_streak_3 fires (warn)
"""
from __future__ import annotations

from datetime import date, timedelta

from src.health_monitor.anomalies import (
    rule_pub_date_stale_60d,
    rule_zero_tender_streak_3,
    rule_tender_count_drop_50pct,
    rule_http_error_spike,
    rule_rate_limit_cluster,
    rule_duration_spike,
    rule_unhandled_exception,
    rule_snapshot_drift,
    check_anomalies,
    DEFAULTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metric(adapter="fr", adapter_status="working", tender_count=13,
            newest_pub_date="2021-12-17", success=True, exception_count=0,
            exception_summary=None, http_4xx_count=0, http_5xx_count=0,
            http_429_count=0, run_duration_seconds=None, new_tender_count=0,
            removed_tender_count=0, run_id="20260519_140000"):
    return {
        "run_id": run_id,
        "adapter": adapter,
        "adapter_status": adapter_status,
        "tender_count": tender_count,
        "newest_pub_date": newest_pub_date,
        "success": success,
        "exception_count": exception_count,
        "exception_summary": exception_summary,
        "http_4xx_count": http_4xx_count,
        "http_5xx_count": http_5xx_count,
        "http_429_count": http_429_count,
        "run_duration_seconds": run_duration_seconds,
        "new_tender_count": new_tender_count,
        "removed_tender_count": removed_tender_count,
    }


def _baseline(tender_count_7d_mean=None, tender_count_30d_mean=None,
              http_error_7d_mean=None, duration_7d_mean=None,
              zero_streak=0):
    return {
        "tender_count_7d_mean":  tender_count_7d_mean,
        "tender_count_30d_mean": tender_count_30d_mean,
        "http_error_7d_mean":    http_error_7d_mean,
        "duration_7d_mean":      duration_7d_mean,
        "zero_streak":           zero_streak,
    }


_T = dict(DEFAULTS)  # Use default thresholds


# ---------------------------------------------------------------------------
# FR pub_date_stale_60d
# ---------------------------------------------------------------------------

class TestPubDateStale:
    def test_fr_2021_pub_date_fires(self):
        """FR: tender_count=13, newest_pub='2021-12-17' → pub_date_stale_60d (info)."""
        m = _metric(adapter="fr", adapter_status="working",
                    tender_count=13, newest_pub_date="2021-12-17")
        b = _baseline()
        result = rule_pub_date_stale_60d(m, b, _T)
        assert result is not None, "Expected pub_date_stale_60d to fire"
        assert result["rule"] == "pub_date_stale_60d"
        assert result["severity"] == "info"
        assert result["adapter"] == "fr"
        assert "2021-12-17" in result["value"]

    def test_recent_pub_date_no_fire(self):
        """Recent pub date (today-30d) should not fire."""
        recent = (date.today() - timedelta(days=30)).isoformat()
        m = _metric(adapter="fr", adapter_status="working",
                    tender_count=10, newest_pub_date=recent)
        b = _baseline()
        result = rule_pub_date_stale_60d(m, b, _T)
        assert result is None, f"Expected no anomaly, got {result}"

    def test_exactly_at_boundary_no_fire(self):
        """pub_date at exactly today-60d should not fire (boundary is exclusive: older than)."""
        boundary = (date.today() - timedelta(days=60)).isoformat()
        m = _metric(adapter="fr", adapter_status="working",
                    newest_pub_date=boundary)
        b = _baseline()
        result = rule_pub_date_stale_60d(m, b, _T)
        # boundary is NOT older than cutoff (it equals it), so should not fire
        assert result is None

    def test_working_no_data_does_not_fire(self):
        """working_no_data adapters should not trigger stale-date rule."""
        m = _metric(adapter="de", adapter_status="working_no_data",
                    newest_pub_date="2020-01-01")
        b = _baseline()
        result = rule_pub_date_stale_60d(m, b, _T)
        assert result is None

    def test_null_pub_date_no_fire(self):
        m = _metric(adapter="fr", adapter_status="working", newest_pub_date=None)
        b = _baseline()
        assert rule_pub_date_stale_60d(m, b, _T) is None


# ---------------------------------------------------------------------------
# AU-ATM — zero_tender_streak_3 should NOT fire with only 1 run
# ---------------------------------------------------------------------------

class TestZeroTenderStreak:
    def test_au_atm_single_run_no_fire(self):
        """AU-ATM: tender_count=0, only 1 run → NO zero_tender_streak_3."""
        m = _metric(adapter="au-atm", adapter_status="working",
                    tender_count=0, newest_pub_date=None)
        # With only 1 run, zero_streak=1 (< threshold of 3)
        b = _baseline(tender_count_30d_mean=10.0, zero_streak=1)
        result = rule_zero_tender_streak_3(m, b, _T)
        assert result is None, f"Expected no zero_streak anomaly for single-run, got {result}"

    def test_ca_three_consecutive_zeros_fires(self):
        """CA: tender_count=0 for 3 consecutive runs, 30d_mean=74 → zero_tender_streak_3 (warn)."""
        m = _metric(adapter="ca", adapter_status="working",
                    tender_count=0, newest_pub_date=None)
        b = _baseline(tender_count_30d_mean=74.0, zero_streak=3)
        result = rule_zero_tender_streak_3(m, b, _T)
        assert result is not None, "Expected zero_tender_streak_3 to fire for CA"
        assert result["rule"] == "zero_tender_streak_3"
        assert result["severity"] == "warn"
        assert result["adapter"] == "ca"

    def test_working_no_data_does_not_fire(self):
        """working_no_data adapters skip zero_streak rule (only 'working' adapters affected)."""
        m = _metric(adapter="de", adapter_status="working_no_data",
                    tender_count=0)
        b = _baseline(tender_count_30d_mean=20.0, zero_streak=10)
        result = rule_zero_tender_streak_3(m, b, _T)
        assert result is None

    def test_low_30d_mean_does_not_fire(self):
        """30d_mean below threshold (< 5) should not fire."""
        m = _metric(adapter="nl", adapter_status="working", tender_count=0)
        b = _baseline(tender_count_30d_mean=2.0, zero_streak=5)
        result = rule_zero_tender_streak_3(m, b, _T)
        assert result is None

    def test_streak_two_does_not_fire(self):
        """Streak of 2 is below the threshold of 3."""
        m = _metric(adapter="ca", adapter_status="working", tender_count=0)
        b = _baseline(tender_count_30d_mean=74.0, zero_streak=2)
        result = rule_zero_tender_streak_3(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# tender_count_drop_50pct
# ---------------------------------------------------------------------------

class TestTenderCountDrop:
    def test_50pct_drop_fires(self):
        m = _metric(adapter="fr", adapter_status="working", tender_count=5)
        b = _baseline(tender_count_7d_mean=15.0)
        result = rule_tender_count_drop_50pct(m, b, _T)
        assert result is not None
        assert result["severity"] == "warn"

    def test_no_drop_no_fire(self):
        m = _metric(adapter="fr", adapter_status="working", tender_count=13)
        b = _baseline(tender_count_7d_mean=13.0)
        result = rule_tender_count_drop_50pct(m, b, _T)
        assert result is None

    def test_below_min_baseline_no_fire(self):
        """baseline < 5 → rule should not fire."""
        m = _metric(adapter="nl", adapter_status="working", tender_count=0)
        b = _baseline(tender_count_7d_mean=3.0)
        result = rule_tender_count_drop_50pct(m, b, _T)
        assert result is None

    def test_null_baseline_no_fire(self):
        m = _metric(adapter="fr", adapter_status="working", tender_count=5)
        b = _baseline(tender_count_7d_mean=None)
        result = rule_tender_count_drop_50pct(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# HTTP error spike
# ---------------------------------------------------------------------------

class TestHttpErrorSpike:
    def test_high_error_count_fires(self):
        m = _metric(adapter="fr", http_4xx_count=10, http_5xx_count=5)
        b = _baseline(http_error_7d_mean=1.0)
        result = rule_http_error_spike(m, b, _T)
        assert result is not None
        assert result["severity"] == "warn"

    def test_within_threshold_no_fire(self):
        m = _metric(adapter="fr", http_4xx_count=2)
        b = _baseline(http_error_7d_mean=1.0)
        # 2 < max(3, 3*1.0=3) → exactly at threshold, should not fire
        result = rule_http_error_spike(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_429_fires(self):
        m = _metric(adapter="ted", http_429_count=2)
        b = _baseline()
        result = rule_rate_limit_cluster(m, b, _T)
        assert result is not None
        assert result["severity"] == "warn"

    def test_no_429_no_fire(self):
        m = _metric(adapter="ted", http_429_count=0)
        b = _baseline()
        result = rule_rate_limit_cluster(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# Duration spike
# ---------------------------------------------------------------------------

class TestDurationSpike:
    def test_duration_spike_fires(self):
        m = _metric(adapter="fr", run_duration_seconds=600.0)
        b = _baseline(duration_7d_mean=100.0)
        result = rule_duration_spike(m, b, _T)
        assert result is not None
        assert result["severity"] == "info"

    def test_no_spike_no_fire(self):
        m = _metric(adapter="fr", run_duration_seconds=150.0)
        b = _baseline(duration_7d_mean=100.0)
        result = rule_duration_spike(m, b, _T)
        assert result is None

    def test_null_baseline_no_fire(self):
        m = _metric(adapter="fr", run_duration_seconds=999.0)
        b = _baseline(duration_7d_mean=None)
        result = rule_duration_spike(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# Unhandled exception
# ---------------------------------------------------------------------------

class TestUnhandledException:
    def test_success_false_fires(self):
        m = _metric(adapter="cz", success=False, exception_count=2,
                    exception_summary="Traceback (most recent call last): ...")
        b = _baseline()
        result = rule_unhandled_exception(m, b, _T)
        assert result is not None
        assert result["severity"] == "critical"

    def test_exception_count_fires(self):
        m = _metric(adapter="cz", success=False, exception_count=1)
        b = _baseline()
        result = rule_unhandled_exception(m, b, _T)
        assert result is not None

    def test_clean_run_no_fire(self):
        m = _metric(adapter="cz", success=True, exception_count=0)
        b = _baseline()
        result = rule_unhandled_exception(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# Snapshot drift
# ---------------------------------------------------------------------------

class TestSnapshotDrift:
    def test_high_drift_fires(self):
        m = _metric(adapter="fr", tender_count=20, new_tender_count=15, removed_tender_count=0)
        b = _baseline()
        result = rule_snapshot_drift(m, b, _T)
        assert result is not None
        assert result["severity"] == "warn"

    def test_low_drift_no_fire(self):
        m = _metric(adapter="fr", tender_count=20, new_tender_count=2, removed_tender_count=1)
        b = _baseline()
        result = rule_snapshot_drift(m, b, _T)
        assert result is None

    def test_zero_tender_count_no_fire(self):
        m = _metric(adapter="fr", tender_count=0, new_tender_count=10)
        b = _baseline()
        result = rule_snapshot_drift(m, b, _T)
        assert result is None


# ---------------------------------------------------------------------------
# Integration: check_anomalies
# ---------------------------------------------------------------------------

class TestCheckAnomalies:
    def test_fr_stale_pub_date_fires_info(self):
        """Integration: FR with 2021-12-17 pub date triggers pub_date_stale_60d."""
        m = _metric(adapter="fr", adapter_status="working",
                    tender_count=13, newest_pub_date="2021-12-17")
        b = _baseline(tender_count_7d_mean=13.0)
        anomalies = check_anomalies(m, b, _T)
        rules_fired = {a["rule"] for a in anomalies}
        assert "pub_date_stale_60d" in rules_fired, f"Expected pub_date_stale_60d, got: {rules_fired}"
        stale = next(a for a in anomalies if a["rule"] == "pub_date_stale_60d")
        assert stale["severity"] == "info"

    def test_clean_run_no_anomalies(self):
        """A clean run with good metrics should produce no anomalies."""
        recent = (date.today() - timedelta(days=10)).isoformat()
        m = _metric(adapter="no", adapter_status="working",
                    tender_count=3, newest_pub_date=recent,
                    success=True, exception_count=0,
                    http_429_count=0, http_4xx_count=0, http_5xx_count=0)
        b = _baseline(tender_count_7d_mean=3.0, tender_count_30d_mean=3.0,
                      http_error_7d_mean=0.0, duration_7d_mean=None, zero_streak=0)
        anomalies = check_anomalies(m, b, _T)
        assert anomalies == [], f"Expected no anomalies, got: {anomalies}"
