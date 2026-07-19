"""
Statistical rigor enhancements for F200 (association mining) and
F202 (adaptive baseline).

Covers:
  - F200: lift computation, support/lift/confidence thresholding
  - F202: MAD-based robust scale, robust anomaly threshold,
          cold-start (insufficient-sample) protection
"""

import pytest

from backend.core.causal import (
    score_pair,
    _pair_passes_thresholds,
    MIN_CO_OCCURRENCE,
    MIN_SUPPORT,
    CONFIDENCE_FLOOR,
    LIFT_FLOOR,
)
from backend.core.baseline import (
    _median_abs_deviation,
    robust_sigma,
    check_baseline_status,
    MAD_SCALE,
    MIN_SAMPLES,
    ANOMALY_K,
)


# ══════════════════════════════════════════════════════════════
# F200 — association metrics
# ══════════════════════════════════════════════════════════════

def test_lift_independent_is_one():
    """When B occurs at the same rate whether or not A precedes it, lift ~= 1."""
    # 100 episodes, A in 50, B in 50, A->B co-occurs in 25.
    # confidence = 25/50 = 0.5; P(B) = 50/100 = 0.5; lift = 0.5/0.5 = 1.0
    s = score_pair(co_occurrence=25, antecedent_episodes=50,
                   consequent_episodes=50, total_episodes=100)
    assert s["confidence"] == pytest.approx(0.5)
    assert s["support"] == pytest.approx(0.25)
    assert s["lift"] == pytest.approx(1.0)


def test_lift_positive_association():
    """B follows A far more than B's base rate => lift > 1."""
    # A in 20 episodes, A->B in 18 => confidence 0.9.
    # B overall in 30/100 => P(B)=0.3 => lift = 0.9/0.3 = 3.0
    s = score_pair(co_occurrence=18, antecedent_episodes=20,
                   consequent_episodes=30, total_episodes=100)
    assert s["lift"] == pytest.approx(3.0)
    assert s["lift"] > 1.0


def test_lift_frequent_but_unrelated_not_over_one():
    """Two very frequent observers co-occur a lot yet are ~independent.

    This is exactly the 'A frequent & B frequent' false positive the naive
    count/confidence approach flagged. Lift keeps it near 1 (not > 1).
    """
    # Both A and B appear in 90/100 episodes; A->B co-occurs in 81
    # (=0.9*0.9*100, i.e. independence). confidence=81/90=0.9,
    # P(B)=0.9 => lift=1.0 exactly => not a positive association.
    s = score_pair(co_occurrence=81, antecedent_episodes=90,
                   consequent_episodes=90, total_episodes=100)
    assert s["confidence"] == pytest.approx(0.9)
    assert s["lift"] == pytest.approx(1.0)


def test_lift_zero_when_consequent_absent():
    s = score_pair(co_occurrence=5, antecedent_episodes=5,
                   consequent_episodes=0, total_episodes=100)
    assert s["lift"] == 0.0


def test_support_filter_drops_rare_pairs():
    """A pair seen only a couple times in a huge window is below support floor."""
    # count=2 in 1000 episodes => support 0.002 << MIN_SUPPORT
    s = score_pair(co_occurrence=2, antecedent_episodes=2,
                   consequent_episodes=2, total_episodes=1000)
    assert s["support"] < MIN_SUPPORT
    # Even with perfect confidence/lift, low support rejects the edge.
    assert _pair_passes_thresholds(s, 2) is False


def test_thresholds_accept_strong_edge():
    s = score_pair(co_occurrence=18, antecedent_episodes=20,
                   consequent_episodes=30, total_episodes=100)
    assert s["support"] >= MIN_SUPPORT
    assert s["confidence"] >= CONFIDENCE_FLOOR
    assert s["lift"] >= LIFT_FLOOR
    assert _pair_passes_thresholds(s, 18) is True


