# ui/platform_admin_dashboard.py
# ── PLAGENOR 4.0 — Platform Admin Dashboard ──────────────────────────────────
# Serves  : ROLE_PLATFORM_ADMIN
# Manages : Request queue, validation, assignment, appointments,
#            analysis tracking, report generation, GENOCLAB quotes, KPI board.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime
from typing import Optional                          # BUG-FIX P-03

import config
from ui.auth import require_roles
from ui.shared_components import (
    render_sidebar_user,
    render_request_card,
    render_status_badge,
    kpi_row,
    confirm_action,
    resolve_username,
    resolve_service_name,
    render_empty_state,
    render_workflow_progress,
)
from core.repository import (
    get_all_active_requests,
    get_all_archived_requests,
    get_all_members,
    get_all_services,
    get_all_invoices,
    get_all_audit_logs,
    save_request,
)
from core.workflow_engine   import transition
from core.assignment_engine import rank_candidates, assign_best_member
from core.productivity_engine import (
    get_productivity_ranking,
    recalculate_all,
    recalculate_member,
)
from core.financial_engine import set_quote_amount
from services.document_service  import generate_report_docx, generate_invoice_pdf
from core.exceptions            import PlagenorError


# ── Channel aliases ───────────────────────────────────────────────────────────
CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB


# ── Workflow state references ─────────────────────────────────────────────────
class IbtikarState:
    SUBMITTED            = "SUBMITTED"
    VALIDATION           = "VALIDATION"
    APPROVED             = "APPROVED"
    REJECTED             = "REJECTED"
    ASSIGNED             = "ASSIGNED"
    ANALYSIS_IN_PROGRESS = "ANALYSIS_IN_PROGRESS"
    ANALYSIS_FINISHED    = "ANALYSIS_FINISHED"
    REPORT_UPLOADED      = "REPORT_UPLOADED"
    COMPLETED            = "COMPLETED"


class GenoClabState:
    SUBMITTED                 = "SUBMITTED"
    VALIDATION                = "VALIDATION"
    APPROVED                  = "APPROVED"
    REJECTED                  = "REJECTED"
    QUOTE_DRAFT               = "QUOTE_DRAFT"
    QUOTE_SENT                = "QUOTE_SENT"
    QUOTE_VALIDATED_BY_CLIENT = "QUOTE_VALIDATED_BY_CLIENT"
    QUOTE_REJECTED_BY_CLIENT  = "QUOTE_REJECTED_BY_CLIENT"
    INVOICE_GENERATED         = "INVOICE_GENERATED"
    ASSIGNED                  = "ASSIGNED"
    ANALYSIS_IN_PROGRESS      = "ANALYSIS_IN_PROGRESS"
    ANALYSIS_FINISHED         = "ANALYSIS_FINISHED"
    REPORT_UPLOADED           = "REPORT_UPLOADED"
    COMPLETED                 = "COMPLETED"


# ── Module-level constants ────────────────────────────────────────────────────
# BUG-FIX P-01: was defined inside _tab_assignment only — not visible elsewhere.
PRODUCTIVITY_EMOJI_MAP = {
    "EXCELLENT": "🟢",
    "GOOD":      "🔵",
    "NORMAL":    "🟡",
    "LOW":       "🔴",
}


# ── Utility helpers (defined early — used by ALL _tab_* functions) ────────────
# BUG-FIX YELLOW-1: moved from bottom of file.
# BUG-FIX RED-2   : datetime imported inline to avoid NameError.
def _days_since(iso_date: str) -> int:
    """Returns calendar days elapsed since an ISO datetime string."""
    if not iso_date:
        return 0
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return max((datetime.utcnow() - dt.replace(tzinfo=None)).days, 0)
    except Exception:
        return 0


# BUG-FIX YELLOW-2: moved from after _tab_quotes — now visible to all tabs.
def _advance_request(
    req:   dict,
    to:    str,
    actor: dict,
    notes: str = "",
) -> None:
    """Transitions a request to a new state and calls st.rerun(). Never raises."""
    try:
        transition(request_id=req["id"], to_state=to, actor=actor, notes=notes)
        st.success(f"✅ Demande avancée → `{to}`")
        st.cache_data.clear()
        st.rerun()
    except PlagenorError as e:
        st.error(f"❌ {e}")


def _action_ok(msg: str) -> None:
    st.success(f"✅ {msg}")


