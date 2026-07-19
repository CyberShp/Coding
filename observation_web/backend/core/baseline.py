"""
F202: Adaptive Baseline computation.

Runs periodically to compute a 30-day rolling baseline for numeric alert
metrics per (array_id, observer_name, metric_key).

Statistical approach (robust):
  The original implementation used median +/- 3*stddev. Standard deviation
  is not robust: a handful of extreme alert values inflate it, and for
  count-like / skewed metrics (error counts, flag counts) the normal-
  distribution assumption behind "3-sigma" simply does not hold, producing
  both false positives and false negatives.

  We therefore estimate spread with the Median Absolute Deviation (MAD),
  a robust scale estimator, and derive an anomaly threshold of
  median + k * (1.4826 * MAD). The 1.4826 factor rescales MAD so that, for
  normally distributed data, it matches the standard deviation - keeping the
  familiar "k-sigma" intuition while staying resistant to outliers and skew.
  When MAD collapses to zero (many identical samples, common for counts) we
  fall back to the classic standard deviation so a single differing value is
  not flagged as anomalous.

  To avoid over-repurposing the schema, the robust scale estimate is stored
  in the existing ``stddev_value`` column (no migration): it plays exactly
  the same role - the multiplier applied to build the threshold.

Cold-start protection:
  A baseline is only emitted once at least MIN_SAMPLES observations exist.
  With fewer samples the spread estimate is meaningless, so classification
  returns "insufficient_data" rather than a misleading normal/anomalous call.

Metric extraction rules per observer:
- error_code: total error count across ports
- cpu_usage: cpu_usage percentage
- memory_leak: current_rss_mb
- card_info: count of flagged fields
"""

import json
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from ..db import database as _db_module
from ..models.alert import AlertModel
from ..models.baseline import BaselineStats

logger = logging.getLogger("baseline")

WINDOW_DAYS = 30

# ── Robust-statistics constants (empirical; tune with care) ─────
# Minimum observations before a baseline is trusted. Below this the spread
# estimate is unstable, so we withhold any normal/anomalous judgement.
MIN_SAMPLES = 10
# Rescales MAD to be a consistent estimator of the standard deviation for
# normally distributed data (1 / Phi^-1(0.75) ~= 1.4826).
MAD_SCALE = 1.4826
# Threshold multiplier: anomaly if value > median + ANOMALY_K * robust_sigma.
# Kept at 3.0 to preserve the previous "3-sigma" operator intuition, but now
# applied to a robust (outlier-resistant) scale estimate.
ANOMALY_K = 3.0


# ── Robust spread estimators ───────────────────────────────────

def _median_abs_deviation(values: List[float], med: Optional[float] = None) -> float:
    """Median Absolute Deviation: median(|x_i - median(x)|)."""
    if not values:
        return 0.0
    m = statistics.median(values) if med is None else med
    return statistics.median([abs(v - m) for v in values])


def robust_sigma(values: List[float], med: Optional[float] = None) -> float:
    """
    Robust estimate of scale (comparable to stddev but outlier-resistant).

    Uses 1.4826 * MAD. Falls back to the classic sample standard deviation
    when MAD is zero (e.g. many identical samples), so a lone differing value
    is not treated as an anomaly against a zero-spread baseline.
    """
    if not values:
        return 0.0
    sigma = MAD_SCALE * _median_abs_deviation(values, med)
    if sigma == 0.0:
        sigma = statistics.stdev(values) if len(values) >= 2 else 0.0
    return sigma

# ── Metric extraction per observer ──────────────────────────────

def _extract_metrics(observer_name: str, details_str: str) -> Dict[str, float]:
    """Extract numeric metric(s) from alert details JSON. Returns {metric_key: value}."""
    try:
        d = json.loads(details_str) if isinstance(details_str, str) else (details_str or {})
    except (json.JSONDecodeError, TypeError):
        return {}

    metrics = {}

    if observer_name == "error_code":
        # Sum all port error counters
        port_counters = d.get("port_counters", {})
        total = 0
        for port, counters in port_counters.items():
            if isinstance(counters, dict):
                total += sum(v for v in counters.values() if isinstance(v, (int, float)))
        if total > 0:
            metrics["error_count"] = float(total)

    elif observer_name == "cpu_usage":
        val = d.get("cpu_usage") or d.get("current_percent")
        if isinstance(val, (int, float)):
            metrics["cpu_percent"] = float(val)

    elif observer_name == "memory_leak":
        val = d.get("current_rss_mb")
        if isinstance(val, (int, float)):
            metrics["rss_mb"] = float(val)
        growth = d.get("rss_growth_mb_per_hour")
        if isinstance(growth, (int, float)):
            metrics["rss_growth_per_hour"] = float(growth)

    elif observer_name == "card_info":
        # Count of flagged card fields
        alerts = d.get("alerts", [])
        if isinstance(alerts, list):
            metrics["card_flag_count"] = float(len(alerts))

    elif observer_name == "disk_smart":
        # Generic: extract any numeric value from the first item
        items = d.get("alerts", d.get("items", []))
        if isinstance(items, list) and len(items) > 0:
            item = items[0]
            if isinstance(item, dict):
                for key in ("reallocated_sectors", "current_pending", "offline_uncorrectable", "value"):
                    v = item.get(key)
                    if isinstance(v, (int, float)):
                        metrics[key] = float(v)

    return metrics


