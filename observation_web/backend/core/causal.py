"""
F200: Temporal Association / Co-occurrence Engine.

Mines temporal co-occurrence patterns from alert history to build a
per-array association graph.  At query time, overlays the learned graph onto
a set of concurrent alerts to order likely antecedents vs. followers.

IMPORTANT — these are associations, not proven causes.
  The rules describe *statistical co-occurrence with temporal precedence*
  ("A tends to fire shortly before B"), which is suggestive of a causal link
  but does not establish one. High counts alone are misleading: two observers
  that both fire frequently will co-occur often even when unrelated. We
  therefore rank edges by association strength, not raw frequency, and the
  learned graph should be read as a ranked hypothesis for triage, not proof.

Algorithm:
  1. For each array, scan alert windows (30-day rolling).
  2. Find "episodes" — bursts of alerts within EPISODE_GAP seconds.
  3. Within each episode, record all ordered observer pairs (A before B).
  4. Accumulate counts and average lags.
  5. Score each pair with three association metrics and keep only pairs that
     clear every threshold:
       - support    = co-occurrences / total episodes  (filters rare pairs)
       - confidence = P(B follows A | A)                (directional strength)
       - lift       = P(B|A) / P(B)                     (association vs. chance;
                      lift ~= 1 means independent, > 1 positively associated)
  6. Upsert survivors into the ``causal_rules`` table (name kept for schema /
     API / frontend compatibility; the contents are association metrics).

Runtime graph construction:
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
# NOTE: the thresholds below are empirical heuristics, not theoretically
# derived. They trade recall for precision to suppress spurious edges; tune
# against real alert history rather than treating them as ground truth.
WINDOW_DAYS = 30          # Mining lookback window
EPISODE_GAP_SEC = 60      # Max gap between alerts in one episode
MIN_CO_OCCURRENCE = 2     # Minimum times A→B must be seen to keep the edge
CONFIDENCE_FLOOR = 0.15   # Drop edges below this directional confidence
MIN_SUPPORT = 0.05        # Drop pairs seen in < 5% of episodes (rare/incidental)
LIFT_FLOOR = 1.0          # Keep only positively-associated pairs (lift > chance).
                          # lift == 1 => A and B independent; < 1 => negatively
                          # associated; both are dropped as non-informative.


def score_pair(
    co_occurrence: int,
    antecedent_episodes: int,
    consequent_episodes: int,
    total_episodes: int,
) -> Dict[str, float]:
    """
    Compute association metrics for an ordered pair A->B.

    Args:
        co_occurrence:       episodes where A fired before B
        antecedent_episodes: episodes containing A
        consequent_episodes: episodes containing B
        total_episodes:      total episodes in the mining window

    Returns dict with:
        confidence = P(B follows A | A) = co_occurrence / antecedent_episodes
        support    = co_occurrence / total_episodes
        lift       = confidence / P(B), where P(B) = consequent_episodes / total
                     lift ~= 1 -> independent, > 1 -> positive association
    """
    confidence = co_occurrence / antecedent_episodes if antecedent_episodes else 0.0
    support = co_occurrence / total_episodes if total_episodes else 0.0
    p_consequent = consequent_episodes / total_episodes if total_episodes else 0.0
    lift = (confidence / p_consequent) if p_consequent > 0 else 0.0
    return {"confidence": confidence, "support": support, "lift": lift}


def _pair_passes_thresholds(scores: Dict[str, float], co_occurrence: int) -> bool:
    """Apply all association thresholds; True means keep the edge."""
    return (
        co_occurrence >= MIN_CO_OCCURRENCE
        and scores["support"] >= MIN_SUPPORT
        and scores["confidence"] >= CONFIDENCE_FLOOR
        and scores["lift"] >= LIFT_FLOOR
    )


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
    Periodic job: scan alert history and upsert association (co-occurrence)
    rules. Runs after compute_baselines in the scheduler.

    Function/table names retain the "causal" label for schema, API and
    frontend compatibility; the mined relationships are temporal associations,
    not proven causal links.
    """
    logger.info("Starting association rule mining (co-occurrence, window=%d days)",
                WINDOW_DAYS)
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)

    async with _db_module.AsyncSessionLocal() as db:
        # Get all distinct array_ids with recent alerts
        arr_result = await db.execute(
            select(AlertModel.array_id)
            .where(AlertModel.timestamp >= cutoff)
            .distinct()
        )
        array_ids = [row[0] for row in arr_result.all()]
        logger.info("Mining association rules for %d arrays", len(array_ids))

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

            # Count per-observer episodes (denominator for confidence / lift)
            episodes = _split_episodes(rows)
            total_episodes = len(episodes)
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
                avg_lag = sum(lags) / count if count else 0.0
                ant_total = observer_episode_count.get(ant, count)
                con_total = observer_episode_count.get(con, 0)
                scores = score_pair(count, ant_total, con_total, total_episodes)
                # Log association strength even for dropped edges (lift has no
                # dedicated column, so this is where it is surfaced).
                logger.debug(
                    "assoc %s->%s: count=%d support=%.3f confidence=%.3f lift=%.3f",
                    ant, con, count, scores["support"],
                    scores["confidence"], scores["lift"],
                )
                if not _pair_passes_thresholds(scores, count):
                    continue
                confidence = scores["confidence"]

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
        logger.info("Association mining done: %d edges upserted across %d arrays",
                     total_upserts, len(array_ids))