def _action_err(e: Exception) -> None:
    st.error(f"❌ {e}")


# ── Data loaders (cached per rerun) ───────────────────────────────────────────
@st.cache_data(ttl=10)
def _load_active_requests() -> list:
    return get_all_active_requests()


@st.cache_data(ttl=10)
def _load_all_requests() -> list:
    return get_all_active_requests() + get_all_archived_requests()


@st.cache_data(ttl=10)
def _load_members() -> list:
    return get_all_members()


@st.cache_data(ttl=10)
def _load_invoices() -> list:
    return get_all_invoices()


# ── Filter helpers ────────────────────────────────────────────────────────────
def _by_status(requests: list, *statuses: str) -> list:
    return [r for r in requests if r.get("status") in statuses]


def _by_channel(requests: list, channel: str) -> list:
    return [r for r in requests if r.get("channel") == channel]


# ── Request selector widget ───────────────────────────────────────────────────
def _request_selector(requests: list, key: str) -> Optional[dict]:
    if not requests:
        return None
    opts = {
        f"[{r.get('channel','?')}] {r['id'][:8]} — "
        f"{resolve_service_name(r.get('service_id',''))} "
        f"({r.get('status', '')})" : r
        for r in requests
    }
    sel = st.selectbox("Sélectionner une demande", list(opts.keys()), key=key)
    return opts[sel]


# ── Tab: Queue ────────────────────────────────────────────────────────────────
def _tab_queue(actor: dict) -> None:
    st.markdown("## 📋 File d'attente — Toutes les demandes actives")

    requests = _load_active_requests()
    if not requests:
        render_empty_state("📭", "Aucune demande active", "La file est vide.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        ch_filter = st.selectbox(
            "Canal", ["Tous", CHANNEL_IBTIKAR, CHANNEL_GENOCLAB], key="q_ch"
        )
    with col2:
        all_statuses = sorted({r.get("status", "") for r in requests})
        st_filter = st.selectbox("Statut", ["Tous"] + all_statuses, key="q_st")
    with col3:
        sort_by = st.selectbox(
            "Trier par",
            ["Date (récent)", "Date (ancien)", "Statut"],
            key="q_sort",
        )

    filtered = requests
    if ch_filter != "Tous":
        filtered = _by_channel(filtered, ch_filter)
    if st_filter != "Tous":
        filtered = _by_status(filtered, st_filter)

    if sort_by == "Date (récent)":
        filtered = sorted(filtered, key=lambda r: r.get("created_at", ""), reverse=True)
    elif sort_by == "Date (ancien)":
        filtered = sorted(filtered, key=lambda r: r.get("created_at", ""))
    else:
        filtered = sorted(filtered, key=lambda r: r.get("status", ""))

    st.caption(f"Affichage: **{len(filtered)}** / {len(requests)} demandes")
    st.divider()

    for req in filtered:
        # BUG-FIX YELLOW-1: _days_since now defined above — no forward ref warning
        days_waiting = _days_since(req.get("created_at", ""))
        age_color    = "🔴" if days_waiting > 7 else ("🟡" if days_waiting > 3 else "🟢")
        render_request_card(req)
        st.caption(f"{age_color} En attente depuis: **{days_waiting} jour(s)**")
        st.divider()


# ── Tab: Validation ───────────────────────────────────────────────────────────
def _tab_validation(actor: dict) -> None:
    st.markdown("## ✅ Validation des nouvelles demandes")

    requests    = _load_active_requests()
    to_validate = _by_status(requests, "SUBMITTED", "VALIDATION")

    if not to_validate:
        render_empty_state(
            "✅", "Aucune demande à valider",
            "Toutes les soumissions ont été traitées.",
        )
        return

    req = _request_selector(to_validate, "val_selector")
    if not req:
        return

    render_request_card(req)
    render_workflow_progress(req.get("channel", ""), req.get("status", ""))
    st.divider()
    _render_validate_reject_panel(req, actor)


