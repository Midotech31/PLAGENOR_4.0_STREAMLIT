# ui/requester_dashboard.py
# ── PLAGENOR 4.0 — Requester Dashboard (IBTIKAR) ─────────────────────────────
# Role: ROLE_REQUESTER — institutional researchers submitting IBTIKAR requests
#
# Tabs:
#   1. 📊 Tableau de bord   — KPIs, budget gauge, recent activity
#   2. ➕ Nouvelle demande  — IBTIKAR request submission form
#   3. 📋 Mes demandes      — request list with status tracking
#   4. 📄 Mes rapports      — available analysis reports
#   5. 💰 Mon budget        — IBTIKAR annual budget tracker
#   6. 🔔 Notifications     — unread notifications
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, date
from typing import Optional

import streamlit as st

import config
from config import IbtikarState as IS
from ui.auth import (
    require_role,
    render_user_profile_card,
    audit_page_access,
    has_permission,
)
from core.repository import (
    get_all_active_requests,
    get_all_archived_requests,
    get_all_services,
    save_request,
    get_all_notifications_for_user,
    mark_notification_read,
    mark_all_notifications_read_for_user,
    get_all_documents_for_request,
)
from core.workflow_engine import transition, get_pipeline_position
from core.exceptions import WorkflowError


# ── Constants ─────────────────────────────────────────────────────────────────
CH = config.CHANNEL_IBTIKAR
_TERMINAL = {IS.COMPLETED, IS.REJECTED, "ARCHIVED"}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.utcnow().isoformat()


def _fmt_date(iso: str) -> str:
    if not iso:
        return "–"
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso[:16]


def _fmt_date_short(iso: str) -> str:
    if not iso:
        return "–"
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%d/%m/%Y")
    except Exception:
        return iso[:10]


def _status_badge(status: str) -> str:
    icon, label, colour = config.STATUS_LABELS.get(
        status, ("📋", status, "#7F8C8D")
    )
    return (
        f'<span style="background:{colour}22; color:{colour}; '
        f'padding:3px 10px; border-radius:12px; font-size:0.75rem; '
        f'font-weight:600;">{icon} {label}</span>'
    )


def _get_my_requests(user_id: str) -> list[dict]:
    """Returns all IBTIKAR requests submitted by this user (active + archived)."""
    active   = get_all_active_requests()
    archived = get_all_archived_requests()
    all_reqs = active + archived
    return [
        r for r in all_reqs
        if r.get("channel") == CH
        and r.get("submitted_by_user_id") == user_id
    ]


def _used_budget(requests: list[dict]) -> float:
    """Sums quote_amount of non-rejected, non-archived IBTIKAR requests."""
    return sum(
        float(r.get("quote_amount", 0))
        for r in requests
        if r.get("status") not in {IS.REJECTED, "ARCHIVED",
                                    GS_QUOTE_REJECTED := "QUOTE_REJECTED_BY_CLIENT"}
    )


def _budget_colour(pct: float) -> str:
    if pct >= 90:
        return "#E74C3C"
    if pct >= 70:
        return "#F39C12"
    return "#27AE60"


