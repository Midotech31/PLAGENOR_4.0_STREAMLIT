# ui/client_dashboard.py
# ── PLAGENOR 4.0 — Client Dashboard ──────────────────────────────────────────
# Serves  : ROLE_CLIENT (external GENOCLAB clients)
# Scope   : Only their own organisation's requests.
#           Clients CANNOT see other organisations' data, members, or admin panels.
# Channels: GENOCLAB only (IBTIKAR is institutional — no client billing)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime
from typing import Optional

import config
from ui.auth import require_roles
from ui.shared_components import (
    render_sidebar_user,
    render_request_card,
    render_status_badge,
    render_workflow_progress,
    render_empty_state,
    confirm_action,
    resolve_service_name,
)
from core.repository import (
    get_all_active_requests,
    get_all_archived_requests,
    get_all_invoices,
    get_all_documents,
    get_request,
    mark_notification_read,
    get_notifications_for_user_id,
    get_notifications_for_role,
)
from core.workflow_engine  import transition
from core.financial_engine import get_invoice_pdf_path
from core.exceptions       import PlagenorError


# ── Constants ─────────────────────────────────────────────────────────────────
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB


# ── Quote state references ────────────────────────────────────────────────────
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


# ── Status display config ─────────────────────────────────────────────────────
STATUS_CLIENT_LABELS: dict = {
    GenoClabState.SUBMITTED:                 ("🕐", "Soumise — en attente de validation",  "info"),
    GenoClabState.VALIDATION:                ("🔍", "En cours de validation",              "info"),
    GenoClabState.APPROVED:                  ("✅", "Approuvée",                           "success"),
    GenoClabState.REJECTED:                  ("🚫", "Rejetée",                             "error"),
    GenoClabState.QUOTE_DRAFT:               ("📝", "Devis en préparation",                "info"),
    GenoClabState.QUOTE_SENT:                ("📧", "Devis envoyé — en attente de réponse","warning"),
    GenoClabState.QUOTE_VALIDATED_BY_CLIENT: ("🤝", "Devis accepté",                       "success"),
    GenoClabState.QUOTE_REJECTED_BY_CLIENT:  ("🚫", "Devis refusé",                        "error"),
    GenoClabState.INVOICE_GENERATED:         ("🧾", "Facture générée",                     "success"),
    GenoClabState.ASSIGNED:                  ("🧬", "Analyste assigné",                    "info"),
    GenoClabState.ANALYSIS_IN_PROGRESS:      ("🔬", "Analyse en cours",                    "info"),
    GenoClabState.ANALYSIS_FINISHED:         ("✅", "Analyse terminée",                    "success"),
    GenoClabState.REPORT_UPLOADED:           ("📄", "Rapport disponible",                  "success"),
    GenoClabState.COMPLETED:                 ("🏁", "Demande clôturée",                    "success"),
}

# States where client action is required
CLIENT_ACTION_REQUIRED = {
    GenoClabState.QUOTE_SENT,
}

# States visible to client (hide internal draft states)
CLIENT_VISIBLE_STATES = {
    GenoClabState.SUBMITTED,
    GenoClabState.VALIDATION,
    GenoClabState.APPROVED,
    GenoClabState.REJECTED,
    GenoClabState.QUOTE_SENT,
    GenoClabState.QUOTE_VALIDATED_BY_CLIENT,
    GenoClabState.QUOTE_REJECTED_BY_CLIENT,
    GenoClabState.INVOICE_GENERATED,
    GenoClabState.ASSIGNED,
    GenoClabState.ANALYSIS_IN_PROGRESS,
    GenoClabState.ANALYSIS_FINISHED,
    GenoClabState.REPORT_UPLOADED,
    GenoClabState.COMPLETED,
}


# ── Utility helpers ───────────────────────────────────────────────────────────
def _days_since(iso_date: str) -> int:
    if not iso_date:
        return 0
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return max((datetime.utcnow() - dt.replace(tzinfo=None)).days, 0)
    except Exception:
        return 0


def _action_ok(msg: str) -> None:
    st.success(f"✅ {msg}")


def _action_err(e: Exception) -> None:
    st.error(f"❌ {e}")