def _render_validate_reject_panel(req: dict, actor: dict) -> None:
    channel   = req.get("channel", "")
    form_data = req.get("form_data", {})
    requester = form_data.get("requester", {})

    st.markdown("### 🔍 Évaluation de la demande")
    st.markdown(
        f"**Demandeur:** {requester.get('full_name', '–')}  \n"
        f"**Institution:** {requester.get('institution', '–')}  \n"
        f"**Email:** {requester.get('email', '–')}  \n"
        f"**Service:** {resolve_service_name(req.get('service_id', ''))}"
    )

    if channel == CHANNEL_IBTIKAR:
        budget = form_data.get("budget", {})
        st.markdown(
            f"**Budget demandé:** {float(budget.get('requested', 0)):,.0f} DZD  \n"
            f"**Justification:** {budget.get('justification', '–')}"
        )

    st.divider()
    _render_approve_panel(req, actor)

    st.divider()
    st.markdown("### 🚫 Rejeter la demande")
    reject_reason = st.text_area(
        "Motif de rejet *",
        key         = f"reject_reason_{req['id']}",
        height      = 80,
        placeholder = "Expliquez pourquoi la demande est rejetée.",
    )
    if confirm_action(
        key     = f"reject_{req['id']}",
        label   = "🚫 Rejeter",
        message = f"Confirmer le rejet de la demande `{req['id'][:8]}` ?",
        danger  = True,
    ):
        if not reject_reason.strip():
            st.warning("⚠️ Le motif de rejet est obligatoire.")
        else:
            _advance_request(req, "REJECTED", actor, notes=reject_reason)


def _render_approve_panel(req: dict, actor: dict) -> None:
    channel   = req.get("channel", "")
    form_data = req.get("form_data", {})

    st.markdown("### ✅ Approuver la demande")
    approval_note = st.text_input(
        "Note d'approbation (optionnelle)",
        key         = f"appr_note_{req['id']}",
        placeholder = "Ex: Conforme aux critères du programme.",
    )

    if channel == CHANNEL_IBTIKAR:
        budget    = form_data.get("budget", {})
        cap       = float(getattr(config, "IBTIKAR_BUDGET_CAP", 150_000))
        requested = float(budget.get("requested", 0))
        justification = ""

        if requested > cap:
            st.warning(
                f"⚠️ Budget ({requested:,.0f} DZD) dépasse le plafond "
                f"({cap:,.0f} DZD). Justification obligatoire."
            )
            justification = st.text_area(
                "Justification de dépassement *",
                key = f"just_{req['id']}",
            )

        if confirm_action(
            key     = f"approve_{req['id']}",
            label   = "✅ Approuver",
            message = f"Approuver la demande `{req['id'][:8]}` ?",
        ):
            if requested > cap and not justification.strip():
                st.warning("⚠️ Justification requise pour dépasser le plafond.")
            else:
                _advance_request(
                    req, "APPROVED", actor,
                    notes=justification or approval_note,
                )
    else:
        # GENOCLAB: APPROVED auto-chains → QUOTE_DRAFT via workflow_engine
        if confirm_action(
            key     = f"approve_{req['id']}",
            label   = "✅ Approuver",
            message = (
                f"Approuver la demande GENOCLAB `{req['id'][:8]}` ?  \n"
                f"Un QUOTE_DRAFT sera créé automatiquement."
            ),
        ):
            _advance_request(req, "APPROVED", actor, notes=approval_note)


# ── Tab: Assignment ───────────────────────────────────────────────────────────
def _tab_assignment(actor: dict) -> None:
    st.markdown("## 🧬 Assignation des demandes approuvées")

    requests   = _load_active_requests()
    # IBTIKAR:  APPROVED → ASSIGNED
    # GENOCLAB: INVOICE_GENERATED → ASSIGNED
    assignable = _by_status(requests, "APPROVED", "INVOICE_GENERATED")

    if not assignable:
        render_empty_state(
            "🧬", "Aucune demande à assigner",
            "En attente d'approbations ou de factures validées.",
        )
        return

    req = _request_selector(assignable, "assign_selector")
    if not req:
        return

    render_request_card(req)
    render_workflow_progress(req.get("channel", ""), req.get("status", ""))
    st.divider()

    st.markdown("### 🤖 Classement automatique des membres")
    try:
        candidates, excluded = rank_candidates(req)
    except Exception as e:
        st.error(f"Erreur lors du classement: {e}")
        return

    if not candidates:
        st.warning("⚠️ Aucun membre disponible pour ce service.")
        if excluded:
            with st.expander("Membres exclus"):
                for ex in excluded:
                    st.write(f"🔴 **{ex.get('member_name')}** — {ex.get('reason', '–')}")
        return

    st.success(f"✅ {len(candidates)} candidat(s) disponible(s)")

    for i, cand in enumerate(candidates[:5]):
        medal = ["🥇", "🥈", "🥉"]
        prefix = medal[i] if i < 3 else f"**{i+1}.**"
        st.markdown(
            f"{prefix} **{cand.get('member_name')}** | "
            f"Score: `{cand.get('final_score', 0):.1f}` | "
            f"Charge: `{cand.get('current_load', 0)}/{cand.get('max_load', 0)}` | "
            f"Productivité: `{cand.get('productivity_score', 0):.1f}`"
        )

    if excluded:
        with st.expander(f"Membres exclus ({len(excluded)})"):
            for ex in excluded:
                st.write(f"🔴 **{ex.get('member_name')}** — {ex.get('reason', '–')}")

    st.divider()
    best = candidates[0]
    st.info(
        f"🤖 Recommandation: **{best.get('member_name')}** "
        f"(score: {best.get('final_score', 0):.1f})"
    )
    _do_assign(req, actor)


