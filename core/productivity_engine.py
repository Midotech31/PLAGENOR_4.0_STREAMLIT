# core/productivity_engine.py
# ── PLAGENOR 4.0 — Productivity Engine ───────────────────────────────────────
# Computes and maintains productivity scores for members (analystes).
#
# Scoring model:
#   A weighted composite score (0–100) derived from:
#     1. Completion rate       — % of assigned requests completed
#     2. On-time rate          — % completed within SLA deadline
#     3. Report quality score  — average quality rating on reports (if rated)
#     4. Throughput            — completed requests per active day
#     5. Load efficiency       — how well member utilises available capacity
#     6. Rejection penalty     — deduction for requests rejected after assignment
#
# Score labels:
#   EXCELLENT (≥ 80) | GOOD (≥ 60) | NORMAL (≥ 40) | LOW (< 40)
#
# History:
#   Each recalculation appends an entry to member.productivity_history[]
#   keeping the last 90 days of snapshots.
#
# Triggers:
#   - Called by workflow_engine on COMPLETED transition
#   - Called by super_admin "Recalculate all" action
#   - Called on-demand via recalculate_member(member_id)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from typing import Optional, Any

import config
from core.exceptions import ProductivityError
from core.repository import (
    get_member,
    get_all_members,
    save_member,
    get_all_active_requests,
    get_all_archived_requests,
    get_all_audit_logs,
)


# ── Constants ─────────────────────────────────────────────────────────────────
CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB

# ── Score thresholds ──────────────────────────────────────────────────────────
SCORE_EXCELLENT  = 80.0
SCORE_GOOD       = 60.0
SCORE_NORMAL     = 40.0
# Below NORMAL → LOW

# ── Default SLA deadlines (calendar days per channel) ─────────────────────────
SLA_DAYS = {
    CHANNEL_IBTIKAR:  int(getattr(config, "SLA_DAYS_IBTIKAR",  21)),
    CHANNEL_GENOCLAB: int(getattr(config, "SLA_DAYS_GENOCLAB", 14)),
    "default":        21,
}

# ── History retention ─────────────────────────────────────────────────────────
MAX_HISTORY_ENTRIES = 90