def _advance(req: dict, to: str, actor: dict, notes: str = "") -> None:
    try:
        transition(request_id=req["id"], to_state=to, actor=actor, notes=notes)
        st.success(f"✅ Action enregistrée.")
        st.cache_data.clear()
        st.rerun()
    except PlagenorError as e:
        st.error(f"❌ {e}")


def _fmt_currency(amount: float) -> str:
    return f"{amount:,.0f} DZD"


def _fmt_date(iso: str) -> str:
    if not iso:
        return "–"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except Exception:
        return iso[:10]


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=15)
def _load_active_requests() -> list:
    return get_all_active_requests()


@st.cache_data(ttl=15)
def _load_archived_requests() -> list:
    return get_all_archived_requests()


@st.cache_data(ttl=15)
def _load_invoices() -> list:
    return get_all_invoices()


@st.cache_data(ttl=15)
def _load_documents() -> list:
    return get_all_documents()


# ── Client-scoped data filters ────────────────────────────────────────────────
def _my_requests(user: dict) -> list:
    """
    Returns all GENOCLAB requests belonging to this client.
    Matches on form_data.requester.email OR organization_id.
    Filters to CLIENT_VISIBLE_STATES only.
    """
    uid    = user.get("id", "")
    email  = user.get("email", "")
    org_id = user.get("organization_id", "")

    all_reqs = _load_active_requests() + _load_archived_requests()

    result = []
    for r in all_reqs:
        if r.get("channel") != CHANNEL_GENOCLAB:
            continue
        if r.get("status") not in CLIENT_VISIBLE_STATES:
            continue

        req_data  = r.get("form_data", {})
        requester = req_data.get("requester", {})

        # Match by submitter user_id, email, or org
        if (
            r.get("submitted_by_user_id") == uid
            or requester.get("email") == email
            or (org_id and r.get("organization_id") == org_id)
            or (org_id and requester.get("organization_id") == org_id)
        ):
            result.append(r)

    return sorted(result, key=lambda r: r.get("created_at", ""), reverse=True)


def _my_invoices(user: dict, requests: list) -> list:
    """Returns invoices for this client's requests."""
    req_ids  = {r["id"] for r in requests}
    invoices = _load_invoices()
    return [i for i in invoices if i.get("request_id") in req_ids]


def _my_documents(requests: list) -> list:
    """Returns documents (reports) for this client's requests."""
    req_ids = {r["id"] for r in requests}
    docs    = _load_documents()
    return [d for d in docs if d.get("request_id") in req_ids]


# ── Request selector widget ───────────────────────────────────────────────────
def _request_selector(requests: list, key: str) -> Optional[dict]:
    if not requests:
        return None
    opts = {}
    for r in requests:
        status = r.get("status", "")
        icon, _, _ = STATUS_CLIENT_LABELS.get(status, ("📋", status, "info"))
        label = (
            f"{icon} {r['id'][:8]} — "
            f"{resolve_service_name(r.get('service_id',''))} "
            f"({_fmt_date(r.get('created_at',''))})"
        )
        opts[label] = r
    sel = st.selectbox("Sélectionner une demande", list(opts.keys()), key=key)
    return opts[sel]


# ── Status display helper ─────────────────────────────────────────────────────
def _render_status_card(req: dict) -> None:
    status          = req.get("status", "")
    icon, label, level = STATUS_CLIENT_LABELS.get(
        status, ("📋", status, "info")
    )
    action_required = status in CLIENT_ACTION_REQUIRED

    if action_required:
        st.warning(
            f"⚡ **Action requise** — {icon} {label}  \n"
            f"Votre réponse est attendue pour cette demande."
        )
    elif level == "success":
        st.success(f"{icon} **Statut:** {label}")
    elif level == "error":
        st.error(f"{icon} **Statut:** {label}")
    else:
        st.info(f"{icon} **Statut:** {label}")