def _do_assign(req: dict, actor: dict) -> None:
    # BUG-FIX P-03: Optional imported at top — no NameError here
    if st.button(
        "▶ Assigner le meilleur candidat et avancer",
        key                 = f"do_assign_{req['id']}",
        type                = "primary",
        use_container_width = True,
    ):
        with st.spinner("Assignation en cours..."):
            try:
                assign_best_member(req["id"], actor)
                st.success("✅ Analyste assigné — demande avancée vers ASSIGNED.")
                st.cache_data.clear()
                st.rerun()
            except PlagenorError as e:
                st.error(f"❌ {e}")


# ── Tab: Appointments ─────────────────────────────────────────────────────────
def _tab_appointments(actor: dict) -> None:
    st.markdown("## 📅 Rendez-vous et réception des échantillons")

    requests    = _load_active_requests()
    appointment = _by_status(requests, "ASSIGNED")

    if not appointment:
        render_empty_state(
            "📅", "Aucun rendez-vous en attente",
            "Toutes les demandes assignées ont été traitées.",
        )
        return

    req = _request_selector(appointment, "appt_selector")
    if not req:
        return

    render_request_card(req)
    st.divider()

    appt_info = req.get("appointment", {})
    if appt_info:
        st.markdown(
            f"**📅 RDV planifié:** {appt_info.get('date', '–')} "
            f"à {appt_info.get('time', '–')}  \n"
            f"**📝 Note:** {appt_info.get('note', '–')}"
        )
        st.divider()

    st.markdown("### 📅 Planifier / Modifier un rendez-vous")
    with st.form(f"appt_form_{req['id']}"):
        appt_date = st.date_input("Date du rendez-vous", key=f"appt_d_{req['id']}")
        appt_time = st.time_input("Heure",               key=f"appt_t_{req['id']}")
        appt_note = st.text_area(
            "Instructions / Note",
            key         = f"appt_n_{req['id']}",
            placeholder = "Ex: Apporter les souches en tube Eppendorf.",
        )
        if st.form_submit_button("💾 Enregistrer le rendez-vous", use_container_width=True):
            from core.repository import get_request, save_request as _save_req
            r = get_request(req["id"])
            if r:
                r["appointment"] = {
                    "date": str(appt_date),
                    "time": str(appt_time),
                    "note": appt_note,
                }
                _save_req(r)
                st.success("✅ Rendez-vous enregistré.")
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.markdown("### ✅ Confirmer la réception des échantillons")
    reception_note = st.text_input(
        "Note de réception",
        key         = f"rec_note_{req['id']}",
        placeholder = "Ex: 6 souches reçues, conditions correctes.",
    )
    if confirm_action(
        key     = f"receive_{req['id']}",
        label   = "✅ Confirmer réception → ANALYSIS_IN_PROGRESS",
        message = f"Confirmer la réception des échantillons pour `{req['id'][:8]}` ?",
    ):
        _advance_request(req, "ANALYSIS_IN_PROGRESS", actor, notes=reception_note)