# ── Baseline computation ────────────────────────────────────────

async def compute_baselines():
    """Compute rolling baselines for all (array_id, observer_name) combinations."""
    logger.info("Starting baseline computation (window=%d days)", WINDOW_DAYS)
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)

    async with _db_module.AsyncSessionLocal() as db:
        # Get all distinct (array_id, observer_name) with recent alerts
        combos = await db.execute(
            select(AlertModel.array_id, AlertModel.observer_name)
            .where(AlertModel.timestamp >= cutoff)
            .distinct()
        )
        pairs = combos.all()
        logger.info("Found %d (array, observer) pairs to baseline", len(pairs))

        upsert_count = 0
        for array_id, observer_name in pairs:
            # Fetch all alerts for this pair in the window
            result = await db.execute(
                select(AlertModel.details)
                .where(
                    AlertModel.array_id == array_id,
                    AlertModel.observer_name == observer_name,
                    AlertModel.timestamp >= cutoff,
                )
                .order_by(AlertModel.timestamp)
            )
            rows = result.all()

            # Accumulate metric values
            metric_values: Dict[str, List[float]] = {}
            for (details_str,) in rows:
                metrics = _extract_metrics(observer_name, details_str)
                for key, val in metrics.items():
                    metric_values.setdefault(key, []).append(val)

            # Compute stats and upsert
            for metric_key, values in metric_values.items():
                if len(values) < MIN_SAMPLES:
                    continue  # Cold start: too few samples for a trustworthy baseline

                median_val = statistics.median(values)
                # Store the robust scale estimate in the stddev_value column
                # (no schema change): it serves the same role as stddev did -
                # the spread multiplier used to derive the anomaly threshold.
                stddev_val = robust_sigma(values, median_val)

                stmt = sqlite_upsert(BaselineStats).values(
                    array_id=array_id,
                    observer_name=observer_name,
                    metric_key=metric_key,
                    median_value=median_val,
                    stddev_value=stddev_val,
                    sample_count=len(values),
                    window_days=WINDOW_DAYS,
                    updated_at=datetime.now(),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["array_id", "observer_name", "metric_key"],
                    set_={
                        "median_value": stmt.excluded.median_value,
                        "stddev_value": stmt.excluded.stddev_value,
                        "sample_count": stmt.excluded.sample_count,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                await db.execute(stmt)
                upsert_count += 1

        await db.commit()
        logger.info("Baseline computation done: %d metrics updated", upsert_count)


async def get_baseline(db, array_id: str, observer_name: str) -> Dict[str, dict]:
    """Get baselines for a given array+observer. Returns {metric_key: {median, stddev, count}}."""
    result = await db.execute(
        select(BaselineStats)
        .where(
            BaselineStats.array_id == array_id,
            BaselineStats.observer_name == observer_name,
        )
    )
    rows = result.scalars().all()
    return {
        # stddev_value now holds the robust scale estimate (1.4826 * MAD, with
        # stddev fallback); the threshold is median + ANOMALY_K * robust_sigma.
        r.metric_key: {
            "median": r.median_value,
            "stddev": r.stddev_value,
            "count": r.sample_count,
            "threshold": r.median_value + ANOMALY_K * r.stddev_value,
        }
        for r in rows
    }


def check_baseline_status(metrics: Dict[str, float], baselines: Dict[str, dict]) -> str:
    """
    Compare alert metrics against baselines using the robust threshold
    (median + ANOMALY_K * robust_sigma).

    Returns:
      - 'anomalous'          if any metric exceeds its robust threshold
      - 'normal'             if all overlapping metrics are within threshold
      - 'insufficient_data'  if a matching baseline exists but is still in
                             cold start (fewer than MIN_SAMPLES observations)
      - 'no_baseline'        if no baseline data / no overlapping metrics
    """
    if not baselines:
        return "no_baseline"

    if not metrics or not (metrics.keys() & baselines.keys()):
        return "no_baseline"

    saw_usable_baseline = False
    for key, val in metrics.items():
        bl = baselines.get(key)
        if not bl:
            continue
        # Cold-start guard: withhold judgement on under-sampled baselines.
        if bl.get("count", 0) < MIN_SAMPLES:
            continue
        saw_usable_baseline = True
        if val > bl["threshold"]:
            return "anomalous"

    if not saw_usable_baseline:
        return "insufficient_data"

    return "normal"