# ── Tab: My Requests ──────────────────────────────────────────────────────────
def _tab_my_requests(user: dict, requests: list) -> None:
    st.markdown("## 📋 Mes demandes")

    if not requests:
        render_empty_state(
            "📭", "Aucune demande",
            "Vous n'avez pas encore soumis de demande GENOCLAB.",
        )
        return

    # Summary counters
    total     = len(requests)
    active    = sum(1 for r in requests if r.get("status") not in
                    {GenoClabState.COMPLETED, GenoClabState.REJECTED,
                     GenoClabState.QUOTE_REJECTED_BY_CLIENT})
    completed = sum(1 for r in requests if r.get("status") == GenoClabState.COMPLETED)
    pending   = sum(1 for r in requests if r.get("status") in CLIENT_ACTION_REQUIRED)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📋 Total demandes",    total)
    col2.metric("🔄 En cours",          active)
    col3.metric("✅ Clôturées",          completed)
    col4.metric("⚡ Action requise",     pending,
                delta     = "Répondre maintenant" if pending else None,
                delta_color = "inverse" if pending else "off")

    st.divider()

    # Filter controls
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        statuses = sorted({r.get("status", "") for r in requests})
        st_filter = st.selectbox(
            "Filtrer par statut", ["Tous"] + statuses, key="cl_st"
        )
    with col_f2:
        sort_by = st.selectbox(
            "Trier par",
            ["Date (récent)", "Date (ancien)", "Statut"],
            key = "cl_sort",
        )

    filtered = requests
    if st_filter != "Tous":
        filtered = [r for r in filtered if r.get("status") == st_filter]

    if sort_by == "Date (récent)":
        filtered = sorted(filtered, key=lambda r: r.get("created_at", ""), reverse=True)
    elif sort_by == "Date (ancien)":
        filtered = sorted(filtered, key=lambda r: r.get("created_at", ""))
    else:
        filtered = sorted(filtered, key=lambda r: r.get("status", ""))

    st.caption(f"Affichage: **{len(filtered)}** / {total} demande(s)")
    st.divider()

    for req in filtered:
        status          = req.get("status", "")
        icon, label, _  = STATUS_CLIENT_LABELS.get(status, ("📋", status, "info"))
        svc_name        = resolve_service_name(req.get("service_id", ""))
        created         = _fmt_date(req.get("created_at", ""))
        days            = _days_since(req.get("created_at", ""))
        action_required = status in CLIENT_ACTION_REQUIRED

        with st.container():
            col1, col2, col3 = st.columns([4, 3, 2])
            with col1:
                st.markdown(
                    f"**🧬 {svc_name}**  \n"
                    f"Réf: `{req['id'][:8]}`  \n"
                    f"Soumise le: {created}"
                )
            with col2:
                st.markdown(
                    f"{icon} **{label}**  \n"
                    f"{'⚡ **Action requise**' if action_required else f'Depuis: {days} jour(s)'}"
                )
            with col3:
                if action_required:
                    if st.button(
                        "⚡ Répondre",
                        key  = f"goto_quote_{req['id']}",
                        type = "primary",
                        use_container_width = True,
                    ):
                        st.session_state["active_tab_hint"] = "quotes"
                        st.rerun()
                else:
                    st.caption(f"Aucune action requise")
            st.divider()


# ── Tab: Quotes ───────────────────────────────────────────────────────────────
def _tab_quotes(user: dict, requests: list) -> None:
    st.markdown("## 💵 Mes devis")

    # Quotes awaiting client response
    pending_quotes = [
        r for r in requests if r.get("status") == GenoClabState.QUOTE_SENT
    ]
    # All quotes (sent + responded)
    all_quote_reqs = [
        r for r in requests
        if r.get("status") in {
            GenoClabState.QUOTE_SENT,
            GenoClabState.QUOTE_VALIDATED_BY_CLIENT,
            GenoClabState.QUOTE_REJECTED_BY_CLIENT,
            GenoClabState.INVOICE_GENERATED,
            GenoClabState.ASSIGNED,
            GenoClabState.ANALYSIS_IN_PROGRESS,
            GenoClabState.ANALYSIS_FINISHED,
            GenoClabState.REPORT_UPLOADED,
            GenoClabState.COMPLETED,
        }
        if r.get("quote_amount") or r.get("quote_amount") == 0
    ]

    # ── Action Required Banner ────────────────────────────────────────────────
    if pending_quotes:
        st.error(
            f"⚡ **{len(pending_quotes)} devis en attente de votre réponse.**  \n"
            f"Veuillez accepter ou refuser chaque devis ci-dessous."
        )
        st.divider()

        for req in pending_quotes:
            _render_quote_response_panel(req, user)
        st.divider()

    # ── Quote History ─────────────────────────────────────────────────────────
    responded = [
        r for r in all_quote_reqs
        if r.get("status") not in {GenoClabState.QUOTE_SENT}
        and (r.get("quote_amount") is not None)
    ]

    if responded:
        st.markdown("### 📋 Historique des devis")
        for req in responded:
            vat_rate     = float(getattr(config, "VAT_RATE", 0.19))
            quote_ht     = float(req.get("quote_amount", 0))
            vat          = round(quote_ht * vat_rate, 2)
            ttc          = round(quote_ht + vat, 2)
            status       = req.get("status", "")
            icon, label, _ = STATUS_CLIENT_LABELS.get(status, ("📋", status, "info"))
            svc_name     = resolve_service_name(req.get("service_id", ""))

            with st.container():
                col1, col2, col3 = st.columns([4, 3, 2])
                with col1:
                    st.markdown(
                        f"**{svc_name}** — `{req['id'][:8]}`  \n"
                        f"Soumise: {_fmt_date(req.get('created_at', ''))}"
                    )
                with col2:
                    st.markdown(
                        f"**HT:** {_fmt_currency(quote_ht)}  \n"
                        f"**TTC:** {_fmt_currency(ttc)}"
                    )
                with col3:
                    st.markdown(f"{icon} **{label}**")
                st.divider()

    if not pending_quotes and not responded:
        render_empty_state(
            "💵", "Aucun devis reçu",
            "Vos devis apparaîtront ici une fois votre demande approuvée.",
        )