# ── Tab: Analysis ─────────────────────────────────────────────────────────────
def _tab_analysis(actor: dict) -> None:
    st.markdown("## 🔬 Suivi des analyses en cours")

    requests    = _load_active_requests()
    in_analysis = _by_status(requests, "ANALYSIS_IN_PROGRESS")

    if not in_analysis:
        render_empty_state(
            "🔬", "Aucune analyse en cours",
            "En attente d'échantillons reçus.",
        )
        return

    req = _request_selector(in_analysis, "analysis_selector")
    if not req:
        return

    render_request_card(req)
    render_workflow_progress(req.get("channel", ""), req.get("status", ""))
    st.divider()

    # BUG-FIX RED-1: l'analyste — apostrophe extracted to variable, not inside f-string
    _analyst_name = req.get("assigned_member_name") or "l'analyste assigné"
    _service_name = resolve_service_name(req.get("service_id", ""))
    days_waiting  = _days_since(req.get("created_at", ""))

    st.info(
        f"🔬 **Service:** {_service_name}  \n"
        f"📌 **Analyste:** {_analyst_name}  \n"
        f"📅 **Soumise il y a:** {days_waiting} jour(s)"
    )

    tasks = req.get("tasks", [])
    if tasks:
        st.markdown("### 📋 Tâches associées")
        for task in tasks:
            icon = "✅" if task.get("done") else "🔲"
            st.write(
                f"{icon} **{task.get('title', '–')}** "
                f"— Assigné à: `{task.get('assigned_to_name', '–')}`"
            )

    st.divider()
    st.markdown("### ✅ Marquer l'analyse comme terminée")
    completion_note = st.text_area(
        "Note de fin d'analyse",
        key         = f"fin_note_{req['id']}",
        height      = 80,
        placeholder = "Ex: Séquençage terminé, données exportées.",
    )
    if confirm_action(
        key     = f"finish_analysis_{req['id']}",
        label   = "✅ Analyse terminée → ANALYSIS_FINISHED",
        message = f"Confirmer la fin de l'analyse pour `{req['id'][:8]}` ?",
    ):
        _advance_request(req, "ANALYSIS_FINISHED", actor, notes=completion_note)


# ── Tab: Reports ──────────────────────────────────────────────────────────────
def _tab_reports(actor: dict) -> None:
    st.markdown("## 📄 Génération et dépôt des rapports")

    requests = _load_active_requests()
    finished = _by_status(requests, "ANALYSIS_FINISHED")

    if not finished:
        render_empty_state(
            "📄", "Aucun rapport à générer",
            "En attente d'analyses terminées.",
        )
        return

    req = _request_selector(finished, "report_selector")
    if not req:
        return

    render_request_card(req)
    render_workflow_progress(req.get("channel", ""), req.get("status", ""))
    st.divider()

    # BUG-FIX RED-1: same apostrophe fix applied here
    _analyst_name = req.get("assigned_member_name") or "l'analyste assigné"
    _service_name = resolve_service_name(req.get("service_id", ""))

    st.info(
        f"📋 Rapport à générer pour: **{_service_name}**  \n"
        f"📌 **Analyste:** {_analyst_name}  \n"
        f"📅 **Soumise il y a:** {_days_since(req.get('created_at', ''))} jour(s)"
    )

    st.markdown("### 📄 Générer le rapport DOCX")
    st.caption(
        "Le rapport est généré à partir des données de la demande "
        "et des résultats d'analyse."
    )

    if st.button(
        "📄 Générer le rapport DOCX → REPORT_UPLOADED",
        key                 = f"gen_report_{req['id']}",
        type                = "primary",
        use_container_width = True,
    ):
        with st.spinner("Génération du rapport..."):
            try:
                generate_report_docx(req, actor)
                _advance_request(req, "REPORT_UPLOADED", actor)
            except PlagenorError as e:
                _action_err(e)

    # Clôture: REPORT_UPLOADED → COMPLETED
    reported = _by_status(requests, "REPORT_UPLOADED")
    if reported:
        st.divider()
        st.markdown("### 📦 Rapports déposés — Clôturer la demande")
        rep_req = _request_selector(reported, "complete_selector")
        if rep_req:
            render_request_card(rep_req)
            if confirm_action(
                key     = f"complete_{rep_req['id']}",
                label   = "✅ Clôturer → COMPLETED",
                message = f"Marquer `{rep_req['id'][:8]}` comme COMPLETED ?",
            ):
                _advance_request(rep_req, "COMPLETED", actor)


