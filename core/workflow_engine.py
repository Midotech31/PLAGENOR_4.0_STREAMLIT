# core/workflow_engine.py
# ── PLAGENOR 4.0 — Workflow Engine ───────────────────────────────────────────
# Manages all state machine transitions for both channels:
#   IBTIKAR  — institutional research funding requests
#   GENOCLAB — external genomics service requests (with billing)
#
# Core contract:
#   transition(request_id, to_state, actor, **kwargs) → updated request dict
#
# State names are sourced from config.IbtikarState / config.GenoClabState.
# Never hardcode state strings here — always read from config.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime
from typing import Any, Optional

import config
from config import IbtikarState as IS, GenoClabState as GS
from core.exceptions import (
    InvalidTransitionError,
    RequestNotFoundError,
    MissingTransitionDataError,
    WorkflowError,
    NoAvailableMemberError,
    MemberUnavailableError,
    MemberOverloadedError,
)
from core.repository import (
    get_request,
    save_request,
    get_member,
    get_available_members_for_service,
    increment_member_load,
    decrement_member_load,
    archive_request,
    create_notification,
    get_user,
)


# ── Channel constants ─────────────────────────────────────────────────────────
CH_IBTIKAR  = config.CHANNEL_IBTIKAR
CH_GENOCLAB = config.CHANNEL_GENOCLAB


# ══════════════════════════════════════════════════════════════════════════════
# STATE MACHINE GRAPHS
# Each key = from_state; value = set of allowed to_states.
# Backward (corrective) transitions are included where operationally needed.
# ══════════════════════════════════════════════════════════════════════════════

IBTIKAR_TRANSITIONS: dict[str, set] = {
    IS.SUBMITTED:             {IS.VALIDATED,             IS.REJECTED},
    IS.VALIDATED:             {IS.APPROVED,              IS.REJECTED},
    IS.APPROVED:              {IS.APPOINTMENT_SCHEDULED, IS.REJECTED},
    IS.APPOINTMENT_SCHEDULED: {IS.SAMPLE_RECEIVED,       IS.APPROVED},      # APPROVED = cancel appt
    IS.SAMPLE_RECEIVED:       {IS.SAMPLE_VERIFIED,       IS.APPOINTMENT_SCHEDULED},
    IS.SAMPLE_VERIFIED:       {IS.ASSIGNED,              IS.SAMPLE_RECEIVED},
    IS.ASSIGNED:              {IS.PENDING_ACCEPTANCE,    IS.SAMPLE_VERIFIED},  # SAMPLE_VERIFIED = unassign
    IS.PENDING_ACCEPTANCE:    {IS.IN_PROGRESS,           IS.SAMPLE_VERIFIED},  # SAMPLE_VERIFIED = reject
    IS.IN_PROGRESS:           {IS.ANALYSIS_FINISHED,     IS.ASSIGNED},         # ASSIGNED = reopen
    IS.ANALYSIS_FINISHED:     {IS.REPORT_UPLOADED,       IS.IN_PROGRESS},
    IS.REPORT_UPLOADED:       {IS.ADMIN_REVIEW,          IS.ANALYSIS_FINISHED},
    IS.ADMIN_REVIEW:          {IS.REPORT_VALIDATED,      IS.REPORT_UPLOADED},  # REPORT_UPLOADED = re-review
    IS.REPORT_VALIDATED:      {IS.SENT_TO_REQUESTER},
    IS.SENT_TO_REQUESTER:     {IS.COMPLETED},
    IS.COMPLETED:             {IS.COMPLETED},             # soft terminal — ARCHIVED via bulk_archive
    IS.REJECTED:              {IS.REJECTED},              # soft terminal
}


