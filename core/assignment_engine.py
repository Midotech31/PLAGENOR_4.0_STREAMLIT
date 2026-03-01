"""
PLAGENOR 4.0 — Assignment Engine
Intelligent member assignment for IBTIKAR and GENOCLAB service requests.

RESPONSIBILITIES:
- Score all eligible members against a request
- Enforce hard gates (availability, load capacity)
- Apply configurable weighted scoring
- Return ranked candidate list with full breakdown for admin transparency
- Execute assignment and trigger ASSIGNED transition
- Never expose the scoring formula for direct modification

NON-NEGOTIABLE:
- Unavailable members are excluded before scoring (hard gate).
- Members at max load capacity are excluded before scoring (hard gate).
- Scoring weights are read from config.ASSIGNMENT_WEIGHTS only.
- The formula structure is protected — only weights are configurable.
- Every assignment is logged with full score breakdown.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from typing import Optional
import config
from config import ASSIGNMENT_WEIGHTS
from core.audit_engine import log_event
from core.exceptions import PlagenorError


# ── Scoring constants (protected — do not expose to UI) ───────────────────────
_MAX_SCORE         = 100.0
_SKILL_MATCH_FULL  = 1.0    # exact service match
_SKILL_MATCH_CAT   = 0.6    # same service category
_SKILL_MATCH_NONE  = 0.1    # no match — minimum baseline


# ── Hard gate checks ──────────────────────────────────────────────────────────

def _is_available(member: dict) -> bool:
    """
    Hard gate 1: Member must be explicitly available.
    available=True AND not on leave AND account active.
    """
    return (
        member.get("available", False) is True
        and member.get("on_leave", False) is False
        and member.get("active", True) is True
    )


def _is_under_load(member: dict) -> bool:
    """
    Hard gate 2: Member must have capacity below their max_load.
    Strict less-than — a member at exactly max_load is excluded.
    """
    current = int(member.get("current_load", 0))
    maximum = int(member.get("max_load", config.DEFAULT_MAX_LOAD
                             if hasattr(config, "DEFAULT_MAX_LOAD") else 5))
    return current < maximum


# ── Skill scoring ─────────────────────────────────────────────────────────────

def _score_skill(member: dict, service: dict) -> float:
    """
    Scores skill match between member expertise and requested service.
    Returns normalised 0.0–1.0:
      1.0 → exact service code match in member's specializations
      0.6 → service category match
      0.1 → no match (minimum baseline — never zero)
    """
    service_code     = service.get("name", "").upper()
    service_category = service.get("category", "").upper()

    specializations = [
        s.upper() for s in member.get("specializations", [])
    ]
    categories = [
        c.upper() for c in member.get("categories", [])
    ]

    if service_code in specializations:
        return _SKILL_MATCH_FULL
    if service_category and service_category in categories:
        return _SKILL_MATCH_CAT
    return _SKILL_MATCH_NONE


# ── Load scoring ──────────────────────────────────────────────────────────────

def _score_load(member: dict) -> float:
    """
    Scores inverse load ratio — lower load = higher score.
    Returns normalised 0.0–1.0.
    A member with 0 load scores 1.0 (best).
    A member at max_load - 1 scores close to 0 (but already excluded at max).
    """
    current = int(member.get("current_load", 0))
    maximum = int(member.get("max_load",
                             getattr(config, "DEFAULT_MAX_LOAD", 5)))
    if maximum <= 0:
        return 0.0
    # Inverse ratio: (max - current) / max
    return max(0.0, (maximum - current) / maximum)


# ── Productivity scoring ───────────────────────────────────────────────────────

def _score_productivity(member: dict) -> float:
    """
    Scores member productivity contribution.
    Reads last recorded productivity score (0–100).
    Returns normalised 0.0–1.0.
    """
    prod_score = float(member.get("productivity_score", 50.0))
    return max(0.0, min(prod_score / 100.0, 1.0))


# ── Composite score ───────────────────────────────────────────────────────────

def _compute_score(
    member:  dict,
    service: dict,
    weights: dict,
) -> dict:
    """
    Computes the composite assignment score for one member.
    Weights are read from config.ASSIGNMENT_WEIGHTS (or overridden by admin).
    Formula is protected — weights are the only configurable parameter.

    Returns a score breakdown dict:
    {
      "member_id":          str,
      "member_name":        str,
      "raw_skill":          float,   # 0.0–1.0
      "raw_load":           float,   # 0.0–1.0
      "raw_productivity":   float,   # 0.0–1.0
      "w_skill":            float,   # configured weight
      "w_load":             float,
      "w_productivity":     float,
      "weighted_skill":     float,   # raw × weight
      "weighted_load":      float,
      "weighted_productivity": float,
      "total_weight":       float,   # sum of weights
      "final_score":        float,   # 0–100, normalised
      "current_load":       int,
      "max_load":           int,
      "specializations":    list,
    }
    """
    w_skill        = float(weights.get("skill",        40.0))
    w_load         = float(weights.get("load",         30.0))
    w_productivity = float(weights.get("productivity", 20.0))
    # availability weight is a hard gate — not used in scoring formula

    raw_skill        = _score_skill(member, service)
    raw_load         = _score_load(member)
    raw_productivity = _score_productivity(member)

    weighted_skill        = raw_skill        * w_skill
    weighted_load         = raw_load         * w_load
    weighted_productivity = raw_productivity * w_productivity

    total_weight = w_skill + w_load + w_productivity
    if total_weight <= 0:
        final_score = 0.0
    else:
        # Normalise to 0–100
        final_score = round(
            (weighted_skill + weighted_load + weighted_productivity)
            / total_weight * _MAX_SCORE,
            2,
        )

    return {
        "member_id":             member["id"],
        "member_name":           member.get("name", member["id"]),
        "user_id":               member.get("user_id", ""),
        # Raw component scores
        "raw_skill":             round(raw_skill,        4),
        "raw_load":              round(raw_load,         4),
        "raw_productivity":      round(raw_productivity, 4),
        # Configured weights
        "w_skill":               w_skill,
        "w_load":                w_load,
        "w_productivity":        w_productivity,
        # Weighted contributions
        "weighted_skill":        round(weighted_skill,        2),
        "weighted_load":         round(weighted_load,         2),
        "weighted_productivity": round(weighted_productivity, 2),
        # Totals
        "total_weight":          total_weight,
        "final_score":           final_score,
        # Metadata for admin display
        "current_load":          int(member.get("current_load", 0)),
        "max_load":              int(member.get("max_load",
                                     getattr(config, "DEFAULT_MAX_LOAD", 5))),
        "specializations":       member.get("specializations", []),
        "availability":          member.get("available", False),
        "productivity_label":    member.get("productivity_label", "NORMAL"),
        "declining":             member.get("declining", False),
    }


# ── Candidate ranking ─────────────────────────────────────────────────────────

def rank_candidates(
    request: dict,
    weights: Optional[dict] = None,
) -> list:
    """
    Ranks all eligible members for a given request.
    Applies hard gates first, then scores and sorts.

    Args:
        request: The full request dict (must include service_id).
        weights: Optional weight override dict (SUPER_ADMIN only).
                 Falls back to config.ASSIGNMENT_WEIGHTS.

    Returns:
        List of score breakdown dicts, sorted by final_score descending.
        Empty list if no eligible members.

    Includes:
        - excluded: list of dicts explaining why each member was excluded.
    """
    from core.repository import get_all_members, get_service_by_id
    from core.exceptions import EntityNotFoundError

    # Resolve service
    service_id = request.get("service_id", "")
    try:
        service = get_service_by_id(service_id)
    except EntityNotFoundError:
        service = {"name": service_id, "category": ""}

    effective_weights = weights or ASSIGNMENT_WEIGHTS

    all_members = get_all_members()
    candidates  = []
    excluded    = []

    for member in all_members:
        # Hard gate 1: availability
        if not _is_available(member):
            excluded.append({
                "member_id":   member["id"],
                "member_name": member.get("name", member["id"]),
                "reason":      (
                    "En congé" if member.get("on_leave") else
                    "Inactif"  if not member.get("active", True) else
                    "Non disponible"
                ),
            })
            continue

        # Hard gate 2: load capacity
        if not _is_under_load(member):
            excluded.append({
                "member_id":   member["id"],
                "member_name": member.get("name", member["id"]),
                "reason":      (
                    f"Charge maximale atteinte "
                    f"({member.get('current_load', 0)}"
                    f"/{member.get('max_load', getattr(config, 'DEFAULT_MAX_LOAD', 5))})"
                ),
            })
            continue

        # Score eligible member
        breakdown = _compute_score(member, service, effective_weights)
        candidates.append(breakdown)

    # Sort by final_score descending
    candidates.sort(key=lambda x: x["final_score"], reverse=True)

    return candidates, excluded


# ── Assignment execution ──────────────────────────────────────────────────────

def assign_best_member(
    request_id: str,
    actor:      dict,
    weights:    Optional[dict] = None,
    override_member_id: Optional[str] = None,
) -> dict:
    """
    Assigns the best eligible member to a request.
    Transitions request to ASSIGNED → PENDING_ACCEPTANCE.

    Args:
        request_id:         UUID of the request to assign.
        actor:              The admin/super_admin performing the assignment.
        weights:            Optional weight override (SUPER_ADMIN only).
        override_member_id: Manually select a specific member (SUPER_ADMIN only).
                            Still enforces hard gates unless actor is SUPER_ADMIN.

    Returns:
        Updated request dict with assigned_member_id and score_breakdown.

    Raises:
        PlagenorError if no eligible members exist or hard gates fail.
    """
    from core.repository import (
        get_request, save_request,
        get_member_by_id, save_member,
    )
    from core.workflow_engine import transition

    allowed_roles = {config.ROLE_PLATFORM_ADMIN, config.ROLE_SUPER_ADMIN}
    if actor.get("role") not in allowed_roles:
        raise PlagenorError(
            "Seul PLATFORM_ADMIN ou SUPER_ADMIN peut effectuer une assignation."
        )

    # Weight override only for SUPER_ADMIN
    if weights and actor.get("role") != config.ROLE_SUPER_ADMIN:
        raise PlagenorError(
            "Seul SUPER_ADMIN peut modifier les pondérations d'assignation."
        )

    request = get_request(request_id)
    if request is None:
        raise PlagenorError(f"Demande introuvable: {request_id}")

    candidates, excluded = rank_candidates(request, weights)

    # Manual override
    if override_member_id:
        if actor.get("role") != config.ROLE_SUPER_ADMIN:
            raise PlagenorError(
                "Seul SUPER_ADMIN peut forcer l'assignation à un membre spécifique."
            )
        # Find override member in candidates or re-evaluate
        chosen = next(
            (c for c in candidates if c["member_id"] == override_member_id),
            None,
        )
        if chosen is None:
            # Check if excluded (hard gate failed)
            exc = next(
                (e for e in excluded if e["member_id"] == override_member_id),
                None,
            )
            if exc:
                raise PlagenorError(
                    f"Le membre sélectionné est exclu: {exc['reason']}. "
                    f"SUPER_ADMIN peut forcer uniquement si le membre passe les "
                    f"portes de disponibilité et de charge."
                )
            raise PlagenorError(
                f"Membre introuvable: {override_member_id}"
            )
    else:
        if not candidates:
            exc_summary = "; ".join(
                f"{e['member_name']} ({e['reason']})" for e in excluded
            ) or "Aucun membre enregistré"
            raise PlagenorError(
                f"❌ Aucun analyste éligible disponible pour cette demande.\n"
                f"Membres exclus: {exc_summary}"
            )
        chosen = candidates[0]  # highest score

    member_id = chosen["member_id"]

    # Update member load
    try:
        member = get_member_by_id(member_id)
        member["current_load"] = int(member.get("current_load", 0)) + 1
        save_member(member)
    except Exception as e:
        raise PlagenorError(f"Erreur mise à jour charge analyste: {e}")

    # Attach assignment metadata to request
    request["assigned_member_id"] = member_id
    request["assigned_member_name"] = chosen["member_name"]
    request["assignment_score"]   = chosen["final_score"]
    request["score_breakdown"]    = chosen
    request["all_candidates"]     = candidates        # full ranking for admin
    request["excluded_members"]   = excluded          # exclusion reasons
    request["assigned_at"]        = datetime.utcnow().isoformat()
    request["assigned_by"]        = actor.get("id")
    save_request(request)

    # Transition to ASSIGNED → triggers PENDING_ACCEPTANCE notification
    result = transition(request_id, "ASSIGNED", actor)

    log_event(
        entity_type = "ASSIGNMENT",
        entity_id   = request_id,
        action      = "MEMBER_ASSIGNED",
        user_id     = actor["id"],
        details     = {
            "assigned_member_id":   member_id,
            "assigned_member_name": chosen["member_name"],
            "final_score":          chosen["final_score"],
            "score_breakdown":      chosen,
            "candidates_count":     len(candidates),
            "excluded_count":       len(excluded),
            "weights_used":         weights or ASSIGNMENT_WEIGHTS,
            "override":             override_member_id is not None,
        },
    )
    return result


def release_member_load(
    request_id: str,
    actor:      dict,
) -> None:
    """
    Decrements assigned member's load when a request reaches a terminal state
    or is rejected after assignment.
    Called by workflow_engine on COMPLETED/REJECTED transitions.
    Silent on failure — load imbalance is recoverable via recalculation.
    """
    from core.repository import get_request, get_member_by_id, save_member
    try:
        request   = get_request(request_id)
        if not request:
            return
        member_id = request.get("assigned_member_id")
        if not member_id:
            return
        member = get_member_by_id(member_id)
        current = int(member.get("current_load", 0))
        member["current_load"] = max(0, current - 1)
        save_member(member)
        log_event(
            entity_type = "ASSIGNMENT",
            entity_id   = request_id,
            action      = "MEMBER_LOAD_RELEASED",
            user_id     = actor.get("id", "system"),
            details     = {
                "member_id":    member_id,
                "new_load":     member["current_load"],
            },
        )
    except Exception:
        pass   # silent — non-blocking


# ── Weight validation helper (for SUPER_ADMIN config panel) ──────────────────

def validate_weights(weights: dict) -> dict:
    """
    Validates custom weight values before applying.
    Each weight must be a float between 0.0 and 100.0.
    Returns {"valid": bool, "errors": list[str]}.
    Used by SUPER_ADMIN configuration panel only.
    """
    errors   = []
    required = {"skill", "load", "productivity"}

    for key in required:
        val = weights.get(key)
        if val is None:
            errors.append(f"Pondération manquante: '{key}'")
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            errors.append(f"Valeur invalide pour '{key}': {val}")
            continue
        if not (0.0 <= fval <= 100.0):
            errors.append(
                f"Pondération '{key}' hors limites: {fval} "
                f"(doit être entre 0 et 100)"
            )

    return {"valid": len(errors) == 0, "errors": errors}


# ── Score breakdown renderer (for admin dashboard) ────────────────────────────

def format_score_breakdown_for_display(breakdown: dict) -> dict:
    """
    Returns a display-safe version of a score breakdown dict.
    Strips internal formula details — only exposes what admin needs to see.

    Returns:
    {
      "member_name":     str,
      "final_score":     float,
      "skill_pct":       float,   # weighted skill contribution %
      "load_pct":        float,   # weighted load contribution %
      "productivity_pct": float,  # weighted productivity contribution %
      "current_load":    str,     # "2 / 5"
      "specializations": list,
      "productivity_label": str,
      "declining":       bool,
    }
    """
    total_w = breakdown.get("total_weight", 1.0) or 1.0
    return {
        "member_name":        breakdown.get("member_name", ""),
        "final_score":        breakdown.get("final_score", 0.0),
        "skill_pct":          round(
            breakdown.get("weighted_skill", 0) / total_w * 100, 1),
        "load_pct":           round(
            breakdown.get("weighted_load", 0) / total_w * 100, 1),
        "productivity_pct":   round(
            breakdown.get("weighted_productivity", 0) / total_w * 100, 1),
        "current_load":       (
            f"{breakdown.get('current_load', 0)} "
            f"/ {breakdown.get('max_load', 5)}"
        ),
        "specializations":    breakdown.get("specializations", []),
        "productivity_label": breakdown.get("productivity_label", "NORMAL"),
        "declining":          breakdown.get("declining", False),
    }