# ── Runtime DAG construction ──────────────────────────────────

async def get_causal_rules(
    db: AsyncSession, array_id: str,
) -> List[CausalRuleModel]:
    """Fetch all learned association (co-occurrence) edges for an array."""
    result = await db.execute(
        select(CausalRuleModel)
        .where(CausalRuleModel.array_id == array_id)
        .order_by(CausalRuleModel.confidence.desc())
    )
    return result.scalars().all()


def _parse_alert_ts(alert: dict) -> Optional[datetime]:
    """Parse timestamp from alert dict."""
    ts = alert.get("timestamp", "")
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", ""))
        except (ValueError, TypeError):
            return None
    return None


def _build_episode_dag(
    episode_alerts: List[dict],
    rules: List,
) -> List[dict]:
    """
    Build an association DAG for a single episode (a set of temporally
    co-occurring alerts), ordering antecedents before followers using the
    learned co-occurrence edges. Returns annotated tree nodes.

    Note: the ``causal_role`` / ``causal_edge`` keys are retained for frontend
    compatibility; roles reflect observed temporal precedence within the
    episode, not proven causation.
    """
    # Build lookup: observer_name → list of alerts in this episode
    obs_alerts: Dict[str, List[dict]] = defaultdict(list)
    for a in episode_alerts:
        obs_alerts[a.get("observer_name", "")].append(a)

    active_obs: Set[str] = set(obs_alerts.keys())

    # Compute earliest timestamp per observer in this episode
    obs_earliest: Dict[str, datetime] = {}
    for obs, alerts_list in obs_alerts.items():
        earliest = None
        for a in alerts_list:
            ts = _parse_alert_ts(a)
            if ts and (earliest is None or ts < earliest):
                earliest = ts
        if earliest:
            obs_earliest[obs] = earliest

    # Build edge map from rules — only accept edge if the antecedent's
    # earliest occurrence in THIS episode is before the consequent's earliest
    edges: Dict[str, Set[str]] = defaultdict(set)
    has_antecedent: Set[str] = set()
    rule_map: Dict[Tuple[str, str], object] = {}

    for r in rules:
        if r.antecedent in active_obs and r.consequent in active_obs:
            ant_ts = obs_earliest.get(r.antecedent)
            con_ts = obs_earliest.get(r.consequent)
            if ant_ts and con_ts and ant_ts < con_ts:
                edges[r.antecedent].add(r.consequent)
                has_antecedent.add(r.consequent)
                rule_map[(r.antecedent, r.consequent)] = r

    root_obs = active_obs - has_antecedent

    # No edges → everything isolated
    if not edges:
        result = []
        for a in episode_alerts:
            node = dict(a)
            node["causal_role"] = "isolated"
            node["consequences"] = []
            result.append(node)
        return result

    # Build tree from roots
    used_obs: Set[str] = set()

    def _build_subtree(obs: str) -> List[dict]:
        if obs in used_obs:
            return []
        used_obs.add(obs)
        subtrees = []
        for child_obs in sorted(edges.get(obs, set())):
            rule = rule_map.get((obs, child_obs))
            for ca in obs_alerts.get(child_obs, []):
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
    for obs in sorted(root_obs):
        for ra in obs_alerts.get(obs, []):
            node = dict(ra)
            node["causal_role"] = "root"
            node["consequences"] = _build_subtree(obs)
            result.append(node)

    # Uncovered observers (cycle or isolated)
    for obs in active_obs - used_obs:
        for a in obs_alerts.get(obs, []):
            node = dict(a)
            node["causal_role"] = "isolated"
            node["consequences"] = []
            result.append(node)

    return result


def build_causal_dag(
    alerts: List[dict],
    rules: List,
) -> List[dict]:
    """
    Split alerts into temporal episodes, then build an association DAG
    per episode using learned co-occurrence rules.

    Each alert gets a 'causal_role' annotation (key name kept for frontend
    compatibility; it denotes observed precedence, not proven causation):
      - 'root': no known antecedent (predecessor) in this episode
      - 'consequence': follows a known antecedent in this episode
      - 'isolated': no association edges match

    Returns flat list of annotated tree nodes (roots with nested consequences).
    """
    if not alerts:
        return []

    # Sort alerts by timestamp for episode detection
    timed = []
    for a in alerts:
        ts = _parse_alert_ts(a)
        if ts:
            timed.append((ts, a))
    timed.sort(key=lambda x: x[0])

    if not timed:
        return [dict(a, causal_role="isolated", consequences=[]) for a in alerts]

    # Split into episodes using the same gap threshold as mining
    episodes = _split_episodes(timed, gap_sec=EPISODE_GAP_SEC)

    # Build a DAG per episode, collect all results
    result = []
    for ep in episodes:
        ep_alerts = [a for _, a in ep]
        ep_trees = _build_episode_dag(ep_alerts, rules)
        result.extend(ep_trees)

    return result