# ── Tab: Quotes ───────────────────────────────────────────────────────────────
def _tab_quotes(actor: dict) -> None:
    st.markdown("## 💵 Gestion des Devis — GENOCLAB")

    requests = _load_active_requests()
    quotable = _by_channel(
        _by_status(
            requests,
            GenoClabState.QUOTE_DRAFT,
            GenoClabState.QUOTE_SENT,
            GenoClabState.QUOTE_VALIDATED_BY_CLIENT,   # edge-case only
        ),
        CHANNEL_GENOCLAB,
    )

    if not quotable:
        render_empty_state(
            "💵", "Aucun devis en cours",
            "Les demandes GENOCLAB APPROVED créent automatiquement un QUOTE_DRAFT.",
        )
        return

    req = _request_selector(quotable, "quote_selector")
    if not req:
        return

    status = req.get("status", "")
    render_workflow_progress(CHANNEL_GENOCLAB, status)

    requester = req.get("form_data", {}).get("requester", {})
    st.markdown(
        f"**Client:** {requester.get('full_name', '–')}  \n"
        f"**Email:** {requester.get('email', '–')}"
    )
    st.divider()

    # ── QUOTE_DRAFT ───────────────────────────────────────────────────────────
    if status == GenoClabState.QUOTE_DRAFT:
        st.markdown("### 💵 Définir et envoyer le devis")

        pricing    = req.get("form_data", {}).get("pricing", {})
        suggested  = float(pricing.get("subtotal", 0))
        vat_rate   = float(getattr(config, "VAT_RATE", 0.19))
        vat_amount = round(suggested * vat_rate, 2)
        ttc        = round(suggested + vat_amount, 2)

        if suggested > 0:
            st.info(
                f"💡 Montant estimé: **{suggested:,.0f} DZD HT** "
                f"(TVA {vat_rate * 100:.0f}%: {vat_amount:,.0f} DZD → "
                f"**{ttc:,.0f} DZD TTC**)"
            )

        quote_ht = st.number_input(
            "Montant du devis HT (DZD) *",
            min_value = 0.0,
            value     = max(suggested, 0.0),
            step      = 1_000.0,
            format    = "%.0f",
            key       = f"quote_ht_{req['id']}",
        )
        vat_preview = round(quote_ht * vat_rate, 2)
        ttc_preview = round(quote_ht + vat_preview, 2)
        st.markdown(
            f"**TVA ({vat_rate * 100:.0f}%):** {vat_preview:,.0f} DZD  \n"
            f"**Total TTC:** **{ttc_preview:,.0f} DZD**"
        )

        _validity = st.number_input(
            "Validité du devis (jours)",
            min_value = 7,
            max_value = 90,
            value     = 30,
            key       = f"quote_validity_{req['id']}",
        )
        quote_notes = st.text_area(
            "Notes / conditions particulières",
            key         = f"quote_notes_{req['id']}",
            height      = 80,
            placeholder = "Ex: Ce devis inclut l'extraction d'ADN.",
        )

        if st.button(
            "📧 Enregistrer et envoyer le devis",
            key                 = f"send_quote_{req['id']}",
            type                = "primary",
            use_container_width = True,
            disabled            = (quote_ht <= 0),
        ):
            try:
                set_request_quote(req["id"], quote_ht, actor)
                transition(
                    request_id = req["id"],
                    to_state   = GenoClabState.QUOTE_SENT,
                    actor      = actor,
                    notes      = quote_notes,
                )
                _action_ok(f"Devis de {ttc_preview:,.0f} DZD TTC envoyé au client.")
                st.cache_data.clear()
                st.rerun()
            except PlagenorError as e:
                _action_err(e)

    # ── QUOTE_SENT ────────────────────────────────────────────────────────────
    elif status == GenoClabState.QUOTE_SENT:
        vat_rate     = float(getattr(config, "VAT_RATE", 0.19))
        quote_amount = float(req.get("quote_amount", 0))
        vat          = round(quote_amount * vat_rate, 2)
        ttc          = round(quote_amount + vat, 2)

        st.info(
            f"⏳ En attente de réponse client.  \n"
            f"HT: **{quote_amount:,.0f} DZD** | TTC: **{ttc:,.0f} DZD**"
        )

        st.markdown("#### Réponse client manuelle")
        st.caption(
            "Si le client a répondu hors plateforme (email, téléphone), "
            "enregistrez sa réponse ici."
        )

        col1, col2 = st.columns(2)
        with col1:
            if confirm_action(
                key     = f"client_accept_{req['id']}",
                label   = "🤝 Client a accepté",
                message = (
                    "Enregistrer l'acceptation ?  \n"
                    "La facture sera générée automatiquement."
                ),
            ):
                _advance_request(
                    req, GenoClabState.QUOTE_VALIDATED_BY_CLIENT, actor
                )

        with col2:
            reject_note = st.text_input(
                "Motif refus client",
                key         = f"client_reject_note_{req['id']}",
                placeholder = "Ex: Budget insuffisant.",
            )
            if confirm_action(
                key     = f"client_reject_{req['id']}",
                label   = "🚫 Client a refusé",
                message = "Enregistrer le refus ? La demande sera clôturée.",
                danger  = True,
            ):
                _advance_request(
                    req, GenoClabState.QUOTE_REJECTED_BY_CLIENT,
                    actor, reject_note,
                )

    # ── QUOTE_VALIDATED_BY_CLIENT ─────────────────────────────────────────────
    # BUG-FIX P-02: INVOICE_GENERATED is auto-chained by workflow_engine
    # immediately after QUOTE_VALIDATED_BY_CLIENT. A request should never stay
    # here. If it does, the auto-chain failed — show diagnostic only.
    elif status == GenoClabState.QUOTE_VALIDATED_BY_CLIENT:
        vat_rate     = float(getattr(config, "VAT_RATE", 0.19))
        quote_amount = float(req.get("quote_amount", 0))
        vat          = round(quote_amount * vat_rate, 2)
        ttc          = round(quote_amount + vat, 2)

        st.info(
            f"✅ Devis accepté — **{ttc:,.0f} DZD TTC**  \n\n"
            f"⚙️ La facture est générée automatiquement (transition auto-chaînée).  \n"
            f"Si la demande reste bloquée ici, contactez SUPER_ADMIN "
            f"pour forcer la transition via le panneau de supervision."
        )

        try:
            from core.repository import get_invoice_by_request_id
            inv = get_invoice_by_request_id(req["id"])
            if inv:
                st.success(
                    f"🧾 Facture déjà émise: **{inv.get('invoice_number', '–')}**  \n"
                    f"Total TTC: **{float(inv.get('total_ttc', 0)):,.0f} DZD**  \n"
                    f"Intégrité: `{inv.get('hash_short', '–')}`"
                )
                if st.button("🔄 Actualiser", key=f"refresh_inv_{req['id']}"):
                    st.cache_data.clear()
                    st.rerun()
        except Exception:
            pass