GENOCLAB_TRANSITIONS: dict[str, set] = {
    GS.SUBMITTED:                 {GS.VALIDATED,                  GS.REJECTED},
    GS.VALIDATED:                 {GS.QUOTE_DRAFT,                GS.REJECTED},
    GS.QUOTE_DRAFT:               {GS.QUOTE_SENT,                 GS.VALIDATED},  # VALIDATED = revise
    GS.QUOTE_SENT:                {GS.QUOTE_VALIDATED_BY_CLIENT,  GS.QUOTE_REJECTED_BY_CLIENT},
    GS.QUOTE_VALIDATED_BY_CLIENT: {GS.INVOICE_GENERATED},
    GS.INVOICE_GENERATED:         {GS.ASSIGNED},
    GS.ASSIGNED:                  {GS.PENDING_ACCEPTANCE,         GS.INVOICE_GENERATED},  # INVOICE_GENERATED = unassign
    GS.PENDING_ACCEPTANCE:        {GS.IN_PROGRESS,                GS.INVOICE_GENERATED},  # INVOICE_GENERATED = reject
    GS.IN_PROGRESS:               {GS.ANALYSIS_FINISHED,          GS.ASSIGNED},           # ASSIGNED = reopen
    GS.ANALYSIS_FINISHED:         {GS.REPORT_UPLOADED,            GS.IN_PROGRESS},
    GS.REPORT_UPLOADED:           {GS.ADMIN_REVIEW,               GS.ANALYSIS_FINISHED},
    GS.ADMIN_REVIEW:              {GS.REPORT_VALIDATED,           GS.REPORT_UPLOADED},
    GS.REPORT_VALIDATED:          {GS.SENT_TO_CLIENT},
    GS.SENT_TO_CLIENT:            {GS.COMPLETED},
    GS.COMPLETED:                 {GS.COMPLETED},              # soft terminal
    GS.REJECTED:                  {GS.REJECTED},               # soft terminal
    GS.QUOTE_REJECTED_BY_CLIENT:  {GS.QUOTE_REJECTED_BY_CLIENT}, # soft terminal
}


# Unified lookup
TRANSITION_GRAPHS: dict[str, dict] = {
    CH_IBTIKAR:  IBTIKAR_TRANSITIONS,
    CH_GENOCLAB: GENOCLAB_TRANSITIONS,
}


# True terminal state — ARCHIVED cannot transition to anything
TERMINAL_STATES = {"ARCHIVED"}

# Soft-terminal states — no meaningful forward transition without admin override
SOFT_TERMINAL_STATES = {
    IS.COMPLETED,
    IS.REJECTED,
    GS.COMPLETED,
    GS.REJECTED,
    GS.QUOTE_REJECTED_BY_CLIENT,
}

# States that lock the member's load slot (assign)
STATES_THAT_ASSIGN_MEMBER = {
    IS.ASSIGNED,
    GS.ASSIGNED,
}

# States that release the member's load slot unconditionally
STATES_THAT_RELEASE_MEMBER = {
    IS.COMPLETED,
    IS.REJECTED,
    GS.COMPLETED,
    GS.REJECTED,
    GS.QUOTE_REJECTED_BY_CLIENT,
    "ARCHIVED",
}

# Backward transitions that return a request to pre-assignment and release member
BACKWARD_TRANSITIONS_RELEASING_MEMBER = {
    # IBTIKAR — unassign back to sample verification stage
    IS.SAMPLE_VERIFIED,
    # GENOCLAB — unassign back to invoice stage
    GS.INVOICE_GENERATED,
}


# ══════════════════════════════════════════════════════════════════════════════
# TRANSITION REQUIREMENTS
# ══════════════════════════════════════════════════════════════════════════════

TRANSITION_REQUIREMENTS: dict[str, list[str]] = {
    GS.QUOTE_SENT:                ["quote_amount"],
    GS.QUOTE_VALIDATED_BY_CLIENT: [],
    GS.QUOTE_REJECTED_BY_CLIENT:  [],
    GS.INVOICE_GENERATED:         ["quote_amount"],
    IS.ASSIGNED:                  [],      # member resolved by _handle_assigned
    GS.ASSIGNED:                  [],
    IS.APPOINTMENT_SCHEDULED:     [],      # appointment_date in form_data
    IS.SAMPLE_RECEIVED:           [],
    IS.REPORT_UPLOADED:           [],      # report_path checked in UI
    IS.COMPLETED:                 [],
    GS.COMPLETED:                 [],
}