def _render_quote_response_panel(req: dict, actor: dict) -> None:
    vat_rate = float(getattr(config, "VAT_RATE", 0.19))
    quote_ht = float(req.get("quote_amount", 0))
    vat      = round(quote_ht * vat_rate, 2)
    ttc      = round(quote_ht + vat, 2)
    svc_name = resolve_service_name(req.get("service_id", ""))

    with st.container():
        st.markdown(f"### 💵 Devis — {svc_name} (`{req['id'][:8]}`)")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                f"**Service:** {svc_name}  \n"
                f"**Réf demande:** `{req['id'][:8]}`  \n"
                f"**Date soumission:** {_fmt_date(req.get('created_at', ''))}"
            )
        with col2:
            st.markdown(
                f"**Montant HT:** {_fmt_currency(quote_ht)}  \n"
                f"**TVA ({vat_rate * 100:.0f}%):** {_fmt_currency(vat)}  \n"
                f"**Total TTC:** **{_fmt_currency(ttc)}**"
            )

        # Quote notes from admin
        quote_notes = req.get("quote_notes", "")
        if quote_notes:
            st.info(f"📝 **Note du laboratoire:** {quote_notes}")

        st.markdown("#### Votre réponse")
        st.caption(
            "En acceptant ce devis, vous autorisez le laboratoire GENOCLAB "
            "à procéder à l'analyse et vous vous engagez à régler le montant TTC indiqué."
        )

        col_accept, col_reject = st.columns(2)

        with col_accept:
            st.markdown(
                f"✅ **Accepter le devis**  \n"
                f"Montant: **{_fmt_currency(ttc)} TTC**"
            )
            if confirm_action(
                key     = f"accept_quote_{req['id']}",
                label   = f"✅ J'accepte le devis ({_fmt_currency(ttc)} TTC)",
                message = (
                    f"Confirmer l'acceptation du devis ?  \n"
                    f"Montant TTC: **{_fmt_currency(ttc)}**  \n\n"
                    f"Une facture sera générée automatiquement."
                ),
            ):
                _advance(req, GenoClabState.QUOTE_VALIDATED_BY_CLIENT, actor)

        with col_reject:
            st.markdown("🚫 **Refuser le devis**")
            reject_reason = st.text_input(
                "Motif du refus *",
                key         = f"reject_reason_{req['id']}",
                placeholder = "Ex: Budget insuffisant pour le moment.",
            )
            if confirm_action(
                key     = f"reject_quote_{req['id']}",
                label   = "🚫 Je refuse le devis",
                message = (
                    f"Confirmer le refus du devis ?  \n"
                    f"La demande sera clôturée."
                ),
                danger  = True,
            ):
                if not reject_reason.strip():
                    st.warning("⚠️ Le motif du refus est obligatoire.")
                else:
                    _advance(
                        req,
                        GenoClabState.QUOTE_REJECTED_BY_CLIENT,
                        actor,
                        notes = reject_reason,
                    )

        st.divider()