# ── Weight configuration ──────────────────────────────────────────────────────
# Weights must sum to 1.0
WEIGHTS = {
    "completion_rate":  0.30,   # % completed / total assigned
    "on_time_rate":     0.25,   # % completed within SLA
    "quality_score":    0.20,   # average report quality (0–100)
    "throughput":       0.15,   # completed per active day (normalised)
    "load_efficiency":  0.05,   # current_load / max_load efficiency
    "rejection_penalty":0.05,   # penalty for post-assignment rejections
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# ── Throughput normalisation cap (requests/day → score) ───────────────────────
# A member completing >= THROUGHPUT_CAP requests/day gets full throughput score
THROUGHPUT_CAP = float(getattr(config, "PRODUCTIVITY_THROUGHPUT_CAP", 0.5))


# ── Utility helpers ───────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_dt(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).replace(tzinfo=None)
    except Exception:
        return None


def _days_between(start_iso: str, end_iso: str) -> Optional[float]:
    """Returns float days between two ISO timestamps, or None on error."""
    dt_start = _parse_dt(start_iso)
    dt_end   = _parse_dt(end_iso)
    if dt_start and dt_end:
        return max((dt_end - dt_start).total_seconds() / 86_400, 0.0)
    return None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _score_to_label(score: float) -> str:
    if score >= SCORE_EXCELLENT:
        return "EXCELLENT"
    elif score >= SCORE_GOOD:
        return "GOOD"
    elif score >= SCORE_NORMAL:
        return "NORMAL"
    else:
        return "LOW"


def _trend(history: list[dict]) -> str:
    """
    Returns a trend string based on the last 3 history entries.
    "↑ En hausse" | "↓ En baisse" | "→ Stable"
    """
    if len(history) < 2:
        return "→ Stable"
    recent = history[-3:]
    scores = [float(h.get("score", 50)) for h in recent]
    if len(scores) < 2:
        return "→ Stable"
    delta = scores[-1] - scores[0]
    if delta > 3:
        return "↑ En hausse"
    elif delta < -3:
        return "↓ En baisse"
    else:
        return "→ Stable"


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST DATA COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

def _get_all_requests_for_member(member_id: str) -> list[dict]:
    """
    Returns all requests (active + archived) assigned to member_id.
    """
    active   = get_all_active_requests()
    archived = get_all_archived_requests()
    return [
        r for r in active + archived
        if r.get("assigned_member_id") == member_id
    ]


def _get_completed_requests(requests: list[dict]) -> list[dict]:
    return [
        r for r in requests
        if r.get("status") in {"COMPLETED", "ARCHIVED"}
        and r.get("assigned_member_id")
    ]


def _get_rejected_after_assignment(requests: list[dict]) -> list[dict]:
    """
    Returns requests that were ASSIGNED to the member but later REJECTED.
    Detected via status_history: after an ASSIGNED entry, a REJECTED entry exists.
    """
    result = []
    for req in requests:
        history = req.get("status_history", [])
        states  = [h.get("to_state", h.get("state", "")) for h in history]
        if "ASSIGNED" in states and req.get("status") in {
            "REJECTED", "QUOTE_REJECTED_BY_CLIENT", "ARCHIVED"
        }:
            # Only count if rejection came after assignment
            try:
                assign_idx = max(
                    i for i, s in enumerate(states) if s == "ASSIGNED"
                )
                reject_idx = max(
                    i for i, s in enumerate(states)
                    if s in {"REJECTED", "QUOTE_REJECTED_BY_CLIENT"}
                )
                if reject_idx > assign_idx:
                    result.append(req)
            except (ValueError, TypeError):
                pass
    return result


def _get_sla_deadline_days(request: dict) -> int:
    """Returns the SLA deadline in days for a request's channel."""
    return SLA_DAYS.get(
        request.get("channel", ""),
        SLA_DAYS["default"],
    )


def _was_completed_on_time(request: dict) -> bool:
    """
    Returns True if the request was completed within SLA.
    Uses status_history to find ASSIGNED → COMPLETED transition timestamps.
    """
    history = request.get("status_history", [])
    sla_days = _get_sla_deadline_days(request)

    assigned_at   = None
    completed_at  = None

    for entry in history:
        to_state = entry.get("to_state", entry.get("state", ""))
        ts       = entry.get("timestamp", "")
        if to_state == "ASSIGNED" and not assigned_at:
            assigned_at = ts
        if to_state in {"COMPLETED", "ARCHIVED"} and not completed_at:
            completed_at = ts

    if not assigned_at or not completed_at:
        # Fallback: use created_at → updated_at
        assigned_at  = request.get("created_at", "")
        completed_at = request.get("updated_at",  "")

    days = _days_between(assigned_at, completed_at)
    if days is None:
        return True   # Assume on-time if dates are missing
    return days <= sla_days


def _average_quality_score(completed: list[dict]) -> float:
    """
    Returns the average report quality score for completed requests.
    Quality score is stored in request.report_quality (0–100).
    Returns 70.0 (neutral) if no ratings are found.
    """
    scored  = [
        float(r.get("report_quality", 0))
        for r in completed
        if r.get("report_quality") and float(r.get("report_quality", 0)) > 0
    ]
    if not scored:
        return 70.0   # Neutral default when no ratings exist
    return sum(scored) / len(scored)


def _active_days_since_first_request(requests: list[dict]) -> float:
    """
    Returns the number of calendar days from the member's first
    assigned request to today (minimum 1 to avoid division by zero).
    """
    timestamps = [
        _parse_dt(r.get("created_at", ""))
        for r in requests
        if r.get("created_at")
    ]
    if not timestamps:
        return 1.0
    first = min(t for t in timestamps if t)
    days  = (datetime.utcnow() - first).days
    return max(days, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# COMPONENT SCORE CALCULATORS
# ══════════════════════════════════════════════════════════════════════════════

def _score_completion_rate(
    total_assigned: int,
    total_completed: int,
) -> float:
    """Returns 0–100 score for completion rate."""
    if total_assigned == 0:
        return 50.0   # Neutral for new members
    return _clamp((total_completed / total_assigned) * 100)


def _score_on_time_rate(completed: list[dict]) -> float:
    """Returns 0–100 score for on-time completion rate."""
    if not completed:
        return 50.0
    on_time = sum(1 for r in completed if _was_completed_on_time(r))
    return _clamp((on_time / len(completed)) * 100)


def _score_quality(completed: list[dict]) -> float:
    """Returns 0–100 score from average report quality ratings."""
    return _clamp(_average_quality_score(completed))


def _score_throughput(completed: list[dict], active_days: float) -> float:
    """
    Returns 0–100 score for throughput (completed requests per day).
    Normalised against THROUGHPUT_CAP.
    """
    if not completed or active_days <= 0:
        return 40.0   # Below neutral for inactive members
    rate = len(completed) / active_days
    return _clamp((rate / THROUGHPUT_CAP) * 100)


def _score_load_efficiency(member: dict) -> float:
    """
    Returns 0–100 score for load efficiency.
    A member consistently near (but not over) max_load scores higher.
    Currently uses a static snapshot: current_load / max_load.
    """
    current = int(member.get("current_load", 0))
    maximum = int(member.get("max_load",     5))
    if maximum == 0:
        return 50.0
    ratio = current / maximum
    # Optimal range: 50–90% load
    if 0.50 <= ratio <= 0.90:
        return 100.0
    elif ratio < 0.50:
        return _clamp(ratio * 200)           # Scale 0–50% → 0–100
    else:
        return _clamp((1.0 - ratio) * 1000)  # Penalise overload


def _score_rejection_penalty(
    total_completed:      int,
    rejected_after_assign: int,
) -> float:
    """
    Returns 0–100 where 100 = no rejections after assignment.
    Each rejection reduces the score proportionally.
    """
    if rejected_after_assign == 0:
        return 100.0
    base       = total_completed + rejected_after_assign
    if base == 0:
        return 100.0
    penalty_pct = rejected_after_assign / base
    return _clamp((1.0 - penalty_pct) * 100)


# ══════════════════════════════════════════════════════════════════════════════
# CORE SCORING FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def compute_member_score(member_id: str) -> dict:
    """
    Computes the full productivity score for a member.

    Returns a score_result dict:
    {
        member_id,
        score         (float 0–100),
        label         (EXCELLENT | GOOD | NORMAL | LOW),
        components: {
            completion_rate:   { raw, score, weight, weighted },
            on_time_rate:      { raw, score, weight, weighted },
            quality_score:     { raw, score, weight, weighted },
            throughput:        { raw, score, weight, weighted },
            load_efficiency:   { raw, score, weight, weighted },
            rejection_penalty: { raw, score, weight, weighted },
        },
        stats: {
            total_assigned,
            total_completed,
            on_time_count,
            late_count,
            rejected_after_assign,
            avg_quality,
            active_days,
            throughput_per_day,
            sla_days_ibtikar,
            sla_days_genoclab,
        },
        computed_at,
    }
    """
    member = get_member(member_id)
    if not member:
        raise ProductivityError(
            f"Membre introuvable: `{member_id}`."
        )

    # ── Collect data ──────────────────────────────────────────────────────────
    all_reqs  = _get_all_requests_for_member(member_id)
    completed = _get_completed_requests(all_reqs)
    rejected  = _get_rejected_after_assignment(all_reqs)
    active_days = _active_days_since_first_request(all_reqs)

    total_assigned  = len(all_reqs)
    total_completed = len(completed)
    rejected_count  = len(rejected)
    on_time_count   = sum(1 for r in completed if _was_completed_on_time(r))
    late_count      = total_completed - on_time_count
    avg_quality     = _average_quality_score(completed)
    throughput_per_day = (
        total_completed / active_days if active_days > 0 else 0.0
    )

    # ── Component scores ──────────────────────────────────────────────────────
    s_completion = _score_completion_rate(total_assigned, total_completed)
    s_ontime     = _score_on_time_rate(completed)
    s_quality    = _score_quality(completed)
    s_throughput = _score_throughput(completed, active_days)
    s_load       = _score_load_efficiency(member)
    s_rejection  = _score_rejection_penalty(total_completed, rejected_count)

    # Raw values for display
    raw = {
        "completion_rate":   round(
            (total_completed / total_assigned * 100)
            if total_assigned else 0.0, 1
        ),
        "on_time_rate":      round(
            (on_time_count / total_completed * 100)
            if total_completed else 0.0, 1
        ),
        "quality_score":     round(avg_quality, 1),
        "throughput":        round(throughput_per_day, 3),
        "load_efficiency":   round(
            int(member.get("current_load", 0)) /
            max(int(member.get("max_load", 5)), 1) * 100, 1
        ),
        "rejection_penalty": rejected_count,
    }

    score_vals = {
        "completion_rate":   s_completion,
        "on_time_rate":      s_ontime,
        "quality_score":     s_quality,
        "throughput":        s_throughput,
        "load_efficiency":   s_load,
        "rejection_penalty": s_rejection,
    }

    # ── Weighted composite score ───────────────────────────────────────────────
    weighted_sum = sum(
        score_vals[k] * WEIGHTS[k]
        for k in WEIGHTS
    )
    final_score = _clamp(round(weighted_sum, 2))
    label       = _score_to_label(final_score)

    # ── Build components breakdown ────────────────────────────────────────────
    components = {
        k: {
            "raw":      raw[k],
            "score":    round(score_vals[k], 2),
            "weight":   WEIGHTS[k],
            "weighted": round(score_vals[k] * WEIGHTS[k], 2),
        }
        for k in WEIGHTS
    }

    return {
        "member_id":    member_id,
        "score":        final_score,
        "label":        label,
        "components":   components,
        "stats": {
            "total_assigned":       total_assigned,
            "total_completed":      total_completed,
            "on_time_count":        on_time_count,
            "late_count":           late_count,
            "rejected_after_assign":rejected_count,
            "avg_quality":          round(avg_quality, 1),
            "active_days":          round(active_days, 1),
            "throughput_per_day":   round(throughput_per_day, 4),
            "sla_days_ibtikar":     SLA_DAYS[CHANNEL_IBTIKAR],
            "sla_days_genoclab":    SLA_DAYS[CHANNEL_GENOCLAB],
        },
        "computed_at":  _now_iso(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SAVE & PERSIST
# ══════════════════════════════════════════════════════════════════════════════

def _persist_score(
    member:       dict,
    score_result: dict,
) -> dict:
    """
    Writes the new score back to the member record.
    Appends to productivity_history (capped at MAX_HISTORY_ENTRIES).
    Returns the updated member dict.
    """
    score = score_result["score"]
    label = score_result["label"]

    history_entry = {
        "timestamp":  score_result["computed_at"],
        "score":      score,
        "label":      label,
        "stats":      score_result["stats"],
        "components": {
            k: v["score"]
            for k, v in score_result["components"].items()
        },
    }

    history = member.get("productivity_history", [])
    if not isinstance(history, list):
        history = []
    history.append(history_entry)

    # Trim to cap
    if len(history) > MAX_HISTORY_ENTRIES:
        history = history[-MAX_HISTORY_ENTRIES:]

    member["productivity_score"]   = score
    member["productivity_label"]   = label
    member["productivity_trend"]   = _trend(history)
    member["productivity_history"] = history
    member["productivity_updated_at"] = score_result["computed_at"]

    save_member(member)
    return member


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def recalculate_member(
    member_id: str,
    user:      dict,
    silent:    bool = False,
) -> dict:
    """
    Computes and persists the productivity score for a single member.

    Args:
        member_id: Member to recalculate.
        user:      Actor triggering the recalculation (for audit log).
        silent:    If True, skips audit log and notification.

    Returns:
        { score, label, trend, member_id, stats, components, computed_at }

    Raises:
        ProductivityError — if member not found.
    """
    member = get_member(member_id)
    if not member:
        raise ProductivityError(f"Membre introuvable: `{member_id}`.")

    score_result = compute_member_score(member_id)
    _persist_score(member, score_result)

    if not silent:
        # Audit log
        try:
            from core.audit_engine import log_productivity_event
            log_productivity_event(
                member_id   = member_id,
                member_name = member.get("name", "–"),
                score       = score_result["score"],
                label       = score_result["label"],
                actor       = user,
            )
        except Exception:
            pass

        # Notify member if score changed significantly
        try:
            _notify_member_score_change(member, score_result)
        except Exception:
            pass

    return {
        "member_id":   member_id,
        "score":       score_result["score"],
        "label":       score_result["label"],
        "trend":       member.get("productivity_trend", "→ Stable"),
        "stats":       score_result["stats"],
        "components":  score_result["components"],
        "computed_at": score_result["computed_at"],
    }


def recalculate_all(
    user:   dict,
    silent: bool = False,
) -> list[dict]:
    """
    Recalculates productivity scores for ALL members.

    Returns:
        List of result dicts (one per member):
        [{ member_id, name, score, label, trend, error }]
    """
    members = get_all_members()
    results = []

    for member in members:
        mid = member.get("id", "")
        try:
            result = recalculate_member(mid, user=user, silent=silent)
            results.append({
                "member_id": mid,
                "name":      member.get("name", "–"),
                "score":     result["score"],
                "label":     result["label"],
                "trend":     result["trend"],
                "error":     None,
            })
        except ProductivityError as e:
            results.append({
                "member_id": mid,
                "name":      member.get("name", "–"),
                "score":     None,
                "label":     None,
                "trend":     None,
                "error":     str(e),
            })

    return results


def get_member_score_history(
    member_id: str,
    last_n:    int = 30,
) -> list[dict]:
    """
    Returns the last N productivity history entries for a member.

    Returns:
        [{ timestamp, score, label, trend, stats }]
    """
    member = get_member(member_id)
    if not member:
        return []
    history = member.get("productivity_history", [])
    if not isinstance(history, list):
        return []
    return history[-last_n:]


def get_productivity_ranking(
    channel:  Optional[str] = None,
    top_n:    int           = 10,
    available_only: bool    = False,
) -> list[dict]:
    """
    Returns members ranked by productivity score (descending).

    Args:
        channel:        Filter to members with skills in this channel (optional).
        top_n:          Maximum entries to return.
        available_only: If True, only available members.

    Returns:
        [{ rank, member_id, name, score, label, trend,
           current_load, max_load, available }]
    """
    members = get_all_members()

    if available_only:
        members = [m for m in members if m.get("available", True)]

    if channel:
        # Filter to members with at least one skill for the channel's services
        # (simplified: no channel-service mapping here, return all)
        pass

    ranked = sorted(
        members,
        key     = lambda m: float(m.get("productivity_score", 0)),
        reverse = True,
    )

    result = []
    for i, m in enumerate(ranked[:top_n], start=1):
        history = m.get("productivity_history", [])
        result.append({
            "rank":         i,
            "member_id":    m.get("id",                  ""),
            "name":         m.get("name",                "–"),
            "score":        float(m.get("productivity_score", 0)),
            "label":        m.get("productivity_label",  "NORMAL"),
            "trend":        m.get("productivity_trend",  "→ Stable"),
            "current_load": int(m.get("current_load",    0)),
            "max_load":     int(m.get("max_load",        5)),
            "available":    m.get("available",           True),
            "history_len":  len(history),
        })
    return result


def get_team_productivity_summary() -> dict:
    """
    Returns a team-wide productivity summary.

    Returns:
        {
            total_members,
            avg_score,
            median_score,
            by_label: { EXCELLENT, GOOD, NORMAL, LOW },
            available_count,
            top_member: { name, score, label },
            bottom_member: { name, score, label },
            total_completed_requests,
            team_avg_on_time_rate_pct,
            team_avg_quality,
        }
    """
    members = get_all_members()
    if not members:
        return {
            "total_members": 0,
            "avg_score": 0.0,
            "median_score": 0.0,
            "by_label": {"EXCELLENT": 0, "GOOD": 0, "NORMAL": 0, "LOW": 0},
            "available_count": 0,
            "top_member": None,
            "bottom_member": None,
            "total_completed_requests": 0,
            "team_avg_on_time_rate_pct": 0.0,
            "team_avg_quality": 0.0,
        }

    scores  = [float(m.get("productivity_score", 50)) for m in members]
    n       = len(scores)
    avg     = sum(scores) / n
    sorted_scores = sorted(scores)
    median  = (
        sorted_scores[n // 2]
        if n % 2 == 1
        else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
    )

    by_label = {"EXCELLENT": 0, "GOOD": 0, "NORMAL": 0, "LOW": 0}
    for m in members:
        lbl = m.get("productivity_label", "NORMAL")
        by_label[lbl] = by_label.get(lbl, 0) + 1

    available_count = sum(1 for m in members if m.get("available", True))

    ranked      = sorted(members, key=lambda m: float(m.get("productivity_score", 0)))
    top_m       = ranked[-1] if ranked else None
    bottom_m    = ranked[0]  if ranked else None

    # Team-wide request stats
    all_reqs   = get_all_active_requests() + get_all_archived_requests()
    total_comp = len([
        r for r in all_reqs
        if r.get("status") in {"COMPLETED", "ARCHIVED"}
        and r.get("assigned_member_id")
    ])

    # Team avg on-time rate across all completed requests
    completed_all = [
        r for r in all_reqs
        if r.get("status") in {"COMPLETED", "ARCHIVED"}
        and r.get("assigned_member_id")
    ]
    on_time_all = sum(1 for r in completed_all if _was_completed_on_time(r))
    team_on_time_pct = (
        round(on_time_all / len(completed_all) * 100, 1)
        if completed_all else 0.0
    )

    quality_scores = [
        float(r.get("report_quality", 0))
        for r in completed_all
        if r.get("report_quality") and float(r.get("report_quality", 0)) > 0
    ]
    team_avg_quality = (
        round(sum(quality_scores) / len(quality_scores), 1)
        if quality_scores else 0.0
    )

    return {
        "total_members":             n,
        "avg_score":                 round(avg, 2),
        "median_score":              round(median, 2),
        "by_label":                  by_label,
        "available_count":           available_count,
        "top_member": {
            "name":  top_m.get("name",                "–") if top_m else "–",
            "score": float(top_m.get("productivity_score", 0)) if top_m else 0.0,
            "label": top_m.get("productivity_label",  "–") if top_m else "–",
        } if top_m else None,
        "bottom_member": {
            "name":  bottom_m.get("name",                "–") if bottom_m else "–",
            "score": float(bottom_m.get("productivity_score", 0)) if bottom_m else 0.0,
            "label": bottom_m.get("productivity_label",  "–") if bottom_m else "–",
        } if bottom_m else None,
        "total_completed_requests":  total_comp,
        "team_avg_on_time_rate_pct": team_on_time_pct,
        "team_avg_quality":          team_avg_quality,
    }


def set_report_quality(
    request_id: str,
    score:      float,
    actor:      dict,
) -> dict:
    """
    Sets a quality rating (0–100) on a completed request's report.
    Triggers an immediate productivity recalculation for the assigned member.

    Args:
        request_id: The request to rate.
        score:      Quality score 0–100.
        actor:      User performing the rating.

    Returns:
        Updated request dict.
    """
    from core.repository import get_request, save_request
    if not 0 <= score <= 100:
        raise ProductivityError(
            f"Score de qualité invalide: {score}. "
            f"Doit être entre 0 et 100."
        )

    req = get_request(request_id)
    if not req:
        from core.exceptions import RequestNotFoundError
        raise RequestNotFoundError(request_id)

    req["report_quality"]    = round(float(score), 1)
    req["quality_rated_by"]  = actor.get("id", "system")
    req["quality_rated_at"]  = _now_iso()
    req["updated_at"]        = _now_iso()
    save_request(req)

    # Trigger recalculation for the assigned member
    member_id = req.get("assigned_member_id")
    if member_id:
        try:
            recalculate_member(member_id, user=actor, silent=True)
        except ProductivityError:
            pass

    return req


def get_member_sla_compliance(member_id: str) -> dict:
    """
    Returns SLA compliance breakdown per channel for a member.

    Returns:
        {
            member_id,
            overall_pct,
            by_channel: {
                IBTIKAR:  { total, on_time, late, pct, sla_days },
                GENOCLAB: { total, on_time, late, pct, sla_days },
            }
        }
    """
    all_reqs  = _get_all_requests_for_member(member_id)
    completed = _get_completed_requests(all_reqs)

    by_channel: dict = {}
    for ch in [CHANNEL_IBTIKAR, CHANNEL_GENOCLAB]:
        ch_reqs  = [r for r in completed if r.get("channel") == ch]
        on_time  = sum(1 for r in ch_reqs if _was_completed_on_time(r))
        late     = len(ch_reqs) - on_time
        sla_days = _get_sla_deadline_days({"channel": ch})
        by_channel[ch] = {
            "total":    len(ch_reqs),
            "on_time":  on_time,
            "late":     late,
            "pct":      round(on_time / len(ch_reqs) * 100, 1) if ch_reqs else 0.0,
            "sla_days": sla_days,
        }

    total_comp  = len(completed)
    total_on_time = sum(
        1 for r in completed if _was_completed_on_time(r)
    )
    overall_pct = (
        round(total_on_time / total_comp * 100, 1)
        if total_comp else 0.0
    )

    return {
        "member_id":   member_id,
        "overall_pct": overall_pct,
        "by_channel":  by_channel,
    }


# ── Private: score change notification ───────────────────────────────────────
def _notify_member_score_change(
    member:       dict,
    score_result: dict,
) -> None:
    """
    Sends a notification to the member if their productivity label changed
    or if their score moved significantly (±10 points).
    """
    from core.repository import create_notification

    prev_score = float(member.get("productivity_score", 50))
    new_score  = score_result["score"]
    prev_label = member.get("productivity_label", "NORMAL")
    new_label  = score_result["label"]
    member_uid = member.get("user_id")

    if not member_uid:
        return

    label_changed  = prev_label != new_label
    score_changed  = abs(new_score - prev_score) >= 10

    if label_changed or score_changed:
        direction = "amélioré" if new_score > prev_score else "baissé"
        create_notification(
            title   = f"📊 Productivité mise à jour — {new_label}",
            message = (
                f"Votre score de productivité a {direction}: "
                f"**{prev_score:.0f} → {new_score:.0f}** "
                f"({prev_label} → {new_label})."
            ),
            level   = (
                "success" if new_score > prev_score
                else "warning"
            ),
            user_id = member_uid,
        )