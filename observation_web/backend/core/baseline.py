"""
F202: Adaptive Baseline computation.

Runs periodically to compute 30-day rolling median and stddev
for numeric alert metrics per (array_id, observer_name, metric_key).

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
from typing import Dict, List, Tuple

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from ..db import database as _db_module
from ..models.alert import AlertModel
from ..models.baseline import BaselineStats

logger = logging.getLogger("baseline")

WINDOW_DAYS = 30

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
                if len(values) < 3:
                    continue  # Not enough data for meaningful baseline

                median_val = statistics.median(values)
                stddev_val = statistics.stdev(values) if len(values) >= 2 else 0.0

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
        r.metric_key: {
            "median": r.median_value,
            "stddev": r.stddev_value,
            "count": r.sample_count,
            "threshold": r.median_value + 3 * r.stddev_value,
        }
        for r in rows
    }


def check_baseline_status(metrics: Dict[str, float], baselines: Dict[str, dict]) -> str:
    """
    Compare alert metrics against baselines.
    Returns 'anomalous' if any metric exceeds baseline + 3σ, else 'normal'.
    If no baseline data exists, returns 'no_baseline'.
    """
    if not baselines:
        return "no_baseline"

    for key, val in metrics.items():
        bl = baselines.get(key)
        if not bl:
            continue
        threshold = bl["threshold"]
        if val > threshold:
            return "anomalous"

    return "normal"