# ── Tab: Invoices ─────────────────────────────────────────────────────────────
def _tab_invoices(user: dict, requests: list) -> None:
    st.markdown("## 🧾 Mes factures")

    invoices = _my_invoices(user, requests)

    if not invoices:
        render_empty_state(
            "🧾", "Aucune facture",
            "Vos factures apparaîtront ici après acceptation d'un devis.",
        )
        return

    # Summary
    total_ttc = sum(float(i.get("total_ttc", 0)) for i in invoices)
    paid      = sum(1 for i in invoices if i.get("paid"))
    unpaid    = len(invoices) - paid

    col1, col2, col3 = st.columns(3)
    col1.metric("🧾 Total factures",  len(invoices))
    col2.metric("✅ Réglées",          paid)
    col3.metric("⏳ En attente",        unpaid)
    st.caption(f"Montant total TTC: **{_fmt_currency(total_ttc)}**")
    st.divider()

    for inv in sorted(
        invoices,
        key     = lambda i: i.get("created_at", ""),
        reverse = True,
    ):
        inv_number  = inv.get("invoice_number", inv["id"][:8])
        inv_ht      = float(inv.get("total_ht",  0))
        inv_vat     = float(inv.get("total_vat", 0))
        inv_ttc     = float(inv.get("total_ttc", 0))
        inv_paid    = inv.get("paid", False)
        inv_date    = _fmt_date(inv.get("created_at", ""))
        paid_at     = _fmt_date(inv.get("paid_at", ""))
        req_id      = inv.get("request_id", "")
        svc_name    = ""
        if req_id:
            req_obj  = get_request(req_id)
            svc_name = resolve_service_name(
                req_obj.get("service_id", "") if req_obj else ""
            )

        with st.container():
            col1, col2, col3 = st.columns([4, 3, 2])
            with col1:
                st.markdown(
                    f"**🧾 Facture N° {inv_number}**  \n"
                    f"Service: {svc_name or '–'}  \n"
                    f"Émise le: {inv_date}"
                )
            with col2:
                st.markdown(
                    f"**HT:** {_fmt_currency(inv_ht)}  \n"
                    f"**TVA:** {_fmt_currency(inv_vat)}  \n"
                    f"**TTC:** **{_fmt_currency(inv_ttc)}**"
                )
            with col3:
                if inv_paid:
                    st.success(f"✅ Réglée  \n{paid_at}")
                else:
                    st.warning("⏳ En attente  \nde règlement")

            # PDF download
            pdf_path = inv.get("pdf_path", "")
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label            = f"📥 Télécharger la facture PDF",
                        data             = f.read(),
                        file_name        = f"facture_{inv_number}.pdf",
                        mime             = "application/pdf",
                        key              = f"dl_inv_{inv['id']}",
                        use_container_width = True,
                    )
            else:
                st.caption("📄 PDF en cours de génération...")

            # Integrity hash
            h = inv.get("hash_short", inv.get("integrity_hash", "")[:12])
            if h:
                st.caption(f"🔒 Intégrité: `{h}`")

            st.divider()