# ── Field path resolver ───────────────────────────────────────────────────────
def _resolve_field(req: dict, path: str) -> Any:
    parts = path.split(".")
    node  = req
    for part in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _check_requirements(req: dict, to_state: str, kwargs: dict) -> None:
    required = TRANSITION_REQUIREMENTS.get(to_state, [])
    for field in required:
        val = kwargs.get(field) or _resolve_field(req, field)
        if val is None or (
            isinstance(val, (str, float, int))
            and str(val).strip() in ("", "0", "0.0")
        ):
            raise MissingTransitionDataError(field, to_state)


# ── Utility ───────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.utcnow().isoformat()


def _append_transition_note(req: dict, note: str) -> None:
    req.setdefault("notes", [])
    if isinstance(req["notes"], list):
        req["notes"].append({"text": note, "timestamp": _now()})


def _build_history_entry(
    from_state: str,
    to_state:   str,
    actor:      dict,
    notes:      str  = "",
    forced:     bool = False,
) -> dict:
    return {
        "id":         str(uuid.uuid4()),
        "from_state": from_state,
        "to_state":   to_state,
        "timestamp":  _now(),
        "actor_id":   actor.get("id",   "system"),
        "actor_role": actor.get("role", "system"),
        "notes":      notes,
        "forced":     forced,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SIDE-EFFECT HANDLERS
# Called AFTER state is saved. Non-critical errors are logged, not raised.
# ══════════════════════════════════════════════════════════════════════════════

def _handle_validated(req: dict, actor: dict, kwargs: dict) -> None:
    """Notify requester/client that their submission passed initial validation."""
    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "✅ Soumission validée",
            message = (
                f"Votre demande `{req['id'][:8]}` a été validée "
                f"et est en cours de traitement."
            ),
            level   = "success",
            user_id = submitter_id,
        )


def _handle_approved(req: dict, actor: dict, kwargs: dict) -> None:
    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "✅ Demande approuvée",
            message = (
                f"Votre demande `{req['id'][:8]}` a été approuvée. "
                f"Un rendez-vous de dépôt d'échantillons sera planifié."
                if req.get("channel") == CH_IBTIKAR
                else f"Votre demande `{req['id'][:8]}` a été approuvée. Un devis vous sera envoyé."
            ),
            level   = "success",
            user_id = submitter_id,
        )


def _handle_rejected(req: dict, actor: dict, kwargs: dict) -> None:
    submitter_id = req.get("submitted_by_user_id")
    reason       = kwargs.get("notes", "")
    if submitter_id:
        create_notification(
            title   = "🚫 Demande rejetée",
            message = (
                f"Votre demande `{req['id'][:8]}` a été rejetée."
                + (f" Motif: {reason}" if reason else "")
            ),
            level   = "error",
            user_id = submitter_id,
        )


def _handle_appointment_scheduled(req: dict, actor: dict, kwargs: dict) -> None:
    """Notify requester that sample drop-off appointment is scheduled."""
    submitter_id = req.get("submitted_by_user_id")
    appt_date    = (
        req.get("appointment_date")
        or req.get("form_data", {}).get("appointment_date", "")
    )
    if submitter_id:
        create_notification(
            title   = "📅 Rendez-vous planifié",
            message = (
                f"Un rendez-vous de dépôt d'échantillons a été planifié "
                f"pour votre demande `{req['id'][:8]}`."
                + (f" Date: {appt_date}" if appt_date else "")
                + " Veuillez vous présenter au laboratoire avec vos échantillons."
            ),
            level   = "info",
            user_id = submitter_id,
        )