def _services_for_channel(channel: str) -> list[dict]:
    return [
        s for s in get_all_services()
        if s.get("channel") == channel and s.get("active", True)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def render() -> None:
    user = require_role(config.ROLE_REQUESTER)
    render_user_profile_card(user)
    audit_page_access("RequesterDashboard", user)

    uid = user["id"]

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown(
            f"<div style='font-size:0.78rem; color:#BDC3C7;'>"
            f"Canal actif: <b style='color:#1ABC9C;'>"
            f"{config.CHANNEL_LABELS.get(CH, CH)}</b></div>",
            unsafe_allow_html=True,
        )

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#1B4F72,#154360);
                    border-radius:14px; padding:20px 28px; margin-bottom:20px;">
            <div style="font-size:1.5rem; font-weight:800; color:#FFFFFF;">
                📋 Espace Demandeur — IBTIKAR
            </div>
            <div style="font-size:0.85rem; color:#AED6F1; margin-top:4px;">
                {config.PLATFORM_INSTITUTION}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Tableau de bord",
        "➕ Nouvelle demande",
        "📋 Mes demandes",
        "📄 Mes rapports",
        "💰 Mon budget",
        "🔔 Notifications",
    ])

    with tab1:
        _render_dashboard_tab(user)

    with tab2:
        _render_new_request_tab(user)

    with tab3:
        _render_my_requests_tab(user)

    with tab4:
        _render_reports_tab(user)

    with tab5:
        _render_budget_tab(user)

    with tab6:
        _render_notifications_tab(user)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def _render_dashboard_tab(user: dict) -> None:
    uid      = user["id"]
    my_reqs  = _get_my_requests(uid)

    total         = len(my_reqs)
    active_reqs   = [r for r in my_reqs if r.get("status") not in _TERMINAL]
    completed     = [r for r in my_reqs if r.get("status") == IS.COMPLETED]
    rejected      = [r for r in my_reqs if r.get("status") == IS.REJECTED]
    in_progress   = [
        r for r in my_reqs
        if r.get("status") in {IS.IN_PROGRESS, IS.ANALYSIS_FINISHED}
    ]
    awaiting      = [r for r in my_reqs if r.get("status") == IS.REPORT_UPLOADED]
    reports_avail = [
        r for r in my_reqs
        if r.get("status") in {IS.SENT_TO_REQUESTER, IS.COMPLETED}
    ]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    st.markdown("### 📊 Vue d'ensemble")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📨 Total demandes",    total)
    c2.metric("🔄 En cours",          len(active_reqs))
    c3.metric("🔬 En analyse",        len(in_progress))
    c4.metric("🎉 Complétées",        len(completed))
    c5.metric("📄 Rapports dispo.",   len(reports_avail))

    st.divider()

    # ── Budget gauge ──────────────────────────────────────────────────────────
    used     = _used_budget(my_reqs)
    cap      = config.IBTIKAR_BUDGET_CAP
    pct      = round(min(used / cap * 100, 100), 1) if cap else 0.0
    col_hex  = _budget_colour(pct)

    st.markdown("### 💰 Budget IBTIKAR annuel")
    col_b1, col_b2 = st.columns([2, 1])
    with col_b1:
        st.progress(pct / 100)
        st.markdown(
            f"<span style='color:{col_hex}; font-weight:700; font-size:1.1rem;'>"
            f"{used:,.0f} DZD</span>  utilisés sur  "
            f"<b>{cap:,.0f} DZD</b>  ({pct}%)",
            unsafe_allow_html=True,
        )
    with col_b2:
        remaining = max(cap - used, 0)
        st.metric(
            "💳 Disponible",
            f"{remaining:,.0f} DZD",
            delta = f"-{pct:.1f}%" if pct > 0 else None,
            delta_color = "inverse" if pct > 70 else "normal",
        )

    st.divider()

    # ── Active requests summary ───────────────────────────────────────────────
    st.markdown("### 🔄 Demandes actives")
    if not active_reqs:
        st.info("Aucune demande active. Soumettez votre première demande via l'onglet **➕ Nouvelle demande**.")
        return

    for req in sorted(active_reqs, key=lambda r: r.get("updated_at", ""), reverse=True)[:5]:
        status   = req.get("status", "")
        pipeline = get_pipeline_position(req["id"])
        pct_pip  = pipeline.get("pct", 0)
        step     = pipeline.get("step", 0)
        total_s  = pipeline.get("total", 1)

        with st.expander(
            f"🔬 `{req['id'][:8].upper()}` — "
            f"{req.get('form_data', {}).get('project', {}).get('title', 'Demande sans titre')[:50]}",
            expanded = False,
        ):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f"**Statut:** {_status_badge(status)}",
                    unsafe_allow_html=True,
                )
                st.progress(pct_pip / 100)
                st.caption(
                    f"Étape {step}/{total_s} — "
                    f"{pct_pip:.0f}% du parcours"
                )
            with col2:
                st.caption(f"Soumis le: {_fmt_date_short(req.get('created_at',''))}")
                st.caption(f"Mis à jour: {_fmt_date_short(req.get('updated_at',''))}")

            # Action buttons depending on state
            _render_requester_actions(req, user)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — NEW REQUEST
# ══════════════════════════════════════════════════════════════════════════════