# ── Tab: Reports ──────────────────────────────────────────────────────────────
def _tab_reports(user: dict, requests: list) -> None:
    st.markdown("## 📄 Mes rapports d'analyse")

    # Requests with reports available
    with_reports = [
        r for r in requests
        if r.get("status") in {
            GenoClabState.REPORT_UPLOADED,
            GenoClabState.COMPLETED,
        }
    ]

    if not with_reports:
        render_empty_state(
            "📄", "Aucun rapport disponible",
            "Vos rapports d'analyse apparaîtront ici une fois l'analyse terminée.",
        )
        return

    docs = _my_documents(requests)

    st.caption(
        f"**{len(with_reports)}** demande(s) avec rapport disponible."
    )
    st.divider()

    for req in with_reports:
        svc_name = resolve_service_name(req.get("service_id", ""))
        status   = req.get("status", "")
        icon, label, _ = STATUS_CLIENT_LABELS.get(status, ("📋", status, "info"))

        req_docs = [d for d in docs if d.get("request_id") == req["id"]]

        with st.expander(
            f"📄 **{svc_name}** — `{req['id'][:8]}` — {icon} {label}",
            expanded = (status == GenoClabState.REPORT_UPLOADED),
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    f"**Service:** {svc_name}  \n"
                    f"**Soumise:** {_fmt_date(req.get('created_at', ''))}"
                )
                form_data = req.get("form_data", {})
                requester = form_data.get("requester", {})
                st.markdown(
                    f"**Demandeur:** {requester.get('full_name', '–')}  \n"
                    f"**Institution:** {requester.get('institution', '–')}"
                )
            with col2:
                analyst = req.get("assigned_member_name") or "–"
                st.markdown(
                    f"**Analyste:** {analyst}  \n"
                    f"**Clôturée:** {_fmt_date(req.get('updated_at', ''))}"
                )

            # Analysis notes (read-only for client)
            analysis_notes = req.get("analysis_notes", [])
            if analysis_notes:
                st.markdown("**Notes d'analyse:**")
                for note in analysis_notes[-3:]:
                    st.markdown(
                        f"> {note.get('text', '–')}  \n"
                        f"> _{_fmt_date(note.get('timestamp', ''))}_"
                    )

            st.markdown("#### 📥 Télécharger le rapport")

            if req_docs:
                for doc in req_docs:
                    doc_path = doc.get("path", "")
                    doc_name = doc.get("filename", f"rapport_{req['id'][:8]}.docx")
                    doc_type = doc.get("type", "REPORT")

                    if doc_path and os.path.exists(doc_path):
                        with open(doc_path, "rb") as f:
                            mime = (
                                "application/vnd.openxmlformats-officedocument"
                                ".wordprocessingml.document"
                                if doc_name.endswith(".docx")
                                else "application/octet-stream"
                            )
                            st.download_button(
                                label               = f"📥 {doc_name}",
                                data                = f.read(),
                                file_name           = doc_name,
                                mime                = mime,
                                key                 = f"dl_doc_{doc['id']}",
                                use_container_width = True,
                            )
                    else:
                        st.caption(f"📄 {doc_name} — en cours de préparation.")
            else:
                # Check if report_path is stored on the request directly
                report_path = req.get("report_path", "")
                if report_path and os.path.exists(report_path):
                    with open(report_path, "rb") as f:
                        st.download_button(
                            label               = f"📥 Rapport d'analyse — {svc_name}",
                            data                = f.read(),
                            file_name           = f"rapport_{req['id'][:8]}.docx",
                            mime                = (
                                "application/vnd.openxmlformats-officedocument"
                                ".wordprocessingml.document"
                            ),
                            key                 = f"dl_report_{req['id']}",
                            use_container_width = True,
                        )
                else:
                    st.info(
                        "📄 Le rapport est en cours de finalisation.  \n"
                        "Revenez dans quelques instants."
                    )


