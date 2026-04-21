"""
F200: Causal Inference Engine.

Mines temporal co-occurrence patterns from alert history to build a
per-array causal DAG.  At query time, overlays the learned DAG onto
a set of concurrent alerts to identify root causes vs consequences.

Algorithm:
  1. For each array, scan alert windows (30-day rolling).
  2. Find "episodes" — bursts of alerts within EPISODE_GAP seconds.
  3. Within each episode, record all ordered observer pairs (A before B).
  4. Accumulate counts and average lags → upsert into causal_rules.
  5. Compute confidence = P(B follows A within episode) / P(A in any episode).

Runtime DAG construction:
  Given a set of alerts in a time window, look up learned edges,
  build a DAG, find root nodes (in-degree 0), and return tree structure.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import database as _db_module
from ..models.alert import AlertModel
from ..models.causal import CausalRuleModel

logger = logging.getLogger("causal")

# ── Config ─────────────────────────────────────────────────────
WINDOW_DAYS = 30          # Mining lookback window
EPISODE_GAP_SEC = 60      # Max gap between alerts in one episode
MIN_CO_OCCURRENCE = 2     # Minimum times A→B must be seen to keep the edge
CONFIDENCE_FLOOR = 0.15   # Drop edges below this confidence


# ── Episode detection ──────────────────────────────────────────

def _split_episodes(
    alerts: List[Tuple[datetime, str]],
    gap_sec: float = EPISODE_GAP_SEC,
) -> List[List[Tuple[datetime, str]]]:
    """
    Split a time-sorted list of (timestamp, observer_name) into episodes.
    An episode boundary is a gap > gap_sec between consecutive alerts.
    """
    if not alerts:
        return []
    episodes: List[List[Tuple[datetime, str]]] = [[alerts[0]]]
    for i in range(1, len(alerts)):
        if (alerts[i][0] - alerts[i - 1][0]).total_seconds() > gap_sec:
            episodes.append([])
        episodes[-1].append(alerts[i])
    return episodes


def _mine_pairs(
    episodes: List[List[Tuple[datetime, str]]],
) -> Dict[Tuple[str, str], List[float]]:
    """
    For each episode, extract all ordered observer pairs (A→B where A fires
    before B) and record the time lag.  Returns {(A,B): [lag1, lag2, ...]}.
    """
    pair_lags: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for ep in episodes:
        # Deduplicate observers per episode (keep earliest occurrence)
        seen: Dict[str, datetime] = {}
        for ts, obs in ep:
            if obs not in seen:
                seen[obs] = ts
        observers = sorted(seen.items(), key=lambda x: x[1])
        # All ordered pairs
        for i, (obs_a, ts_a) in enumerate(observers):
            for obs_b, ts_b in observers[i + 1:]:
                if obs_a != obs_b:
                    lag = (ts_b - ts_a).total_seconds()
                    pair_lags[(obs_a, obs_b)].append(lag)
    return pair_lags


# ── Mining job (periodic) ──────────────────────────────────────

async def mine_causal_rules():
    """
    Periodic job: scan alert history and upsert causal rules.
    Runs after compute_baselines in the scheduler.
    """
    logger.info("Starting causal rule mining (window=%d days)", WINDOW_DAYS)
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)

    async with _db_module.AsyncSessionLocal() as db:
        # Get all distinct array_ids with recent alerts
        arr_result = await db.execute(
            select(AlertModel.array_id)
            .where(AlertModel.timestamp >= cutoff)
            .distinct()
        )
        array_ids = [row[0] for row in arr_result.all()]
        logger.info("Mining causal rules for %d arrays", len(array_ids))

        total_upserts = 0
        for array_id in array_ids:
            # Fetch alerts for this array, ordered by time
            result = await db.execute(
                select(AlertModel.timestamp, AlertModel.observer_name)
                .where(
                    AlertModel.array_id == array_id,
                    AlertModel.timestamp >= cutoff,
                )
                .order_by(AlertModel.timestamp)
            )
            rows = [(row[0], row[1]) for row in result.all()]
            if len(rows) < 2:
                continue

            # Count per-observer episodes for confidence denominator
            episodes = _split_episodes(rows)
            observer_episode_count: Dict[str, int] = defaultdict(int)
            for ep in episodes:
                obs_in_ep = {obs for _, obs in ep}
                for obs in obs_in_ep:
                    observer_episode_count[obs] += 1

            # Mine pairs
            pair_lags = _mine_pairs(episodes)

            # Upsert rules
            for (ant, con), lags in pair_lags.items():
                count = len(lags)
                if count < MIN_CO_OCCURRENCE:
                    continue
                avg_lag = sum(lags) / count
                # Confidence: fraction of antecedent episodes where consequent followed
                ant_total = observer_episode_count.get(ant, count)
                confidence = count / ant_total if ant_total > 0 else 0.0
                if confidence < CONFIDENCE_FLOOR:
                    continue

                stmt = sqlite_upsert(CausalRuleModel).values(
                    array_id=array_id,
                    antecedent=ant,
                    consequent=con,
                    co_occurrence_count=count,
                    avg_lag_seconds=round(avg_lag, 2),
                    confidence=round(confidence, 3),
                    last_seen_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["array_id", "antecedent", "consequent"],
                    set_={
                        "co_occurrence_count": stmt.excluded.co_occurrence_count,
                        "avg_lag_seconds": stmt.excluded.avg_lag_seconds,
                        "confidence": stmt.excluded.confidence,
                        "last_seen_at": stmt.excluded.last_seen_at,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                await db.execute(stmt)
                total_upserts += 1

        await db.commit()
        logger.info("Causal mining done: %d edges upserted across %d arrays",
                     total_upserts, len(array_ids))


# ── Runtime DAG construction ──────────────────────────────────

async def get_causal_rules(
    db: AsyncSession, array_id: str,
) -> List[CausalRuleModel]:
    """Fetch all learned causal edges for an array."""
    result = await db.execute(
        select(CausalRuleModel)
        .where(CausalRuleModel.array_id == array_id)
        .order_by(CausalRuleModel.confidence.desc())
    )
    return result.scalars().all()


def build_causal_dag(
    alerts: List[dict],
    rules: List[CausalRuleModel],
) -> List[dict]:
    """
    Given a set of concurrent alerts and learned causal rules,
    build a DAG and return a tree-structured result.

    Each alert gets a 'causal_role' annotation:
      - 'root': no known antecedent in this alert set
      - 'consequence': has a known antecedent in this alert set
      - 'isolated': no causal edges match

    Returns list of root nodes, each with nested 'consequences'.
    """
    if not alerts:
        return []

    # Build lookup: observer_name → list of alerts
    obs_alerts: Dict[str, List[dict]] = defaultdict(list)
    for a in alerts:
        obs_alerts[a.get("observer_name", "")].append(a)

    # Active observers in this alert set
    active_obs: Set[str] = set(obs_alerts.keys())

    # Build edge map from rules (only edges where both ends are active)
    edges: Dict[str, Set[str]] = defaultdict(set)   # antecedent → {consequents}
    has_antecedent: Set[str] = set()
    rule_map: Dict[Tuple[str, str], CausalRuleModel] = {}

    for r in rules:
        if r.antecedent in active_obs and r.consequent in active_obs:
            edges[r.antecedent].add(r.consequent)
            has_antecedent.add(r.consequent)
            rule_map[(r.antecedent, r.consequent)] = r

    # Root observers: in active set but not a consequent of anything
    root_obs = active_obs - has_antecedent

    # If no edges matched, everything is isolated
    if not edges:
        result = []
        for a in alerts:
            node = dict(a)
            node["causal_role"] = "isolated"
            node["consequences"] = []
            result.append(node)
        return result

    # Build tree from roots
    used_obs: Set[str] = set()

    def _build_subtree(obs: str) -> List[dict]:
        """Build consequence subtree for an observer."""
        if obs in used_obs:
            return []
        used_obs.add(obs)
        subtrees = []
        for child_obs in sorted(edges.get(obs, set())):
            rule = rule_map.get((obs, child_obs))
            child_alerts = obs_alerts.get(child_obs, [])
            for ca in child_alerts:
                node = dict(ca)
                node["causal_role"] = "consequence"
                node["causal_edge"] = {
                    "from": obs,
                    "confidence": rule.confidence if rule else 0,
                    "avg_lag": rule.avg_lag_seconds if rule else 0,
                    "co_occurrence": rule.co_occurrence_count if rule else 0,
                }
                node["consequences"] = _build_subtree(child_obs)
                subtrees.append(node)
        return subtrees

    result = []
    # Add root nodes
    for obs in sorted(root_obs):
        for ra in obs_alerts.get(obs, []):
            node = dict(ra)
            node["causal_role"] = "root"
            node["consequences"] = _build_subtree(obs)
            result.append(node)

    # Any observer not covered (cycle or isolated)
    for obs in active_obs - used_obs:
        for a in obs_alerts.get(obs, []):
            node = dict(a)
            node["causal_role"] = "isolated"
            node["consequences"] = []
            result.append(node)

    return result