def _render_new_request_tab(user: dict) -> None:
    st.markdown("### ➕ Soumettre une nouvelle demande IBTIKAR")

    services = _services_for_channel(CH)
    if not services:
        st.warning(
            "⚠️ Aucun service IBTIKAR n'est actuellement disponible. "
            "Contactez l'administrateur de la plateforme."
        )
        return

    # Budget check before allowing submission
    uid     = user["id"]
    my_reqs = _get_my_requests(uid)
    used    = _used_budget(my_reqs)
    cap     = config.IBTIKAR_BUDGET_CAP
    if used >= cap:
        st.error(
            f"🚫 Votre plafond budgétaire annuel IBTIKAR est atteint "
            f"({used:,.0f} / {cap:,.0f} DZD). "
            f"Contactez l'administration pour un arbitrage."
        )
        return

    # ── Service selector ──────────────────────────────────────────────────────
    svc_options = {s["id"]: f"{s.get('code','–')} — {s['name']}" for s in services}
    selected_svc_id = st.selectbox(
        "🧬 Service demandé *",
        options  = list(svc_options.keys()),
        format_func = lambda x: svc_options[x],
        key      = "new_req_service",
    )
    selected_svc = next((s for s in services if s["id"] == selected_svc_id), {})

    if selected_svc:
        with st.expander("ℹ️ Description du service", expanded=False):
            st.markdown(f"**{selected_svc.get('name','–')}**")
            st.write(selected_svc.get("description", "–"))
            st.caption(
                f"Budget indicatif: **{float(selected_svc.get('base_price',0)):,.0f} DZD**"
            )

    st.divider()

    # ── Form ──────────────────────────────────────────────────────────────────
    with st.form("ibtikar_submission_form", clear_on_submit=False):

        st.markdown("#### 👤 Informations du demandeur")
        col1, col2 = st.columns(2)
        with col1:
            full_name   = st.text_input("Nom complet *",
                                         value = user.get("full_name", ""),
                                         placeholder = "Dr. Prénom NOM")
            institution = st.text_input("Institution / Laboratoire *",
                                         placeholder = "Ex: ESSBO, USTHB...")
        with col2:
            email = st.text_input("Email *",
                                   value = user.get("email", ""),
                                   placeholder = "email@institution.dz")
            phone = st.text_input("Téléphone",
                                   placeholder = "+213 5X XX XX XX")

        grade = st.selectbox(
            "Grade académique",
            ["Professeur", "Maître de conférences A", "Maître de conférences B",
             "Maître assistant A", "Maître assistant B",
             "Doctorant(e)", "Chercheur(se)", "Autre"],
            key = "req_grade",
        )

        st.divider()
        st.markdown("#### 🔬 Projet de recherche")

        project_title = st.text_input(
            "Titre du projet *",
            placeholder = "Titre complet du projet de recherche",
            key         = "req_project_title",
        )
        project_acronym = st.text_input(
            "Acronyme du projet",
            placeholder = "Ex: MRESIST-2025",
            key         = "req_project_acronym",
        )
        project_desc = st.text_area(
            "Description et objectifs scientifiques *",
            placeholder = (
                "Décrivez brièvement votre projet, les hypothèses "
                "de recherche et les objectifs attendus..."
            ),
            height = 130,
            key    = "req_project_desc",
        )

        col3, col4 = st.columns(2)
        with col3:
            funding_code = st.text_input(
                "Code de financement DGRSDT",
                placeholder = "Ex: PRFU-B00L01UN31120220001",
                key         = "req_funding_code",
            )
        with col4:
            funding_year = st.selectbox(
                "Année de financement",
                options = list(range(2022, datetime.utcnow().year + 2)),
                index   = len(list(range(2022, datetime.utcnow().year + 2))) - 1,
                key     = "req_funding_year",
            )

        st.divider()
        st.markdown("#### 🧫 Échantillons biologiques")

        col5, col6 = st.columns(2)
        with col5:
            sample_type = st.selectbox(
                "Type d'échantillons *",
                ["Souches bactériennes", "ADN extrait", "ARN extrait",
                 "Tissu biologique", "Eau environnementale",
                 "Sol / Sédiment", "Autre"],
                key = "req_sample_type",
            )
            sample_count = st.number_input(
                "Nombre d'échantillons *",
                min_value = 1,
                max_value = 500,
                value     = 1,
                step      = 1,
                key       = "req_sample_count",
            )
        with col6:
            sample_organism = st.text_input(
                "Organisme / Espèce",
                placeholder = "Ex: Klebsiella pneumoniae, E. coli...",
                key         = "req_organism",
            )
            sample_origin = st.selectbox(
                "Origine des échantillons",
                ["Clinique (humain)", "Vétérinaire (animal)",
                 "Environnement (eau, sol)", "Agroalimentaire",
                 "Industriel", "Autre"],
                key = "req_origin",
            )

        sample_notes = st.text_area(
            "Notes sur les échantillons",
            placeholder = "Conditions de conservation, informations complémentaires...",
            height      = 80,
            key         = "req_sample_notes",
        )

        st.divider()
        st.markdown("#### 💰 Budget demandé")

        col7, col8 = st.columns(2)
        with col7:
            remaining_budget = max(cap - used, 0)
            base_price       = float(selected_svc.get("base_price", 0))
            default_budget   = min(
                base_price * int(sample_count if False else 1),
                remaining_budget,
            )
            budget_requested = st.number_input(
                f"Montant demandé (DZD) * — Max disponible: {remaining_budget:,.0f} DZD",
                min_value = 0.0,
                max_value = float(remaining_budget),
                value     = min(float(base_price), remaining_budget),
                step      = 1000.0,
                format    = "%.2f",
                key       = "req_budget",
            )
        with col8:
            budget_justif = st.text_area(
                "Justification budgétaire",
                placeholder = "Détaillez l'utilisation prévue du budget...",
                height      = 100,
                key         = "req_budget_justif",
            )

        st.divider()
        st.markdown("#### 📅 Disponibilité pour le dépôt des échantillons")

        col9, col10 = st.columns(2)
        with col9:
            avail_from = st.date_input(
                "Disponible à partir du *",
                value = date.today(),
                key   = "req_avail_from",
            )
        with col10:
            avail_to = st.date_input(
                "Disponible jusqu'au",
                value = date.today(),
                key   = "req_avail_to",
            )

        st.divider()
        st.markdown("#### 📎 Informations complémentaires")

        priority = st.select_slider(
            "Priorité de la demande",
            options = ["Normale", "Élevée", "Urgente"],
            value   = "Normale",
            key     = "req_priority",
        )

        add_notes = st.text_area(
            "Notes additionnelles",
            placeholder = "Toute information jugée utile pour le traitement de la demande...",
            height      = 80,
            key         = "req_add_notes",
        )

        # Terms
        agreed = st.checkbox(
            "✅ Je certifie l'exactitude des informations fournies et "
            "m'engage à respecter les conditions d'utilisation de la plateforme PLAGENOR.",
            key = "req_agreed",
        )

        submitted = st.form_submit_button(
            "📨 Soumettre la demande",
            use_container_width = True,
            type                = "primary",
        )

    # ── Form processing ───────────────────────────────────────────────────────
    if submitted:
        errors = []

        if not full_name.strip():
            errors.append("Nom complet requis.")
        if not institution.strip():
            errors.append("Institution / Laboratoire requis.")
        if not email.strip() or "@" not in email:
            errors.append("Email valide requis.")
        if not project_title.strip():
            errors.append("Titre du projet requis.")
        if not project_desc.strip():
            errors.append("Description du projet requise.")
        if budget_requested <= 0:
            errors.append("Le montant du budget doit être supérieur à 0.")
        if budget_requested > remaining_budget:
            errors.append(
                f"Budget demandé ({budget_requested:,.0f} DZD) "
                f"dépasse le disponible ({remaining_budget:,.0f} DZD)."
            )
        if not agreed:
            errors.append("Vous devez accepter les conditions d'utilisation.")

        if errors:
            for err in errors:
                st.error(f"⚠️ {err}")
        else:
            _submit_ibtikar_request(
                user             = user,
                service          = selected_svc,
                full_name        = full_name.strip(),
                institution      = institution.strip(),
                email            = email.strip(),
                phone            = phone.strip(),
                grade            = grade,
                project_title    = project_title.strip(),
                project_acronym  = project_acronym.strip(),
                project_desc     = project_desc.strip(),
                funding_code     = funding_code.strip(),
                funding_year     = int(funding_year),
                sample_type      = sample_type,
                sample_count     = int(sample_count),
                sample_organism  = sample_organism.strip(),
                sample_origin    = sample_origin,
                sample_notes     = sample_notes.strip(),
                budget_requested = float(budget_requested),
                budget_justif    = budget_justif.strip(),
                avail_from       = avail_from.isoformat(),
                avail_to         = avail_to.isoformat(),
                priority         = priority,
                add_notes        = add_notes.strip(),
            )