# ── Tab: Tracking ─────────────────────────────────────────────────────────────
def _tab_tracking(user: dict, requests: list) -> None:
    st.markdown("## 🔍 Suivi détaillé d'une demande")

    if not requests:
        render_empty_state(
            "🔍", "Aucune demande à suivre",
            "Vos demandes apparaîtront ici après soumission.",
        )
        return

    req = _request_selector(requests, "tracking_sel")
    if not req:
        return

    status   = req.get("status", "")
    svc_name = resolve_service_name(req.get("service_id", ""))

    # Header
    st.markdown(f"### 🧬 {svc_name}")
    _render_status_card(req)
    render_workflow_progress(CHANNEL_GENOCLAB, status)
    st.divider()

    # Request details
    col1, col2 = st.columns(2)
    form_data  = req.get("form_data", {})
    requester  = form_data.get("requester", {})
    pricing    = form_data.get("pricing",   {})

    with col1:
        st.markdown("#### 📋 Informations de la demande")
        st.markdown(
            f"**Réf:** `{req['id'][:8]}`  \n"
            f"**Service:** {svc_name}  \n"
            f"**Canal:** `{req.get('channel', '–')}`  \n"
            f"**Soumise le:** {_fmt_date(req.get('created_at', ''))}"
        )
        if requester:
            st.markdown(
                f"**Demandeur:** {requester.get('full_name', '–')}  \n"
                f"**Institution:** {requester.get('institution', '–')}  \n"
                f"**Email:** {requester.get('email', '–')}"
            )

    with col2:
        st.markdown("#### 💰 Informations financières")
        quote_ht = float(req.get("quote_amount", 0))
        if quote_ht > 0:
            vat_rate = float(getattr(config, "VAT_RATE", 0.19))
            vat      = round(quote_ht * vat_rate, 2)
            ttc      = round(quote_ht + vat, 2)
            st.markdown(
                f"**Montant HT:** {_fmt_currency(quote_ht)}  \n"
                f"**TVA ({vat_rate * 100:.0f}%):** {_fmt_currency(vat)}  \n"
                f"**Total TTC:** **{_fmt_currency(ttc)}**"
            )
        elif pricing.get("subtotal"):
            est = float(pricing.get("subtotal", 0))
            st.markdown(
                f"**Estimation initiale:** {_fmt_currency(est)} HT  \n"
                f"_(Le devis définitif sera envoyé après validation)_"
            )
        else:
            st.caption("Aucune information financière disponible.")

        # Appointment info
        appt = req.get("appointment", {})
        if appt:
            st.markdown("#### 📅 Rendez-vous")
            st.markdown(
                f"**Date:** {appt.get('date', '–')}  \n"
                f"**Heure:** {appt.get('time', '–')}  \n"
                f"**Note:** {appt.get('note', '–')}"
            )

    st.divider()

    # Timeline / History
    st.markdown("#### 📅 Historique des transitions")
    history = req.get("status_history", [])
    if history:
        for entry in reversed(history):
            ets   = entry.get("timestamp", "")[:16]
            estat = entry.get("to_state", entry.get("state", "–"))
            enote = entry.get("notes", "")
            eicon, elabel, _ = STATUS_CLIENT_LABELS.get(estat, ("📋", estat, "info"))
            st.markdown(
                f"- `{ets}` — {eicon} **{elabel}**"
                + (f"  \n  _{enote}_" if enote else "")
            )
    else:
        st.caption("Historique non disponible.")

    # Action required — show quote panel inline
    if status == GenoClabState.QUOTE_SENT:
        st.divider()
        st.markdown("### ⚡ Action requise — Répondre au devis")
        _render_quote_response_panel(req, user)


# ── Tab: Notifications ────────────────────────────────────────────────────────
def _tab_notifications(user: dict) -> None:
    st.markdown("## 🔔 Mes notifications")

    try:
        uid    = user.get("id", "")
        role   = user.get("role", "")

        role_notifs = get_notifications_for_role(role)
        user_notifs = get_notifications_for_user_id(uid)

        # Deduplicate
        seen_ids: set = set()
        all_notifs: list = []
        for n in role_notifs + user_notifs:
            nid = n.get("id", "")
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                all_notifs.append(n)

        all_notifs = sorted(
            all_notifs,
            key     = lambda n: n.get("created_at", ""),
            reverse = True,
        )

        if not all_notifs:
            render_empty_state(
                "🔔", "Aucune notification",
                "Vous recevrez des notifications pour chaque mise à jour de vos demandes.",
            )
            return

        unread_count = sum(1 for n in all_notifs if not n.get("read"))
        st.caption(
            f"**{len(all_notifs)}** notification(s) | "
            f"**{unread_count}** non lue(s)"
        )

        if unread_count > 0:
            if st.button(
                "✅ Tout marquer comme lu",
                key = "mark_all_read",
            ):
                for n in all_notifs:
                    if not n.get("read"):
                        try:
                            mark_notification_read(n["id"])
                        except Exception:
                            pass
                st.cache_data.clear()
                st.rerun()

        st.divider()

        for notif in all_notifs[:50]:
            nid     = notif.get("id", "")
            title   = notif.get("title", "Notification")
            message = notif.get("message", "")
            level   = notif.get("level", "info")
            is_read = notif.get("read", False)
            n_date  = _fmt_date(notif.get("created_at", ""))

            col_dot, col_body, col_action = st.columns([1, 8, 2])
            with col_dot:
                st.markdown("⚪" if is_read else "🔵")
            with col_body:
                weight = "normal" if is_read else "bold"
                st.markdown(
                    f"**{title}**  \n"
                    f"{message}  \n"
                    f"<small style='color:#7f8c8d'>{n_date}</small>",
                    unsafe_allow_html = True,
                )
            with col_action:
                if not is_read:
                    if st.button("Lu", key=f"read_{nid}"):
                        try:
                            mark_notification_read(nid)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception:
                            pass
            st.divider()

    except Exception as e:
        st.error(f"Erreur lors du chargement des notifications: {e}")