def _handle_sample_received(req: dict, actor: dict, kwargs: dict) -> None:
    """Notify platform admin that samples arrived — verification pending."""
    create_notification(
        title   = "📦 Échantillons reçus",
        message = (
            f"Les échantillons pour la demande `{req['id'][:8]}` "
            f"ont été réceptionnés. Procédez à la vérification."
        ),
        level   = "info",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_sample_verified(req: dict, actor: dict, kwargs: dict) -> None:
    """Notify platform admin to proceed to assignment."""
    create_notification(
        title   = "🔍 Échantillons vérifiés",
        message = (
            f"Les échantillons de la demande `{req['id'][:8]}` sont conformes. "
            f"Assignez un analyste pour démarrer les analyses."
        ),
        level   = "success",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_quote_sent(req: dict, actor: dict, kwargs: dict) -> None:
    submitter_id = req.get("submitted_by_user_id")
    amount       = float(req.get("quote_amount", 0))
    vat_rate     = float(getattr(config, "VAT_RATE", 0.19))
    ttc          = round(amount * (1 + vat_rate), 2)
    if submitter_id:
        create_notification(
            title   = "💵 Devis reçu — action requise",
            message = (
                f"Un devis de **{ttc:,.0f} DZD TTC** a été envoyé "
                f"pour votre demande `{req['id'][:8]}`. "
                f"Connectez-vous pour accepter ou refuser."
            ),
            level   = "warning",
            user_id = submitter_id,
        )


def _handle_quote_validated(req: dict, actor: dict, kwargs: dict) -> None:
    create_notification(
        title   = "🤝 Devis accepté par le client",
        message = (
            f"Le client a accepté le devis pour la demande "
            f"`{req['id'][:8]}`. Générez la facture."
        ),
        level   = "success",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_quote_rejected_by_client(req: dict, actor: dict, kwargs: dict) -> None:
    reason = kwargs.get("notes", "")
    create_notification(
        title   = "🚫 Devis refusé par le client",
        message = (
            f"Le client a refusé le devis pour la demande "
            f"`{req['id'][:8]}`."
            + (f" Motif: {reason}" if reason else "")
        ),
        level   = "error",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_invoice_generated(req: dict, actor: dict, kwargs: dict) -> None:
    """Auto-trigger invoice PDF generation via financial_engine."""
    try:
        from core.financial_engine import generate_invoice
        generate_invoice(req, actor=actor)
    except Exception as e:
        _append_transition_note(req, f"⚠️ Erreur génération facture: {e}")

    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "🧾 Facture disponible",
            message = (
                f"La facture pour votre demande `{req['id'][:8]}` "
                f"est disponible dans votre espace client."
            ),
            level   = "success",
            user_id = submitter_id,
        )
    create_notification(
        title   = "🧾 Nouvelle facture à encaisser",
        message = f"Facture générée pour la demande `{req['id'][:8]}`.",
        level   = "info",
        role    = config.ROLE_FINANCE,
    )


def _handle_assigned(req: dict, actor: dict, kwargs: dict) -> None:
    """
    Resolves member (explicit or auto-select), increments load, notifies member.
    Raises MemberUnavailableError / MemberOverloadedError / NoAvailableMemberError
    — these cause the transition to roll back.
    """
    member_id = (
        kwargs.get("assigned_member_id")
        or req.get("assigned_member_id")
    )

    if not member_id:
        candidates = get_available_members_for_service(
            req.get("service_id", "")
        )
        if not candidates:
            raise NoAvailableMemberError(req.get("service_id", "service inconnu"))
        # Prefer lowest load, then highest productivity
        candidates.sort(
            key=lambda m: (
                int(m.get("current_load", 0)),
                -float(m.get("productivity_score", 50)),
            )
        )
        member_id = candidates[0]["id"]

    member = get_member(member_id)
    if not member:
        raise WorkflowError(
            f"Analyste `{member_id}` introuvable.", "MEMBER_NOT_FOUND"
        )
    if not member.get("available", True):
        raise MemberUnavailableError(member.get("name", member_id))
    if int(member.get("current_load", 0)) >= int(
        member.get("max_load", config.DEFAULT_MEMBER_MAX_LOAD)
    ):
        raise MemberOverloadedError(member.get("name", member_id))

    req["assigned_member_id"]   = member_id
    req["assigned_member_name"] = member.get("name", "–")
    increment_member_load(member_id)

    member_user_id = member.get("user_id")
    if member_user_id:
        create_notification(
            title   = "🧬 Nouvelle demande assignée",
            message = (
                f"La demande `{req['id'][:8]}` vous a été assignée. "
                f"Vous devez accepter la mission pour démarrer l'analyse."
            ),
            level   = "info",
            user_id = member_user_id,
        )


def _handle_unassigned(req: dict, actor: dict, kwargs: dict) -> None:
    """Releases member load when a request is sent back to a pre-assignment state."""
    member_id = req.get("assigned_member_id")
    if member_id:
        decrement_member_load(member_id)
    # Clear assignment fields
    req["assigned_member_id"]   = None
    req["assigned_member_name"] = None


def _handle_pending_acceptance(req: dict, actor: dict, kwargs: dict) -> None:
    """Re-notify the member they must explicitly accept the mission."""
    member_id = req.get("assigned_member_id")
    if not member_id:
        return
    member = get_member(member_id)
    if not member:
        return
    member_user_id = member.get("user_id")
    if member_user_id:
        create_notification(
            title   = "⚡ Acceptation requise",
            message = (
                f"La demande `{req['id'][:8]}` vous a été assignée. "
                f"Veuillez accepter ou refuser cette mission."
            ),
            level   = "warning",
            user_id = member_user_id,
        )


def _handle_in_progress(req: dict, actor: dict, kwargs: dict) -> None:
    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "🔬 Analyse démarrée",
            message = (
                f"L'analyse de votre demande `{req['id'][:8]}` "
                f"a démarré. Vous serez notifié à la fin."
            ),
            level   = "info",
            user_id = submitter_id,
        )


def _handle_analysis_finished(req: dict, actor: dict, kwargs: dict) -> None:
    create_notification(
        title   = "✅ Analyse terminée",
        message = (
            f"L'analyse de la demande `{req['id'][:8]}` est terminée. "
            f"Veuillez uploader le rapport d'analyse."
        ),
        level   = "success",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_report_uploaded(req: dict, actor: dict, kwargs: dict) -> None:
    create_notification(
        title   = "🔎 Rapport soumis — révision requise",
        message = (
            f"Le rapport de la demande `{req['id'][:8]}` "
            f"est en attente de révision administrative."
        ),
        level   = "info",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_admin_review(req: dict, actor: dict, kwargs: dict) -> None:
    """No-op notification — admin is already reviewing."""
    pass


def _handle_report_validated(req: dict, actor: dict, kwargs: dict) -> None:
    """Notify admin to transmit the validated report."""
    create_notification(
        title   = "📋 Rapport validé — transmission requise",
        message = (
            f"Le rapport de la demande `{req['id'][:8]}` a été validé. "
            f"Transmettez-le au requérant / client."
        ),
        level   = "success",
        role    = config.ROLE_PLATFORM_ADMIN,
    )


def _handle_sent_to_requester(req: dict, actor: dict, kwargs: dict) -> None:
    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "📬 Rapport disponible",
            message = (
                f"Le rapport d'analyse de votre demande `{req['id'][:8]}` "
                f"vous a été transmis. Connectez-vous pour le télécharger."
            ),
            level   = "success",
            user_id = submitter_id,
        )


def _handle_sent_to_client(req: dict, actor: dict, kwargs: dict) -> None:
    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "📬 Rapport et résultats disponibles",
            message = (
                f"Le rapport d'analyse de votre demande `{req['id'][:8]}` "
                f"est disponible dans votre espace client."
            ),
            level   = "success",
            user_id = submitter_id,
        )


def _handle_completed(req: dict, actor: dict, kwargs: dict) -> None:
    """
    Release member load.
    Trigger productivity recalculation.
    Final notification.
    """
    member_id = req.get("assigned_member_id")
    if member_id:
        decrement_member_load(member_id)
        try:
            from core.productivity_engine import recalculate_member
            recalculate_member(member_id, user=actor, silent=False)
        except Exception:
            pass

    submitter_id = req.get("submitted_by_user_id")
    if submitter_id:
        create_notification(
            title   = "🏁 Demande clôturée",
            message = (
                f"Votre demande `{req['id'][:8]}` a été clôturée avec succès. "
                f"Merci de votre confiance."
            ),
            level   = "success",
            user_id = submitter_id,
        )


def _handle_archived(req: dict, actor: dict, kwargs: dict) -> None:
    """Move request from active to archived pool."""
    archive_request(req["id"])


# ── Side-effect dispatch table ────────────────────────────────────────────────
SIDE_EFFECTS: dict[str, Any] = {
    # Shared / IBTIKAR
    IS.VALIDATED:             _handle_validated,
    IS.APPROVED:              _handle_approved,
    IS.REJECTED:              _handle_rejected,
    IS.APPOINTMENT_SCHEDULED: _handle_appointment_scheduled,
    IS.SAMPLE_RECEIVED:       _handle_sample_received,
    IS.SAMPLE_VERIFIED:       _handle_sample_verified,
    IS.ASSIGNED:              _handle_assigned,
    IS.PENDING_ACCEPTANCE:    _handle_pending_acceptance,
    IS.IN_PROGRESS:           _handle_in_progress,
    IS.ANALYSIS_FINISHED:     _handle_analysis_finished,
    IS.REPORT_UPLOADED:       _handle_report_uploaded,
    IS.ADMIN_REVIEW:          _handle_admin_review,
    IS.REPORT_VALIDATED:      _handle_report_validated,
    IS.SENT_TO_REQUESTER:     _handle_sent_to_requester,
    IS.COMPLETED:             _handle_completed,
    # GENOCLAB-specific (shares most handlers via same string values)
    GS.VALIDATED:             _handle_validated,
    GS.QUOTE_SENT:            _handle_quote_sent,
    GS.QUOTE_VALIDATED_BY_CLIENT:  _handle_quote_validated,
    GS.QUOTE_REJECTED_BY_CLIENT:   _handle_quote_rejected_by_client,
    GS.INVOICE_GENERATED:     _handle_invoice_generated,
    GS.SENT_TO_CLIENT:        _handle_sent_to_client,
    # Shared strings (same value in both IS and GS)
    "ARCHIVED":               _handle_archived,
}


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def transition(
    request_id: str,
    to_state:   str,
    actor:      dict,
    notes:      str  = "",
    forced:     bool = False,
    **kwargs,
) -> dict:
    """
    Executes a workflow state transition.

    Args:
        request_id: The request to transition.
        to_state:   Target state string (use config.IbtikarState / GenoClabState).
        actor:      User dict performing the action (must have id + role).
        notes:      Optional free-text note recorded in history.
        forced:     If True, bypasses the transition graph (super_admin only).
        **kwargs:   Runtime data (e.g. assigned_member_id, quote_amount).

    Returns:
        The updated request dict.

    Raises:
        RequestNotFoundError       — request_id not found.
        InvalidTransitionError     — transition not in allowed graph.
        MissingTransitionDataError — required field missing.
        WorkflowError              — any other workflow error.
    """
    # ── 1. Load request ───────────────────────────────────────────────────────
    req = get_request(request_id)
    if not req:
        raise RequestNotFoundError(request_id)

    channel    = req.get("channel", "")
    from_state = req.get("status", "")

    # ── 2. Validate transition ────────────────────────────────────────────────
    if not forced:
        if from_state in TERMINAL_STATES:
            raise InvalidTransitionError(
                from_state, to_state,
                "La demande est archivée (état terminal)."
            )

        graph   = TRANSITION_GRAPHS.get(channel, {})
        allowed = graph.get(from_state, set())

        # Soft-terminal: only super_admin can escape without forced flag
        if (
            from_state in SOFT_TERMINAL_STATES
            and to_state != "ARCHIVED"
            and actor.get("role") != config.ROLE_SUPER_ADMIN
        ):
            raise InvalidTransitionError(
                from_state, to_state,
                f"`{from_state}` est un état terminal. "
                f"Seul le super admin peut forcer une transition."
            )

        if to_state not in allowed:
            raise InvalidTransitionError(
                from_state, to_state,
                f"Transitions autorisées depuis `{from_state}`: "
                f"{sorted(allowed) or 'aucune'}",
            )

    # ── 3. Merge kwargs into request for requirement checks ───────────────────
    for key, val in kwargs.items():
        if val is not None:
            req[key] = val

    # ── 4. Check requirements ─────────────────────────────────────────────────
    if not forced:
        _check_requirements(req, to_state, kwargs)

    # ── 5. Handle backward transitions releasing member ───────────────────────
    if (
        from_state in {IS.ASSIGNED, GS.ASSIGNED,
                       IS.PENDING_ACCEPTANCE, GS.PENDING_ACCEPTANCE}
        and to_state in BACKWARD_TRANSITIONS_RELEASING_MEMBER
    ):
        _handle_unassigned(req, actor, kwargs)

    # ── 6. Update request state ───────────────────────────────────────────────
    prev_state        = from_state
    req["status"]     = to_state
    req["updated_at"] = _now()
    req.setdefault("status_history", []).append(
        _build_history_entry(prev_state, to_state, actor, notes, forced)
    )

    # ── 7. Save BEFORE side effects ───────────────────────────────────────────
    if to_state != "ARCHIVED":
        save_request(req)

    # ── 8. Execute side effects ───────────────────────────────────────────────
    side_effect = SIDE_EFFECTS.get(to_state)
    if side_effect:
        try:
            side_effect(req, actor, kwargs)
        except (
            NoAvailableMemberError,
            MemberUnavailableError,
            MemberOverloadedError,
        ):
            # Recoverable — roll back state and re-raise
            req["status"]     = prev_state
            req["updated_at"] = _now()
            req["status_history"].pop()
            # Restore cleared assignment fields if unassign ran
            if "assigned_member_id" in kwargs:
                req["assigned_member_id"]   = kwargs.get("assigned_member_id")
            save_request(req)
            raise
        except Exception as e:
            # Non-critical — log and continue
            _append_transition_note(req, f"⚠️ Effet secondaire: {e}")
            save_request(req)

    # ── 9. Audit log ──────────────────────────────────────────────────────────
    try:
        from core.audit_engine import log_transition
        log_transition(
            request_id = request_id,
            from_state = prev_state,
            to_state   = to_state,
            actor      = actor,
            channel    = channel,
            notes      = notes,
            forced     = forced,
        )
    except Exception:
        pass

    return req


# ── Read-only helpers ─────────────────────────────────────────────────────────

def can_transition(request_id: str, to_state: str) -> bool:
    """
    Returns True if the transition is allowed.
    Safe to call for UI button visibility — no side effects.
    """
    req = get_request(request_id)
    if not req:
        return False
    from_state = req.get("status", "")
    if from_state in TERMINAL_STATES:
        return False
    graph   = TRANSITION_GRAPHS.get(req.get("channel", ""), {})
    allowed = graph.get(from_state, set())
    return to_state in allowed


def get_allowed_transitions(request_id: str) -> list[str]:
    """
    Returns sorted list of allowed next states.
    Returns [] for terminal or not-found requests.
    """
    req = get_request(request_id)
    if not req:
        return []
    from_state = req.get("status", "")
    if from_state in TERMINAL_STATES:
        return []
    graph = TRANSITION_GRAPHS.get(req.get("channel", ""), {})
    return sorted(graph.get(from_state, set()))


def get_pipeline_position(request_id: str) -> dict:
    """
    Returns pipeline progress info for a request.

    Returns:
        {
            channel, status, step, total, pct,
            pipeline_states, is_terminal, label, icon, colour
        }
    """
    req = get_request(request_id)
    if not req:
        return {}

    channel = req.get("channel", "")
    status  = req.get("status",  "")

    if channel == CH_GENOCLAB:
        pipeline = [
            GS.SUBMITTED,
            GS.VALIDATED,
            GS.QUOTE_DRAFT,
            GS.QUOTE_SENT,
            GS.QUOTE_VALIDATED_BY_CLIENT,
            GS.INVOICE_GENERATED,
            GS.ASSIGNED,
            GS.PENDING_ACCEPTANCE,
            GS.IN_PROGRESS,
            GS.ANALYSIS_FINISHED,
            GS.REPORT_UPLOADED,
            GS.ADMIN_REVIEW,
            GS.REPORT_VALIDATED,
            GS.SENT_TO_CLIENT,
            GS.COMPLETED,
        ]
    else:
        pipeline = [
            IS.SUBMITTED,
            IS.VALIDATED,
            IS.APPROVED,
            IS.APPOINTMENT_SCHEDULED,
            IS.SAMPLE_RECEIVED,
            IS.SAMPLE_VERIFIED,
            IS.ASSIGNED,
            IS.PENDING_ACCEPTANCE,
            IS.IN_PROGRESS,
            IS.ANALYSIS_FINISHED,
            IS.REPORT_UPLOADED,
            IS.ADMIN_REVIEW,
            IS.REPORT_VALIDATED,
            IS.SENT_TO_REQUESTER,
            IS.COMPLETED,
        ]

    step  = pipeline.index(status) + 1 if status in pipeline else 0
    total = len(pipeline)

    # Label and colour from config
    status_meta = config.STATUS_LABELS.get(status, ("📋", status, "#7F8C8D"))

    return {
        "channel":         channel,
        "status":          status,
        "step":            step,
        "total":           total,
        "pct":             round(step / total * 100, 1) if total else 0.0,
        "pipeline_states": pipeline,
        "is_terminal":     status in TERMINAL_STATES | SOFT_TERMINAL_STATES,
        "icon":            status_meta[0],
        "label":           status_meta[1],
        "colour":          status_meta[2],
    }


def bulk_archive(
    request_ids: list[str],
    actor:       dict,
) -> dict[str, Any]:
    """
    Archives requests that are in a completed or rejected state.

    Returns:
        { "archived": [ids], "skipped": [ids], "errors": {id: msg} }
    """
    archivable = {
        IS.COMPLETED,
        IS.REJECTED,
        GS.COMPLETED,
        GS.REJECTED,
        GS.QUOTE_REJECTED_BY_CLIENT,
    }

    archived: list = []
    skipped:  list = []
    errors:   dict = {}

    for rid in request_ids:
        try:
            req = get_request(rid)
            if not req:
                errors[rid] = "Introuvable"
                continue
            if req.get("status") not in archivable:
                skipped.append(rid)
                continue
            transition(rid, "ARCHIVED", actor, forced=True)
            archived.append(rid)
        except Exception as e:
            errors[rid] = str(e)

    # Audit
    try:
        from core.audit_engine import log_system_event
        log_system_event(
            event   = "BULK_ARCHIVE",
            actor   = actor,
            details = (
                f"Archivage en masse: {len(archived)} archivées, "
                f"{len(skipped)} ignorées, {len(errors)} erreurs."
            ),
        )
    except Exception:
        pass

    return {"archived": archived, "skipped": skipped, "errors": errors}


def reject_request(
    request_id: str,
    actor:      dict,
    reason:     str = "",
) -> dict:
    """
    Convenience wrapper to reject a request from any pre-assignment state.
    Only valid from: SUBMITTED, VALIDATED, APPROVED (both channels).
    """
    return transition(
        request_id,
        IS.REJECTED,    # same string as GS.REJECTED
        actor,
        notes  = reason,
        forced = False,
    )