def _submit_ibtikar_request(user: dict, service: dict, **fields) -> None:
    """Builds and saves a new IBTIKAR request in SUBMITTED state."""
    req_id = str(uuid.uuid4())
    now    = _now()

    request = {
        "id":                   req_id,
        "channel":              CH,
        "status":               IS.SUBMITTED,
        "service_id":           service["id"],
        "submitted_by_user_id": user["id"],
        "submitted_by_username":user.get("username", "–"),
        "organization_id":      user.get("organization_id", ""),
        "created_at":           now,
        "updated_at":           now,

        # Financial
        "quote_amount":         fields["budget_requested"],
        "quote_vat":            0.0,
        "quote_ttc":            fields["budget_requested"],
        "quote_vat_rate":       0.0,
        "invoice_id":           None,
        "invoice_number":       None,

        # Assignment
        "assigned_member_id":   None,
        "assigned_member_name": None,

        # History
        "status_history": [{
            "id":         str(uuid.uuid4()),
            "from_state": "",
            "to_state":   IS.SUBMITTED,
            "timestamp":  now,
            "actor_id":   user["id"],
            "actor_role": config.ROLE_REQUESTER,
            "notes":      "Soumission initiale par le demandeur.",
            "forced":     False,
        }],

        "notes":       [],
        "documents":   [],
        "report_path": None,
        "pdf_path":    None,

        # Form data (full snapshot for document generation)
        "form_data": {
            "requester": {
                "full_name":   fields["full_name"],
                "institution": fields["institution"],
                "email":       fields["email"],
                "phone":       fields["phone"],
                "grade":       fields["grade"],
            },
            "project": {
                "title":        fields["project_title"],
                "acronym":      fields["project_acronym"],
                "description":  fields["project_desc"],
                "funding_code": fields["funding_code"],
                "funding_year": fields["funding_year"],
            },
            "samples": {
                "type":         fields["sample_type"],
                "count":        fields["sample_count"],
                "organism":     fields["sample_organism"],
                "origin":       fields["sample_origin"],
                "notes":        fields["sample_notes"],
            },
            "budget": {
                "requested":    fields["budget_requested"],
                "justification":fields["budget_justif"],
            },
            "availability": {
                "from": fields["avail_from"],
                "to":   fields["avail_to"],
            },
            "priority":   fields["priority"],
            "add_notes":  fields["add_notes"],
        },
    }

    try:
        save_request(request)

        try:
            from core.audit_engine import log_action
            log_action(
                action      = "REQUEST_SUBMITTED",
                entity_type = "REQUEST",
                entity_id   = req_id,
                actor       = user,
                details     = (
                    f"IBTIKAR | Projet: {fields['project_title'][:40]} | "
                    f"Budget: {fields['budget_requested']:,.0f} DZD"
                ),
            )
        except Exception:
            pass

        try:
            from core.repository import create_notification
            create_notification(
                title   = "📨 Demande soumise avec succès",
                message = (
                    f"Votre demande `{req_id[:8].upper()}` a été soumise "
                    f"et sera traitée sous 5 jours ouvrables."
                ),
                level   = "success",
                user_id = user["id"],
            )
        except Exception:
            pass

        st.success(
            f"✅ Demande **{req_id[:8].upper()}** soumise avec succès !  \n"
            f"Vous serez notifié par email et sur la plateforme à chaque "
            f"changement de statut."
        )
        st.balloons()

    except Exception as e:
        st.error(f"❌ Erreur lors de la soumission: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — MY REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

def _render_my_requests_tab(user: dict) -> None:
    uid     = user["id"]
    my_reqs = _get_my_requests(uid)

    st.markdown("### 📋 Mes demandes IBTIKAR")

    if not my_reqs:
        st.info(
            "Vous n'avez pas encore soumis de demande.  \n"
            "Utilisez l'onglet **➕ Nouvelle demande** pour commencer."
        )
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    all_statuses = sorted({r.get("status", "–") for r in my_reqs})
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        filter_status = st.multiselect(
            "Filtrer par statut",
            options      = all_statuses,
            default      = [],
            format_func  = lambda s: config.STATUS_LABELS.get(s, ("", s, ""))[1],
            key          = "req_filter_status",
        )
    with col_f2:
        sort_by = st.selectbox(
            "Trier par",
            ["Plus récent", "Plus ancien", "Statut"],
            key = "req_sort",
        )

    filtered = my_reqs
    if filter_status:
        filtered = [r for r in filtered if r.get("status") in filter_status]

    if sort_by == "Plus ancien":
        filtered = sorted(filtered, key=lambda r: r.get("created_at", ""))
    elif sort_by == "Statut":
        filtered = sorted(filtered, key=lambda r: r.get("status", ""))
    else:
        filtered = sorted(
            filtered,
            key     = lambda r: r.get("updated_at", ""),
            reverse = True,
        )

    st.caption(f"{len(filtered)} demande(s) affichée(s) sur {len(my_reqs)}")
    st.divider()

    # ── Request cards ─────────────────────────────────────────────────────────
    for req in filtered:
        _render_request_card(req, user)


def _render_request_card(req: dict, user: dict) -> None:
    """Renders a detailed card for one request."""
    req_id    = req["id"]
    status    = req.get("status", "")
    form_data = req.get("form_data", {})
    project   = form_data.get("project", {})
    samples   = form_data.get("samples", {})
    budget    = form_data.get("budget", {})

    icon, label, colour = config.STATUS_LABELS.get(status, ("📋", status, "#7F8C8D"))
    pipeline  = get_pipeline_position(req_id)
    pct_pip   = pipeline.get("pct", 0)

    with st.expander(
        f"{icon} `{req_id[:8].upper()}` — "
        f"{project.get('title', 'Sans titre')[:55]}  "
        f"[{label}]",
        expanded = False,
    ):
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            st.markdown(
                f"**Statut:** {_status_badge(status)}",
                unsafe_allow_html=True,
            )
            st.progress(pct_pip / 100)
            st.caption(
                f"Étape {pipeline.get('step',0)}/{pipeline.get('total',1)} "
                f"— {pct_pip:.0f}%"
            )

        with col2:
            st.caption(f"**Soumis le:** {_fmt_date_short(req.get('created_at',''))}")
            st.caption(f"**Modifié le:** {_fmt_date_short(req.get('updated_at',''))}")
            st.caption(f"**Échantillons:** {samples.get('count', '–')}")

        with col3:
            amt = float(budget.get("requested", req.get("quote_amount", 0)))
            st.metric("Budget demandé", f"{amt:,.0f} DZD")

        st.divider()

        # ── Details tabs ──────────────────────────────────────────────────────
        dt1, dt2, dt3 = st.tabs(["📋 Détails", "📅 Historique", "⚡ Actions"])

        with dt1:
            _render_request_details(req)

        with dt2:
            _render_status_history(req)

        with dt3:
            _render_requester_actions(req, user)


def _render_request_details(req: dict) -> None:
    form_data = req.get("form_data", {})
    requester = form_data.get("requester", {})
    project   = form_data.get("project",   {})
    samples   = form_data.get("samples",   {})
    budget    = form_data.get("budget",    {})
    avail     = form_data.get("availability", {})

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**👤 Demandeur**")
        st.write(f"- Nom: {requester.get('full_name','–')}")
        st.write(f"- Institution: {requester.get('institution','–')}")
        st.write(f"- Email: {requester.get('email','–')}")
        st.write(f"- Grade: {requester.get('grade','–')}")

        st.markdown("**🔬 Projet**")
        st.write(f"- Titre: {project.get('title','–')}")
        if project.get("acronym"):
            st.write(f"- Acronyme: {project.get('acronym','–')}")
        if project.get("funding_code"):
            st.write(f"- Code DGRSDT: {project.get('funding_code','–')}")
        st.write(f"- Année: {project.get('funding_year','–')}")

    with col2:
        st.markdown("**🧫 Échantillons**")
        st.write(f"- Type: {samples.get('type','–')}")
        st.write(f"- Nombre: {samples.get('count','–')}")
        st.write(f"- Organisme: {samples.get('organism','–') or '–'}")
        st.write(f"- Origine: {samples.get('origin','–')}")

        st.markdown("**💰 Budget**")
        amt = float(budget.get("requested", req.get("quote_amount", 0)))
        st.write(f"- Demandé: **{amt:,.0f} DZD**")
        if budget.get("justification"):
            st.caption(f"Justification: {budget.get('justification','')[:100]}")

        st.markdown("**📅 Disponibilité**")
        st.write(f"- Du: {_fmt_date_short(avail.get('from',''))}")
        if avail.get("to"):
            st.write(f"- Au: {_fmt_date_short(avail.get('to',''))}")

    if project.get("description"):
        st.markdown("**📝 Description du projet**")
        st.info(project.get("description", ""))

    if req.get("assigned_member_name"):
        st.markdown(
            f"**👤 Analyste assigné:** {req.get('assigned_member_name','–')}"
        )


def _render_status_history(req: dict) -> None:
    history = req.get("status_history", [])
    if not history:
        st.info("Aucun historique disponible.")
        return

    for entry in reversed(history):
        f_state = entry.get("from_state", "")
        t_state = entry.get("to_state",   "")
        f_icon  = config.STATUS_LABELS.get(f_state, ("📋",))[0]
        t_icon  = config.STATUS_LABELS.get(t_state, ("📋",))[0]

        st.markdown(
            f"**{_fmt_date(entry.get('timestamp',''))}**  \n"
            f"{f_icon} `{f_state}` → {t_icon} `{t_state}`"
            + (f"  \n💬 _{entry.get('notes','')}_"
               if entry.get("notes") else ""),
        )
        st.divider()


def _render_requester_actions(req: dict, user: dict) -> None:
    """Renders available actions for the requester given current state."""
    status    = req.get("status", "")
    req_id    = req["id"]

    # ── APPOINTMENT_SCHEDULED — requester acknowledges ────────────────────────
    if status == IS.APPOINTMENT_SCHEDULED:
        form_data = req.get("form_data", {})
        appt_date = form_data.get("appointment_date", "")
        st.info(
            f"📅 **Rendez-vous planifié**"
            + (f" — {_fmt_date_short(appt_date)}" if appt_date else "")
            + "  \nPrésentez-vous au laboratoire avec vos échantillons "
              "à la date indiquée."
        )
        if st.button(
            "✅ Confirmer ma prise en compte",
            key = f"ack_appt_{req_id}",
        ):
            st.success("✅ Confirmation enregistrée.")

    # ── SENT_TO_REQUESTER — download report ───────────────────────────────────
    elif status in {IS.SENT_TO_REQUESTER, IS.COMPLETED}:
        report_path = req.get("report_path", "")
        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                st.download_button(
                    label               = "📥 Télécharger le rapport d'analyse",
                    data                = f,
                    file_name           = os.path.basename(report_path),
                    mime                = "application/octet-stream",
                    key                 = f"dl_report_{req_id}",
                    use_container_width = True,
                )
        else:
            docs = get_all_documents_for_request(req_id)
            report_docs = [
                d for d in docs
                if d.get("doc_type") in {"REPORT", "REPORT_TEMPLATE"}
            ]
            if report_docs:
                for doc in report_docs:
                    doc_path = doc.get("path", "")
                    if doc_path and os.path.exists(doc_path):
                        with open(doc_path, "rb") as f:
                            st.download_button(
                                label               = f"📥 {doc.get('filename','Rapport')}",
                                data                = f,
                                file_name           = doc.get("filename", "rapport.pdf"),
                                mime                = "application/octet-stream",
                                key                 = f"dl_doc_{doc['id']}",
                                use_container_width = True,
                            )
            else:
                st.info("📄 Le rapport sera disponible ici une fois transmis.")

    # ── REJECTED — show reason ────────────────────────────────────────────────
    elif status == IS.REJECTED:
        history = req.get("status_history", [])
        rejection = next(
            (e for e in reversed(history) if e.get("to_state") == IS.REJECTED),
            None,
        )
        reason = (rejection or {}).get("notes", "")
        st.error(
            "🚫 **Demande rejetée**"
            + (f"  \nMotif: {reason}" if reason else "")
        )

    # ── SUBMITTED / VALIDATED — pending admin ─────────────────────────────────
    elif status in {IS.SUBMITTED, IS.VALIDATED}:
        st.info(
            "⏳ Votre demande est en cours de traitement par l'administration. "
            "Vous serez notifié dès que la décision est prise."
        )

    # ── APPROVED — awaiting appointment ──────────────────────────────────────
    elif status == IS.APPROVED:
        st.success(
            "✅ Votre demande a été approuvée.  \n"
            "Un rendez-vous pour le dépôt de vos échantillons "
            "sera planifié prochainement."
        )

    # ── IN_PROGRESS / ANALYSIS stages ────────────────────────────────────────
    elif status in {IS.SAMPLE_RECEIVED, IS.SAMPLE_VERIFIED,
                    IS.ASSIGNED, IS.PENDING_ACCEPTANCE,
                    IS.IN_PROGRESS, IS.ANALYSIS_FINISHED}:
        stage_msgs = {
            IS.SAMPLE_RECEIVED:    "📦 Vos échantillons ont été réceptionnés.",
            IS.SAMPLE_VERIFIED:    "🔍 Vos échantillons ont été vérifiés. Assignation en cours.",
            IS.ASSIGNED:           "👤 Un analyste a été assigné à votre demande.",
            IS.PENDING_ACCEPTANCE: "⚡ L'analyste confirme sa prise en charge.",
            IS.IN_PROGRESS:        "🔬 L'analyse est en cours. Vous serez notifié à la fin.",
            IS.ANALYSIS_FINISHED:  "🧪 L'analyse est terminée. Génération du rapport en cours.",
        }
        st.info(stage_msgs.get(status, "🔄 Traitement en cours..."))

    # ── ADMIN_REVIEW / REPORT_VALIDATED ──────────────────────────────────────
    elif status in {IS.REPORT_UPLOADED, IS.ADMIN_REVIEW, IS.REPORT_VALIDATED}:
        st.info(
            "📄 Le rapport est en cours de révision par l'administration. "
            "Il vous sera transmis sous peu."
        )

    # ── COMPLETED / ARCHIVED ─────────────────────────────────────────────────
    elif status in {IS.COMPLETED, "ARCHIVED"}:
        st.success("🎉 Cette demande est clôturée.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — REPORTS
# ══════════════════════════════════════════════════════════════════════════════

def _render_reports_tab(user: dict) -> None:
    uid     = user["id"]
    my_reqs = _get_my_requests(uid)

    st.markdown("### 📄 Mes rapports d'analyse")

    report_reqs = [
        r for r in my_reqs
        if r.get("status") in {IS.SENT_TO_REQUESTER, IS.COMPLETED, "ARCHIVED"}
    ]

    if not report_reqs:
        st.info(
            "Aucun rapport disponible pour le moment.  \n"
            "Les rapports apparaissent ici une fois que l'analyse "
            "est terminée et transmise."
        )
        return

    for req in sorted(
        report_reqs,
        key     = lambda r: r.get("updated_at", ""),
        reverse = True,
    ):
        req_id    = req["id"]
        form_data = req.get("form_data", {})
        project   = form_data.get("project", {})
        status    = req.get("status", "")

        with st.expander(
            f"📄 `{req_id[:8].upper()}` — {project.get('title','–')[:55]}",
            expanded=True,
        ):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f"**Statut:** {_status_badge(status)}",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"Demande soumise le {_fmt_date_short(req.get('created_at',''))} | "
                    f"Transmis le {_fmt_date_short(req.get('updated_at',''))}"
                )
            with col2:
                st.caption(
                    f"Analyste: {req.get('assigned_member_name','–')}"
                )

            # Document list
            docs = get_all_documents_for_request(req_id)
            report_docs = [
                d for d in docs
                if d.get("doc_type") in {"REPORT", "REPORT_TEMPLATE", "ANALYSIS"}
            ]

            if report_docs:
                for doc in report_docs:
                    doc_path = doc.get("path", "")
                    if doc_path and os.path.exists(doc_path):
                        with open(doc_path, "rb") as f:
                            st.download_button(
                                label               = f"📥 {doc.get('filename','Rapport')}",
                                data                = f,
                                file_name           = doc.get("filename","rapport.pdf"),
                                mime                = "application/octet-stream",
                                key                 = f"report_dl_{doc['id']}",
                                use_container_width = True,
                            )
                    else:
                        st.caption(
                            f"⚠️ Fichier introuvable: {doc.get('filename','–')}"
                        )
            elif req.get("report_path") and os.path.exists(req.get("report_path","x")):
                with open(req["report_path"], "rb") as f:
                    st.download_button(
                        label               = "📥 Télécharger le rapport",
                        data                = f,
                        file_name           = os.path.basename(req["report_path"]),
                        mime                = "application/octet-stream",
                        key                 = f"report_dl_direct_{req_id}",
                        use_container_width = True,
                    )
            else:
                st.warning(
                    "Le rapport a été enregistré dans le système mais "
                    "le fichier n'est pas accessible depuis ce navigateur.  \n"
                    "Contactez l'administration si le problème persiste."
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — BUDGET
# ══════════════════════════════════════════════════════════════════════════════

def _render_budget_tab(user: dict) -> None:
    uid     = user["id"]
    my_reqs = _get_my_requests(uid)

    st.markdown("### 💰 Suivi de mon budget IBTIKAR")

    cap  = config.IBTIKAR_BUDGET_CAP
    used = _used_budget(my_reqs)
    pct  = round(min(used / cap * 100, 100), 1) if cap else 0.0
    rem  = max(cap - used, 0)
    col_hex = _budget_colour(pct)

    # ── Summary metrics ───────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📊 Plafond annuel",   f"{cap:,.0f} DZD")
    c2.metric("💸 Engagé",           f"{used:,.0f} DZD")
    c3.metric("✅ Disponible",       f"{rem:,.0f} DZD")
    c4.metric("📈 Taux d'engagement", f"{pct:.1f}%")

    st.divider()

    # ── Progress gauge ────────────────────────────────────────────────────────
    st.progress(pct / 100)
    st.markdown(
        f"<div style='text-align:center; color:{col_hex}; "
        f"font-weight:700; font-size:1.2rem;'>"
        f"{used:,.0f} DZD  /  {cap:,.0f} DZD  ({pct:.1f}%)"
        f"</div>",
        unsafe_allow_html=True,
    )

    if pct >= 90:
        st.error(
            "🚨 **Attention:** Vous approchez du plafond budgétaire annuel. "
            "Contactez l'administration avant de soumettre de nouvelles demandes."
        )
    elif pct >= 70:
        st.warning(
            "⚠️ **Attention:** Plus de 70% de votre budget annuel est engagé."
        )

    st.divider()

    # ── Per-request breakdown ─────────────────────────────────────────────────
    st.markdown("#### 📋 Détail par demande")

    budget_reqs = [
        r for r in my_reqs
        if float(r.get("quote_amount", 0)) > 0
    ]

    if not budget_reqs:
        st.info("Aucune demande avec budget enregistré.")
        return

    for req in sorted(budget_reqs, key=lambda r: r.get("created_at",""), reverse=True):
        status    = req.get("status","")
        amt       = float(req.get("quote_amount", 0))
        form_data = req.get("form_data", {})
        project   = form_data.get("project", {})

        is_active   = status not in {IS.REJECTED, "ARCHIVED"}
        status_icon = config.STATUS_LABELS.get(status, ("📋",))[0]
        amt_colour  = "#27AE60" if is_active else "#7F8C8D"
        strike      = "text-decoration:line-through;" if not is_active else ""

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(
                f"**`{req['id'][:8].upper()}`** — "
                f"{project.get('title','–')[:45]}"
            )
        with col2:
            st.markdown(
                f"<span style='color:{amt_colour}; {strike} font-weight:600;'>"
                f"{amt:,.0f} DZD</span>",
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                f"{status_icon} `{status}`",
                unsafe_allow_html=True,
            )
        st.divider()

    # ── Note ──────────────────────────────────────────────────────────────────
    st.caption(
        f"ℹ️ Le plafond annuel IBTIKAR est fixé à **{cap:,.0f} DZD** "
        f"conformément aux directives DGRSDT. "
        f"Les demandes rejetées ou archivées ne sont pas décomptées."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _render_notifications_tab(user: dict) -> None:
    uid   = user["id"]
    notifs = get_all_notifications_for_user(uid)

    st.markdown("### 🔔 Mes notifications")

    unread = [n for n in notifs if not n.get("read", False)]
    read   = [n for n in notifs if n.get("read",  False)]

    col1, col2 = st.columns([3, 1])
    with col1:
        st.metric("🔔 Non lues", len(unread))
    with col2:
        if unread and st.button(
            "✅ Tout marquer comme lu",
            key                 = "req_mark_all_read",
            use_container_width = True,
        ):
            mark_all_notifications_read_for_user(uid)
            st.rerun()

    st.divider()

    level_icons = {
        "success": "✅", "info": "ℹ️",
        "warning": "⚠️", "error":   "🚫",
    }

    # ── Unread ────────────────────────────────────────────────────────────────
    if unread:
        st.markdown("#### 🔴 Non lues")
        for n in sorted(
            unread,
            key     = lambda x: x.get("created_at", ""),
            reverse = True,
        ):
            level = n.get("level", "info")
            icon  = level_icons.get(level, "🔔")
            with st.container(border=True):
                col_a, col_b = st.columns([5, 1])
                with col_a:
                    st.markdown(f"{icon} **{n.get('title','–')}**")
                    st.write(n.get("message", ""))
                    st.caption(_fmt_date(n.get("created_at", "")))
                with col_b:
                    if st.button(
                        "✓",
                        key  = f"mark_read_{n['id']}",
                        help = "Marquer comme lu",
                    ):
                        mark_notification_read(n["id"])
                        st.rerun()

    # ── Read ──────────────────────────────────────────────────────────────────
    if read:
        with st.expander(
            f"📂 Notifications lues ({len(read)})",
            expanded=False,
        ):
            for n in sorted(
                read,
                key     = lambda x: x.get("created_at", ""),
                reverse = True,
            )[:config.NOTIFICATION_MAX_DISPLAY]:
                level = n.get("level", "info")
                icon  = level_icons.get(level, "🔔")
                st.markdown(
                    f"{icon} **{n.get('title','–')}**  \n"
                    f"_{n.get('message','')}_  \n"
                    f"<span style='font-size:0.72rem; color:#7F8C8D;'>"
                    f"{_fmt_date(n.get('created_at',''))}</span>",
                    unsafe_allow_html=True,
                )
                st.divider()

    if not notifs:
        st.info("Aucune notification pour le moment.")