# ── Tab: Dashboard ────────────────────────────────────────────────────────────
def _tab_dashboard(actor: dict) -> None:
    st.markdown("## 📊 Tableau de bord — KPIs & Productivité")

    requests = _load_active_requests()
    members  = _load_members()
    invoices = _load_invoices()

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("📋 Demandes actives", len(requests))
    with col2:
        st.metric("🌱 IBTIKAR", len(_by_channel(requests, CHANNEL_IBTIKAR)))
    with col3:
        st.metric("🧬 GENOCLAB", len(_by_channel(requests, CHANNEL_GENOCLAB)))
    with col4:
        st.metric("🧑‍🔬 Membres disponibles",
                  len([m for m in members if m.get("available")]))
    with col5:
        st.metric("🧾 Factures", len(invoices))

    st.divider()

    # Status breakdown
    st.markdown("### 📊 Répartition par statut")
    status_counts: dict = {}
    for req in requests:
        s = req.get("status", "UNKNOWN")
        status_counts[s] = status_counts.get(s, 0) + 1

    if status_counts:
        cols = st.columns(min(len(status_counts), 4))
        for i, (status, count) in enumerate(sorted(status_counts.items())):
            with cols[i % len(cols)]:
                st.metric(status, count)

    st.divider()

    # Productivity leaderboard
    # BUG-FIX P-01: PRODUCTIVITY_EMOJI_MAP now module-level — visible here
    st.markdown("### 🏆 Classement de productivité")
    try:
        ranking = get_productivity_ranking()
    except Exception:
        ranking = []

    if not ranking:
        st.info("Aucune donnée. Cliquez 'Recalculer' pour générer les scores.")
    else:
        for r in ranking:
            emoji         = PRODUCTIVITY_EMOJI_MAP.get(r.get("label", "NORMAL"), "📊")
            score         = float(r.get("score", 0))
            label         = r.get("label", "N/A")
            name          = r.get("member_name", r.get("name", "–"))
            declining_tag = "  📉 **En baisse**" if r.get("declining") else ""
            st.markdown(
                f"{emoji} **{name}** &nbsp; "
                f"Score: `{score:.1f}` &nbsp; "
                f"Niveau: `{label}`"
                f"{declining_tag}"
            )
            st.progress(score / 100)

    st.divider()

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("#### 🔄 Recalculer tous les scores")
        if st.button(
            "Recalculer tous les membres",
            use_container_width = True,
            key                 = "recalc_all_btn",
        ):
            with st.spinner("Recalcul en cours..."):
                try:
                    results = recalculate_all(actor)
                    st.success(f"✅ {len(results)} membres recalculés.")
                    st.cache_data.clear()
                    st.rerun()
                except PlagenorError as e:
                    st.error(str(e))

    with col_r2:
        st.markdown("#### 📊 Recalculer un membre")
        if members:
            with st.form("recalc_single_form"):
                mem_opts = {m["name"]: m["id"] for m in members}
                sel_m    = st.selectbox(
                    "Membre", list(mem_opts.keys()), key="recalc_single_sel"
                )
                if st.form_submit_button("Recalculer", use_container_width=True):
                    try:
                        result = recalculate_member(mem_opts[sel_m], user=actor)
                        st.success(
                            f"Score: {float(result.get('score', 0)):.1f} — "
                            f"Niveau: {result.get('label', '–')}"
                        )
                        st.cache_data.clear()
                        st.rerun()
                    except PlagenorError as e:
                        st.error(str(e))

    # Recent activity
    st.divider()
    st.markdown("### 🔍 Dernières activités (20 entrées)")
    try:
        logs = sorted(
            get_all_audit_logs(),
            key     = lambda x: x.get("timestamp", ""),
            reverse = True,
        )[:20]
        for log in logs:
            st.markdown(
                f"`{log.get('timestamp', '')[:19]}` "
                f"| **{log.get('action', '')}** "
                f"| `{log.get('entity_type', '')}` "
                f"| `{str(log.get('entity_id', ''))[:8]}` "
                f"| 👤 `{resolve_username(log.get('user_id', ''))}`"
            )
    except Exception:
        st.info("Aucun log disponible.")