# ── Tab: Profile ──────────────────────────────────────────────────────────────
def _tab_profile(user: dict, requests: list) -> None:
    st.markdown("## 👤 Mon profil")

    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown("### 📋 Informations du compte")
        st.markdown(
            f"**Nom d'utilisateur:** `{user.get('username', '–')}`  \n"
            f"**Rôle:** `{user.get('role', '–')}`  \n"
            f"**Organisation:** `{user.get('organization_id', '–')}`  \n"
            f"**Email:** {user.get('email', '–')}"
        )

    with col2:
        st.markdown("### 📊 Statistiques")
        total     = len(requests)
        completed = sum(1 for r in requests
                        if r.get("status") == GenoClabState.COMPLETED)
        active    = sum(1 for r in requests
                        if r.get("status") not in {
                            GenoClabState.COMPLETED,
                            GenoClabState.REJECTED,
                            GenoClabState.QUOTE_REJECTED_BY_CLIENT,
                        })

        st.metric("📋 Total demandes",  total)
        st.metric("🔄 Demandes actives", active)
        st.metric("✅ Demandes clôturées", completed)

    st.divider()

    # Services used
    if requests:
        st.markdown("### 🧬 Services utilisés")
        svc_counts: dict = {}
        for r in requests:
            svc = resolve_service_name(r.get("service_id", ""))
            svc_counts[svc] = svc_counts.get(svc, 0) + 1
        for svc, count in sorted(
            svc_counts.items(), key=lambda x: x[1], reverse=True
        ):
            st.markdown(f"- **{svc}**: {count} demande(s)")

    st.divider()

    # Contact
    st.markdown("### 📞 Support GENOCLAB")
    st.info(
        "Pour toute question concernant vos demandes ou factures, "
        "contactez le laboratoire GENOCLAB:  \n\n"
        "📧 **mohamed.merzoug.essbo@gmail.com**  \n"
        "🏛️ ESSBO — Oran, Algérie"
    )


# ── Entry point ───────────────────────────────────────────────────────────────
def render() -> None:
    user = require_roles(config.ROLE_CLIENT)
    render_sidebar_user(user)

    st.title("🧬 PLAGENOR 4.0 — Espace Client GENOCLAB")
    st.caption(
        f"Connecté en tant que: **{user.get('username')}** "
        f"| Rôle: `{user.get('role')}`"
    )

    # Load all client-scoped data once
    requests = _my_requests(user)
    invoices = _my_invoices(user, requests)

    # KPI row
    pending_quotes = sum(
        1 for r in requests if r.get("status") == GenoClabState.QUOTE_SENT
    )
    unpaid_invoices = sum(
        1 for i in invoices if not i.get("paid")
    )
    active_requests = sum(
        1 for r in requests
        if r.get("status") not in {
            GenoClabState.COMPLETED,
            GenoClabState.REJECTED,
            GenoClabState.QUOTE_REJECTED_BY_CLIENT,
        }
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📋 Demandes actives",   active_requests)
    col2.metric("💵 Devis en attente",   pending_quotes,
                delta       = "Action requise" if pending_quotes else None,
                delta_color = "inverse" if pending_quotes else "off")
    col3.metric("🧾 Factures non réglées", unpaid_invoices)
    col4.metric("📄 Rapports disponibles",
                sum(1 for r in requests
                    if r.get("status") in {
                        GenoClabState.REPORT_UPLOADED,
                        GenoClabState.COMPLETED,
                    }))

    # Alert banner for pending quotes
    if pending_quotes:
        st.warning(
            f"⚡ **{pending_quotes} devis en attente de votre réponse.** "
            f"Rendez-vous dans l'onglet **💵 Devis** pour répondre."
        )

    st.divider()

    tabs = st.tabs([
        "📋 Mes demandes",
        "💵 Devis",
        "🧾 Factures",
        "📄 Rapports",
        "🔍 Suivi",
        "🔔 Notifications",
        "👤 Mon profil",
    ])

    with tabs[0]: _tab_my_requests(user, requests)
    with tabs[1]: _tab_quotes(user, requests)
    with tabs[2]: _tab_invoices(user, requests)
    with tabs[3]: _tab_reports(user, requests)
    with tabs[4]: _tab_tracking(user, requests)
    with tabs[5]: _tab_notifications(user)
    with tabs[6]: _tab_profile(user, requests)