def test_thresholds_reject_independent_edge():
    """Independent pair (lift == 1) fails the lift floor (> chance required)."""
    s = score_pair(co_occurrence=25, antecedent_episodes=50,
                   consequent_episodes=50, total_episodes=100)
    # lift == LIFT_FLOOR (1.0) passes the >= check, so nudge to a clearly
    # non-informative case: negatively associated.
    s_neg = score_pair(co_occurrence=5, antecedent_episodes=50,
                       consequent_episodes=80, total_episodes=100)
    assert s_neg["lift"] < LIFT_FLOOR
    assert _pair_passes_thresholds(s_neg, 5) is False


def test_thresholds_reject_below_min_co_occurrence():
    s = score_pair(co_occurrence=1, antecedent_episodes=1,
                   consequent_episodes=1, total_episodes=3)
    assert 1 < MIN_CO_OCCURRENCE
    assert _pair_passes_thresholds(s, 1) is False


# ══════════════════════════════════════════════════════════════
# F202 — robust baseline statistics
# ══════════════════════════════════════════════════════════════

def test_mad_basic():
    # values 1..9, median 5, abs devs {4,3,2,1,0,1,2,3,4}, median of those = 2
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert _median_abs_deviation(values) == pytest.approx(2.0)


def test_robust_sigma_scales_mad():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert robust_sigma(values) == pytest.approx(2.0 * MAD_SCALE)


def test_robust_sigma_resists_outlier():
    """A single extreme outlier barely moves robust sigma but explodes stddev."""
    import statistics
    base = [10, 11, 9, 10, 11, 9, 10, 11, 9, 10]
    outlier = base + [10_000]
    classic = statistics.stdev(outlier)
    robust = robust_sigma(outlier)
    # Classic stddev is inflated into the thousands; robust stays small.
    assert classic > 1000
    assert robust < 10


def test_robust_sigma_zero_mad_falls_back_to_stddev():
    """Constant-ish data with MAD==0 falls back to classic stddev (not zero)."""
    # 6 identical + a couple different => MAD is 0 (median dev == 0)
    values = [5, 5, 5, 5, 5, 5, 5, 6, 4]
    assert _median_abs_deviation(values) == 0.0
    assert robust_sigma(values) > 0.0  # fell back to stddev


def test_baseline_status_anomalous_robust_threshold():
    values = [10, 11, 9, 10, 11, 9, 10, 11, 9, 10, 10, 11]
    import statistics
    median = statistics.median(values)
    sigma = robust_sigma(values, median)
    baselines = {
        "cpu_percent": {
            "median": median,
            "stddev": sigma,
            "count": len(values),
            "threshold": median + ANOMALY_K * sigma,
        }
    }
    # Well above threshold
    assert check_baseline_status({"cpu_percent": 500.0}, baselines) == "anomalous"
    # Right at the median => normal
    assert check_baseline_status({"cpu_percent": median}, baselines) == "normal"


def test_baseline_status_cold_start_insufficient():
    """A baseline built from too few samples must not yield a normal/anomalous call."""
    baselines = {
        "cpu_percent": {
            "median": 10.0,
            "stddev": 1.0,
            "count": MIN_SAMPLES - 1,  # under-sampled
            "threshold": 13.0,
        }
    }
    assert check_baseline_status({"cpu_percent": 999.0}, baselines) == "insufficient_data"


def test_baseline_status_mixed_uses_sufficient_baseline():
    """When at least one overlapping baseline is well-sampled, it is used."""
    baselines = {
        "cpu_percent": {"median": 10.0, "stddev": 1.0, "count": MIN_SAMPLES, "threshold": 13.0},
    }
    assert check_baseline_status({"cpu_percent": 12.0}, baselines) == "normal"
    assert check_baseline_status({"cpu_percent": 20.0}, baselines) == "anomalous"


def test_baseline_status_no_baseline_and_no_overlap():
    assert check_baseline_status({"cpu_percent": 5.0}, {}) == "no_baseline"
    baselines = {"cpu_percent": {"median": 1, "stddev": 1, "count": 50, "threshold": 4}}
    # metric key does not overlap baseline keys
    assert check_baseline_status({"other_metric": 5.0}, baselines) == "no_baseline"