# ── Entry point ───────────────────────────────────────────────────────────────
def render() -> None:
    user = require_roles(config.ROLE_PLATFORM_ADMIN, config.ROLE_SUPER_ADMIN)
    render_sidebar_user(user)

    st.title("🛡️ PLAGENOR 4.0 — Tableau de bord Platform Admin")
    st.caption(
        f"Connecté en tant que: **{user.get('username')}** "
        f"| Rôle: `{user.get('role')}`"
    )

    requests = _load_active_requests()
    members  = _load_members()
    invoices = _load_invoices()
    avg_p    = (
        sum(float(m.get("productivity_score", 50)) for m in members) / len(members)
        if members else 0.0
    )

    kpi_row([
        {"label": "📋 Demandes actives",    "value": len(requests)},
        {"label": "🌱 IBTIKAR",             "value": len(_by_channel(requests, CHANNEL_IBTIKAR))},
        {"label": "🧬 GENOCLAB",            "value": len(_by_channel(requests, CHANNEL_GENOCLAB))},
        {"label": "🧾 Factures",            "value": len(invoices)},
        {"label": "📊 Productivité moy.",   "value": f"{avg_p:.1f}"},
    ])
    st.divider()

    tab_labels = [
        "📋 File d'attente",
        "✅ Validation",
        "🧬 Assignation",
        "📅 Rendez-vous",
        "🔬 Analyse",
        "📄 Rapports",
        "💵 Devis",
        "📊 Dashboard",
    ]

    tabs = st.tabs(tab_labels)

    with tabs[0]: _tab_queue(user)
    with tabs[1]: _tab_validation(user)
    with tabs[2]: _tab_assignment(user)
    with tabs[3]: _tab_appointments(user)
    with tabs[4]: _tab_analysis(user)
    with tabs[5]: _tab_reports(user)
    with tabs[6]: _tab_quotes(user)
    with tabs[7]: _tab_dashboard(user)
