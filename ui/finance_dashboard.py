# ui/finance_dashboard.py
# ── PLAGENOR 4.0 — Finance Dashboard ─────────────────────────────────────────
# Serves  : ROLE_FINANCE
# Scope   : Invoice management, payment recording, financial reporting,
#           revenue analytics, VAT summaries, overdue tracking, CSV export.
# Channels: Both IBTIKAR (budget tracking) and GENOCLAB (billing)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import io
from datetime import datetime, date
from typing import Optional

import streamlit as st

import config
from ui.auth import require_roles
from ui.shared_components import (
    render_sidebar_user,
    render_empty_state,
    render_status_badge,
    render_kpi_row,
    render_budget_progress,
    confirm_action,
    resolve_service_name,
    resolve_username,
    fmt_currency,
    fmt_date,
    fmt_datetime,
    time_ago,
    paginate,
    render_pagination_controls,
)
from core.repository import (
    get_all_invoices,
    get_all_active_requests,
    get_all_archived_requests,
    get_all_audit_logs,
    get_invoice,
    save_invoice,
    get_request,
    get_service,
)
from core.financial_engine import (
    record_payment,
    get_revenue_summary,
    get_vat_summary,
    get_overdue_invoices,
    verify_invoice_integrity,
    regenerate_invoice_pdf,
)
from core.exceptions import PlagenorError, FinancialError


# ── Constants ─────────────────────────────────────────────────────────────────
CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB
VAT_RATE         = float(getattr(config, "VAT_RATE", 0.19))

MONTH_NAMES_FR = {
    1: "Janvier",   2: "Février",   3: "Mars",
    4: "Avril",     5: "Mai",       6: "Juin",
    7: "Juillet",   8: "Août",      9: "Septembre",
    10: "Octobre",  11: "Novembre", 12: "Décembre",
}


# ── Utility helpers ───────────────────────────────────────────────────────────
def _action_ok(msg: str) -> None:
    st.success(f"✅ {msg}")


def _action_err(e: Exception) -> None:
    st.error(f"❌ {e}")


def _days_since(iso_date: str) -> int:
    if not iso_date:
        return 0
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return max((datetime.utcnow() - dt.replace(tzinfo=None)).days, 0)
    except Exception:
        return 0


def _invoice_year(inv: dict) -> Optional[int]:
    try:
        return datetime.fromisoformat(
            inv.get("created_at", "").replace("Z", "+00:00")
        ).year
    except Exception:
        return None


def _invoice_month(inv: dict) -> Optional[int]:
    try:
        return datetime.fromisoformat(
            inv.get("created_at", "").replace("Z", "+00:00")
        ).month
    except Exception:
        return None


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=10)
def _load_invoices() -> list:
    return get_all_invoices()


@st.cache_data(ttl=10)
def _load_all_requests() -> list:
    return get_all_active_requests() + get_all_archived_requests()


@st.cache_data(ttl=30)
def _load_audit_logs() -> list:
    return get_all_audit_logs()


# ── Invoice enrichment ────────────────────────────────────────────────────────
def _enrich_invoice(inv: dict) -> dict:
    """
    Adds display fields to an invoice dict without modifying the stored record.
    Adds: svc_name, requester_name, requester_email, channel,
          overdue (bool), days_overdue (int), integrity_ok (bool).
    """
    enriched = dict(inv)
    req_id   = inv.get("request_id", "")
    req_obj  = get_request(req_id) if req_id else None

    enriched["svc_name"] = resolve_service_name(
        req_obj.get("service_id", "") if req_obj else inv.get("service_id", "")
    )
    enriched["channel"] = (
        req_obj.get("channel", inv.get("channel", "–"))
        if req_obj else inv.get("channel", "–")
    )

    requester = (
        req_obj.get("form_data", {}).get("requester", {})
        if req_obj else {}
    )
    enriched["requester_name"]  = (
        inv.get("client_name")
        or requester.get("full_name", "–")
    )
    enriched["requester_email"] = (
        inv.get("client_email")
        or requester.get("email", "–")
    )
    enriched["institution"] = (
        inv.get("institution")
        or requester.get("institution", "–")
    )

    # Overdue: unpaid invoices older than 30 days
    if not inv.get("paid"):
        days = _days_since(inv.get("created_at", ""))
        enriched["overdue"]      = days > 30
        enriched["days_overdue"] = days
    else:
        enriched["overdue"]      = False
        enriched["days_overdue"] = 0

    # Integrity check
    enriched["integrity_ok"] = verify_invoice_integrity(inv)

    return enriched


# ── Invoice card renderer ─────────────────────────────────────────────────────
def _render_invoice_card(inv: dict) -> None:
    """Renders a styled HTML card for an enriched invoice dict."""
    paid      = inv.get("paid", False)
    overdue   = inv.get("overdue", False)
    channel   = inv.get("channel", "–")
    integrity = inv.get("integrity_ok", True)

    if paid:
        border_color = "#27AE60"
        status_icon  = "✅"
        status_label = "Réglée"
        status_css   = "color:#27AE60;"
    elif overdue:
        border_color = "#E74C3C"
        status_icon  = "🔴"
        status_label = f"En retard ({inv.get('days_overdue',0)}j)"
        status_css   = "color:#E74C3C; font-weight:700;"
    else:
        border_color = "#F39C12"
        status_icon  = "⏳"
        status_label = "En attente"
        status_css   = "color:#F39C12;"

    channel_color = "#1B4F72" if channel == CHANNEL_IBTIKAR else "#1ABC9C"
    integrity_badge = (
        '<span style="color:#27AE60; font-size:0.75rem;">🔒 Intègre</span>'
        if integrity else
        '<span style="color:#E74C3C; font-size:0.75rem;">⚠️ Hash invalide</span>'
    )

    st.markdown(
        f"""
        <div style="
            background:#ffffff;
            border:1px solid #e0e8f0;
            border-left:5px solid {border_color};
            border-radius:10px;
            padding:14px 18px;
            margin-bottom:6px;
            box-shadow:0 2px 6px rgba(0,0,0,0.05);
        ">
            <div style="display:flex;
                        justify-content:space-between;
                        align-items:flex-start;">
                <div>
                    <span style="font-weight:700; color:#1B4F72; font-size:1rem;">
                        🧾 {inv.get('invoice_number', inv['id'][:8])}
                    </span>
                    &nbsp;
                    <span style="background:{channel_color}; color:white;
                                 padding:2px 8px; border-radius:10px;
                                 font-size:0.72rem; font-weight:700;">
                        {channel}
                    </span>
                    &nbsp;{integrity_badge}
                </div>
                <span style="{status_css} font-size:0.85rem;">
                    {status_icon} {status_label}
                </span>
            </div>
            <div style="margin-top:8px; font-size:0.85rem; color:#2c3e50;">
                👤 <b>{inv.get('requester_name','–')}</b>
                &nbsp;|&nbsp; 🏛️ {inv.get('institution','–')}
                &nbsp;|&nbsp; 🔬 {inv.get('svc_name','–')}
            </div>
            <div style="margin-top:6px; font-size:0.85rem; color:#2c3e50;">
                💵 HT: <b>{fmt_currency(float(inv.get('total_ht',0)))}</b>
                &nbsp;|&nbsp;
                TVA ({VAT_RATE*100:.0f}%): {fmt_currency(float(inv.get('total_vat',0)))}
                &nbsp;|&nbsp;
                TTC: <b style="color:#1B4F72;">
                    {fmt_currency(float(inv.get('total_ttc',0)))}
                </b>
            </div>
            <div style="margin-top:4px; font-size:0.78rem; color:#7f8c8d;">
                📅 Émise: {fmt_date(inv.get('created_at',''))}
                {"&nbsp;|&nbsp; 💳 Payée le: " + fmt_date(inv.get('paid_at',''))
                 if paid else ""}
                {"&nbsp;|&nbsp; Réf: " + str(inv.get('payment_ref',''))
                 if inv.get('payment_ref') else ""}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Invoice List
# ══════════════════════════════════════════════════════════════════════════════

def _tab_invoices(actor: dict) -> None:
    st.markdown("## 🧾 Toutes les factures")

    raw_invoices = _load_invoices()
    if not raw_invoices:
        render_empty_state(
            "🧾", "Aucune facture",
            "Les factures apparaîtront ici après validation des devis GENOCLAB "
            "ou approbation des budgets IBTIKAR.",
        )
        return

    invoices = [_enrich_invoice(i) for i in raw_invoices]

    # ── KPI row ───────────────────────────────────────────────────────────────
    paid_invs   = [i for i in invoices if i.get("paid")]
    unpaid_invs = [i for i in invoices if not i.get("paid")]
    overdue_invs= [i for i in invoices if i.get("overdue")]
    total_ttc   = sum(float(i.get("total_ttc", 0)) for i in invoices)
    enc_ttc     = sum(float(i.get("total_ttc", 0)) for i in paid_invs)
    pending_ttc = sum(float(i.get("total_ttc", 0)) for i in unpaid_invs)

    render_kpi_row([
        {"label": "🧾 Total factures",  "value": len(invoices)},
        {"label": "✅ Réglées",         "value": len(paid_invs),
         "delta": f"{enc_ttc:,.0f} DZD"},
        {"label": "⏳ En attente",      "value": len(unpaid_invs),
         "delta": f"{pending_ttc:,.0f} DZD"},
        {"label": "🔴 En retard",       "value": len(overdue_invs)},
        {"label": "💰 CA Total TTC",    "value": f"{total_ttc:,.0f} DZD"},
        {"label": "💳 Encaissé TTC",    "value": f"{enc_ttc:,.0f} DZD",
         "delta": f"{enc_ttc/total_ttc*100:.0f}%" if total_ttc else None},
    ])
    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        status_filter = st.selectbox(
            "Statut",
            ["Toutes", "✅ Réglées", "⏳ Non réglées", "🔴 En retard"],
            key="inv_status_filter",
        )
    with col2:
        channel_filter = st.selectbox(
            "Canal",
            ["Tous", CHANNEL_IBTIKAR, CHANNEL_GENOCLAB],
            key="inv_channel_filter",
        )
    with col3:
        year_opts = sorted(
            {str(_invoice_year(i)) for i in invoices if _invoice_year(i)},
            reverse=True,
        )
        year_filter = st.selectbox(
            "Année",
            ["Toutes"] + year_opts,
            key="inv_year_filter",
        )
    with col4:
        month_opts = ["Tous"] + [
            f"{m:02d} – {MONTH_NAMES_FR[m]}" for m in range(1, 13)
        ]
        month_filter = st.selectbox(
            "Mois",
            month_opts,
            key="inv_month_filter",
        )
    with col5:
        search_term = st.text_input(
            "🔍 Recherche",
            key="inv_search",
            placeholder="N° facture, client…",
        )

    # ── Apply filters ─────────────────────────────────────────────────────────
    filtered = invoices

    if status_filter == "✅ Réglées":
        filtered = [i for i in filtered if i.get("paid")]
    elif status_filter == "⏳ Non réglées":
        filtered = [i for i in filtered if not i.get("paid")]
    elif status_filter == "🔴 En retard":
        filtered = [i for i in filtered if i.get("overdue")]

    if channel_filter != "Tous":
        filtered = [i for i in filtered if i.get("channel") == channel_filter]

    if year_filter != "Toutes":
        y = int(year_filter)
        filtered = [i for i in filtered if _invoice_year(i) == y]

    if month_filter != "Tous":
        m = int(month_filter[:2])
        filtered = [i for i in filtered if _invoice_month(i) == m]

    if search_term.strip():
        sq = search_term.strip().lower()
        filtered = [
            i for i in filtered
            if sq in i.get("invoice_number", "").lower()
            or sq in i.get("requester_name",  "").lower()
            or sq in i.get("institution",      "").lower()
            or sq in i.get("svc_name",         "").lower()
        ]

    # Sort newest first
    filtered = sorted(
        filtered,
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )

    st.caption(
        f"**{len(filtered)}** facture(s) filtrée(s) sur {len(invoices)} total"
    )

    # ── CSV export ────────────────────────────────────────────────────────────
    if filtered:
        csv_lines = [
            "N° Facture,Canal,Client,Institution,Service,"
            "Total HT,TVA,Total TTC,Statut,Date émission,Date paiement,Réf paiement"
        ]
        for i in filtered:
            csv_lines.append(
                f"{i.get('invoice_number','')},"
                f"{i.get('channel','')},"
                f"\"{i.get('requester_name','')}\"," 
                f"\"{i.get('institution','')}\"," 
                f"\"{i.get('svc_name','')}\"," 
                f"{float(i.get('total_ht',0)):.2f},"
                f"{float(i.get('total_vat',0)):.2f},"
                f"{float(i.get('total_ttc',0)):.2f},"
                f"{'Réglée' if i.get('paid') else 'En attente'},"
                f"{fmt_date(i.get('created_at',''))},"
                f"{fmt_date(i.get('paid_at',''))},"
                f"{i.get('payment_ref','')}"
            )
        st.download_button(
            label               = "📥 Exporter la liste (CSV)",
            data                = "\n".join(csv_lines),
            file_name           = (
                f"factures_plagenor_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            ),
            mime                = "text/csv",
            key                 = "export_inv_list_csv",
            use_container_width = False,
        )

    st.divider()

    # ── Paginated list ────────────────────────────────────────────────────────
    if not filtered:
        render_empty_state(
            "🔍", "Aucun résultat",
            "Aucune facture ne correspond aux filtres sélectionnés.",
        )
        return

    page_items, current_page, total_pages = paginate(
        filtered, "inv_list_page", per_page=15
    )

    for inv in page_items:
        _render_invoice_card(inv)

        # Detail expander
        with st.expander(
            f"🔍 Détails — {inv.get('invoice_number', inv['id'][:8])}"
        ):
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.markdown(
                    f"**ID facture:** `{inv['id']}`  \n"
                    f"**ID demande:** `{inv.get('request_id','–')[:8]}`  \n"
                    f"**Créée par:** `{resolve_username(inv.get('created_by',''))}`  \n"
                    f"**Hash court:** `{inv.get('hash_short','–')}`  \n"
                    f"**Intégrité:** "
                    f"{'🔒 OK' if inv.get('integrity_ok') else '⚠️ COMPROMIS'}"
                )
            with col_d2:
                # Line items
                st.markdown("**Lignes de facturation:**")
                for item in inv.get("line_items", []):
                    st.markdown(
                        f"- {item.get('label','–')} × {item.get('quantity',1)} "
                        f"— {fmt_currency(float(item.get('subtotal',0)))}"
                    )
                if inv.get("payment_note"):
                    st.markdown(f"**Note paiement:** _{inv.get('payment_note')}_")

            # PDF download
            pdf_path = inv.get("pdf_path")
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as pf:
                    ext  = os.path.splitext(pdf_path)[-1]
                    mime = "application/pdf" if ext == ".pdf" else (
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"
                    )
                    st.download_button(
                        label     = f"📥 Télécharger la facture ({ext[1:].upper()})",
                        data      = pf.read(),
                        file_name = os.path.basename(pdf_path),
                        mime      = mime,
                        key       = f"dl_inv_{inv['id']}",
                    )
            else:
                if st.button(
                    "🔄 Régénérer le PDF",
                    key = f"regen_pdf_{inv['id']}",
                ):
                    try:
                        new_path = regenerate_invoice_pdf(
                            inv["id"], actor=actor
                        )
                        if new_path:
                            _action_ok(f"PDF régénéré: {new_path}")
                        else:
                            st.warning("⚠️ LibreOffice indisponible — fichier .docx généré.")
                        st.cache_data.clear()
                        st.rerun()
                    except PlagenorError as e:
                        _action_err(e)

    render_pagination_controls("inv_list_page", current_page, total_pages)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Payment Recording
# ══════════════════════════════════════════════════════════════════════════════

def _tab_payment(actor: dict) -> None:
    st.markdown("## 💳 Enregistrement des paiements")

    raw_invoices = _load_invoices()
    unpaid       = [
        _enrich_invoice(i)
        for i in raw_invoices
        if not i.get("paid")
    ]

    if not unpaid:
        render_empty_state(
            "💳", "Aucune facture impayée",
            "Toutes les factures émises sont déjà réglées. 🎉",
        )
        return

    # ── Overdue alert ─────────────────────────────────────────────────────────
    overdue_list = [i for i in unpaid if i.get("overdue")]
    if overdue_list:
        st.error(
            f"⚠️ **{len(overdue_list)} facture(s) en retard** "
            f"(> 30 jours sans paiement). "
            f"Total en souffrance: "
            f"**{fmt_currency(sum(float(i.get('total_ttc',0)) for i in overdue_list))}**"
        )

    # ── Unpaid list with quick KPIs ───────────────────────────────────────────
    st.markdown("### 📋 Factures en attente de règlement")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "⏳ Factures impayées",
        len(unpaid),
    )
    col2.metric(
        "💵 Montant total dû",
        f"{sum(float(i.get('total_ttc',0)) for i in unpaid):,.0f} DZD",
    )
    col3.metric(
        "🔴 En retard",
        len(overdue_list),
        delta = (
            f"{sum(float(i.get('total_ttc',0)) for i in overdue_list):,.0f} DZD"
            if overdue_list else None
        ),
        delta_color = "inverse",
    )
    st.divider()

    # ── Invoice selector ──────────────────────────────────────────────────────
    inv_opts: dict = {}
    for inv in sorted(
        unpaid,
        key     = lambda i: i.get("overdue", False),
        reverse = True,
    ):
        overdue_tag = " 🔴 EN RETARD" if inv.get("overdue") else ""
        label = (
            f"{inv.get('invoice_number', inv['id'][:8])}"
            f"{overdue_tag} — "
            f"{inv.get('requester_name','–')} — "
            f"{fmt_currency(float(inv.get('total_ttc',0)))} TTC"
        )
        inv_opts[label] = inv

    selected_label = st.selectbox(
        "Sélectionner la facture à régler",
        list(inv_opts.keys()),
        key="pay_inv_sel",
    )
    selected_inv = inv_opts[selected_label]

    # Preview card
    _render_invoice_card(selected_inv)
    st.divider()

    # ── Payment form ──────────────────────────────────────────────────────────
    st.markdown("### 💳 Saisir le règlement")
    with st.form("record_payment_form"):
        col1, col2 = st.columns(2)
        with col1:
            paid_date = st.date_input(
                "Date de paiement *",
                value = date.today(),
                key   = "pay_date",
            )
        with col2:
            payment_ref = st.text_input(
                "Référence du virement / chèque *",
                key         = "pay_ref",
                placeholder = "Ex: VIR-2026-00123 ou CHQ-456",
            )
        payment_note = st.text_area(
            "Note de paiement (optionnel)",
            key         = "pay_note",
            height      = 70,
            placeholder = "Ex: Virement reçu le … — Banque BNA",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(
                f"**Montant à encaisser:**  \n"
                f"### {fmt_currency(float(selected_inv.get('total_ttc',0)))}"
            )
        with col_b:
            st.markdown(
                f"**Client:** {selected_inv.get('requester_name','–')}  \n"
                f"**Facture:** {selected_inv.get('invoice_number','–')}"
            )

        submitted = st.form_submit_button(
            "✅ Enregistrer le paiement",
            use_container_width = True,
            type                = "primary",
        )

        if submitted:
            if not payment_ref.strip():
                st.warning("⚠️ La référence de paiement est obligatoire.")
            else:
                try:
                    record_payment(
                        invoice_id  = selected_inv["id"],
                        paid_date   = str(paid_date),
                        payment_ref = payment_ref.strip(),
                        actor       = actor,
                        notes       = payment_note.strip(),
                    )
                    _action_ok(
                        f"Paiement enregistré pour la facture "
                        f"**{selected_inv.get('invoice_number','–')}** — "
                        f"{fmt_currency(float(selected_inv.get('total_ttc',0)))} TTC."
                    )
                    st.cache_data.clear()
                    st.rerun()
                except PlagenorError as e:
                    _action_err(e)

    # ── Recent payments ───────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📅 Paiements récents (30 derniers jours)")
    all_invs   = _load_invoices()
    recent_paid = []
    for inv in all_invs:
        if not inv.get("paid"):
            continue
        paid_at = inv.get("paid_at", "")
        if not paid_at:
            continue
        try:
            days = (datetime.utcnow() -
                    datetime.fromisoformat(
                        paid_at.replace("Z", "+00:00")
                    ).replace(tzinfo=None)).days
            if days <= 30:
                recent_paid.append(_enrich_invoice(inv))
        except Exception:
            pass

    recent_paid = sorted(
        recent_paid,
        key     = lambda i: i.get("paid_at", ""),
        reverse = True,
    )

    if not recent_paid:
        st.info("ℹ️ Aucun paiement enregistré ces 30 derniers jours.")
    else:
        for inv in recent_paid[:10]:
            col1, col2, col3 = st.columns([4, 2, 2])
            with col1:
                st.markdown(
                    f"✅ **{inv.get('invoice_number','–')}** — "
                    f"{inv.get('requester_name','–')}"
                )
            with col2:
                st.markdown(
                    f"**{fmt_currency(float(inv.get('total_ttc',0)))}**"
                )
            with col3:
                st.markdown(
                    f"💳 {fmt_date(inv.get('paid_at',''))}  \n"
                    f"_{inv.get('payment_ref','–')}_"
                )
            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Revenue Analytics
# ══════════════════════════════════════════════════════════════════════════════

def _tab_analytics(actor: dict) -> None:
    st.markdown("## 📊 Analyse des revenus")

    current_year = datetime.utcnow().year

    col_y1, col_y2 = st.columns([2, 5])
    with col_y1:
        year_sel = st.selectbox(
            "Année",
            list(range(current_year, current_year - 5, -1)),
            key = "analytics_year",
        )

    try:
        summary = get_revenue_summary(year=year_sel)
    except Exception as e:
        st.error(f"❌ Erreur de calcul: {e}")
        return

    # ── Global KPIs ───────────────────────────────────────────────────────────
    st.markdown(f"### 💰 Récapitulatif {year_sel}")
    render_kpi_row([
        {"label": "🧾 Factures émises",   "value": summary["total_invoices"]},
        {"label": "✅ Réglées",           "value": summary["paid_invoices"]},
        {"label": "⏳ En attente",        "value": summary["unpaid_invoices"]},
        {"label": "💵 CA HT",
         "value": f"{summary['total_ht']:,.0f} DZD"},
        {"label": "💰 Encaissé TTC",
         "value": f"{summary['encaisse_ttc']:,.0f} DZD"},
        {"label": "📈 Taux recouvrement",
         "value": f"{summary['collection_rate_pct']:.1f}%"},
    ])
    st.divider()

    # ── Budget bar ────────────────────────────────────────────────────────────
    if summary["total_ttc"] > 0:
        render_budget_progress(
            label    = "💳 Taux d'encaissement TTC",
            spent    = summary["encaisse_ttc"],
            total    = summary["total_ttc"],
            currency = True,
        )
        st.divider()

    # ── À encaisser ───────────────────────────────────────────────────────────
    a_enc = summary.get("a_encaisser_ttc", 0)
    if a_enc > 0:
        st.warning(
            f"💵 **Montant restant à encaisser:** "
            f"{fmt_currency(a_enc)} TTC"
        )
        st.divider()

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    st.markdown("### 📅 Évolution mensuelle")
    by_month = summary.get("by_month", {})

    month_data = []
    for m in range(1, 13):
        data = by_month.get(m, {"ttc": 0, "paid_ttc": 0, "count": 0})
        month_data.append({
            "Mois":              f"{MONTH_NAMES_FR[m][:3]}.",
            "Facturé TTC":       float(data.get("ttc",      0)),
            "Encaissé TTC":      float(data.get("paid_ttc", 0)),
            "Nombre factures":   int(data.get("count",      0)),
        })

    # Display as table
    col_headers = ["Mois", "Facturé TTC", "Encaissé TTC", "Nbre"]
    header_cols = st.columns([2, 3, 3, 1])
    for col, h in zip(header_cols, col_headers):
        col.markdown(f"**{h}**")

    for row in month_data:
        if row["Nombre factures"] == 0:
            continue
        c1, c2, c3, c4 = st.columns([2, 3, 3, 1])
        c1.markdown(f"**{row['Mois']}**")
        c2.markdown(f"{row['Facturé TTC']:,.0f} DZD")
        c3.markdown(
            f"{'✅' if row['Encaissé TTC'] >= row['Facturé TTC'] else '⏳'} "
            f"{row['Encaissé TTC']:,.0f} DZD"
        )
        c4.markdown(str(row["Nombre factures"]))
    st.divider()

    # ── Channel breakdown ─────────────────────────────────────────────────────
    st.markdown("### 🔀 Par canal")
    by_channel = summary.get("by_channel", {})

    col_ib, col_gc = st.columns(2)
    for col, ch, icon in [
        (col_ib, CHANNEL_IBTIKAR,  "🌱"),
        (col_gc, CHANNEL_GENOCLAB, "🧬"),
    ]:
        ch_data = by_channel.get(ch, {})
        with col:
            st.markdown(
                f"**{icon} {ch}**  \n"
                f"Factures: `{ch_data.get('count', 0)}`  \n"
                f"Total TTC: **{fmt_currency(float(ch_data.get('total_ttc',0)))}**  \n"
                f"Encaissé: {fmt_currency(float(ch_data.get('paid_ttc',0)))}"
            )
            if float(ch_data.get("total_ttc", 0)) > 0:
                pct = (
                    float(ch_data.get("paid_ttc", 0)) /
                    float(ch_data.get("total_ttc", 1)) * 100
                )
                st.progress(min(pct / 100, 1.0))
                st.caption(f"Taux: {pct:.1f}%")

    st.divider()

    # ── Export revenue summary ────────────────────────────────────────────────
    st.markdown("### 📥 Export")
    csv_lines = [
        f"# Rapport financier PLAGENOR {year_sel}",
        f"# Généré le: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}",
        "#",
        "Période,Facturé HT,TVA,Facturé TTC,Encaissé TTC,À encaisser,Taux",
        f"Annuel {year_sel},"
        f"{summary['total_ht']:.2f},"
        f"{summary['total_vat']:.2f},"
        f"{summary['total_ttc']:.2f},"
        f"{summary['encaisse_ttc']:.2f},"
        f"{summary['a_encaisser_ttc']:.2f},"
        f"{summary['collection_rate_pct']:.1f}%",
        "#",
        "Mois,Facturé HT,Facturé TTC,Encaissé TTC,Nombre factures",
    ]
    for m in range(1, 13):
        d = by_month.get(m, {"ht": 0, "ttc": 0, "paid_ttc": 0, "count": 0})
        csv_lines.append(
            f"{MONTH_NAMES_FR[m]} {year_sel},"
            f"{float(d.get('ht',0)):.2f},"
            f"{float(d.get('ttc',0)):.2f},"
            f"{float(d.get('paid_ttc',0)):.2f},"
            f"{int(d.get('count',0))}"
        )

    st.download_button(
        label               = f"📥 Exporter rapport {year_sel} (CSV)",
        data                = "\n".join(csv_lines),
        file_name           = f"rapport_financier_{year_sel}.csv",
        mime                = "text/csv",
        key                 = "export_revenue_csv",
        use_container_width = False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — VAT Summary
# ══════════════════════════════════════════════════════════════════════════════

def _tab_vat(actor: dict) -> None:
    st.markdown("## 🧮 Récapitulatif TVA")
    st.caption(
        f"Taux TVA appliqué: **{VAT_RATE*100:.0f}%**  \n"
        "Les demandes IBTIKAR (financement institutionnel) sont exonérées de TVA."
    )

    current_year = datetime.utcnow().year
    col_y, _ = st.columns([2, 5])
    with col_y:
        year_sel = st.selectbox(
            "Année fiscale",
            list(range(current_year, current_year - 5, -1)),
            key = "vat_year",
        )

    try:
        vat_data = get_vat_summary(year=year_sel)
    except Exception as e:
        st.error(f"❌ Erreur: {e}")
        return

    annual = vat_data.get("annual", {})

    # ── Annual total ──────────────────────────────────────────────────────────
    st.markdown(f"### 📊 Totaux annuels {year_sel}")
    render_kpi_row([
        {"label": "🧾 Factures GENOCLAB",
         "value": annual.get("count", 0)},
        {"label": "💵 Base HT totale",
         "value": f"{annual.get('ht',0):,.0f} DZD"},
        {"label": f"🧮 TVA collectée ({VAT_RATE*100:.0f}%)",
         "value": f"{annual.get('vat',0):,.0f} DZD"},
        {"label": "💰 Total TTC",
         "value": f"{annual.get('ttc',0):,.0f} DZD"},
    ])
    st.divider()

    # ── Quarterly breakdown ───────────────────────────────────────────────────
    st.markdown("### 📅 Ventilation trimestrielle")
    quarters = vat_data.get("quarters", {})

    q_cols = st.columns(4)
    for i, (q_label, q_data) in enumerate(quarters.items()):
        with q_cols[i]:
            ttc = float(q_data.get("ttc", 0))
            vat = float(q_data.get("vat", 0))
            ht  = float(q_data.get("ht",  0))
            cnt = int(q_data.get("count", 0))

            st.markdown(
                f"""
                <div style="
                    background:#f8fafc;
                    border:1px solid #d5e8f3;
                    border-radius:10px;
                    padding:14px;
                    text-align:center;
                ">
                    <div style="font-size:1.1rem; font-weight:700;
                                color:#1B4F72;">{q_label}</div>
                    <div style="font-size:0.8rem; color:#7f8c8d;
                                margin:4px 0;">
                        {cnt} facture(s)
                    </div>
                    <div style="font-size:0.85rem; margin-top:8px;">
                        HT: <b>{ht:,.0f} DZD</b>
                    </div>
                    <div style="font-size:0.85rem; color:#E74C3C;">
                        TVA: <b>{vat:,.0f} DZD</b>
                    </div>
                    <div style="font-size:0.9rem; font-weight:700;
                                color:#1B4F72; margin-top:4px;">
                        TTC: {ttc:,.0f} DZD
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # ── VAT declaration export ────────────────────────────────────────────────
    st.markdown("### 📥 Export déclaration TVA")
    st.caption(
        "Ce fichier CSV est destiné à faciliter la déclaration fiscale "
        "auprès des services des impôts."
    )

    dec_lines = [
        f"# DÉCLARATION TVA — PLAGENOR 4.0",
        f"# Exercice fiscal: {year_sel}",
        f"# Taux TVA: {VAT_RATE*100:.0f}%",
        f"# Généré le: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}",
        "#",
        "Trimestre,Mois inclus,Nbre factures,Base HT (DZD),TVA collectée (DZD),Total TTC (DZD)",
    ]
    q_months = {
        "T1": "Jan–Fév–Mar",
        "T2": "Avr–Mai–Jun",
        "T3": "Jul–Aoû–Sep",
        "T4": "Oct–Nov–Déc",
    }
    for q_label, q_data in quarters.items():
        dec_lines.append(
            f"{q_label},"
            f"{q_months.get(q_label,'')},"
            f"{q_data.get('count',0)},"
            f"{float(q_data.get('ht',0)):.2f},"
            f"{float(q_data.get('vat',0)):.2f},"
            f"{float(q_data.get('ttc',0)):.2f}"
        )
    dec_lines.append(
        f"TOTAL ANNUEL,Jan–Déc,"
        f"{annual.get('count',0)},"
        f"{annual.get('ht',0):.2f},"
        f"{annual.get('vat',0):.2f},"
        f"{annual.get('ttc',0):.2f}"
    )

    # Append invoice-level detail
    dec_lines += [
        "#",
        "# DÉTAIL FACTURES GENOCLAB",
        "N° Facture,Date,Client,Institution,HT,TVA,TTC,Statut",
    ]
    all_invs = _load_invoices()
    for inv in sorted(
        all_invs,
        key     = lambda i: i.get("created_at",""),
        reverse = False,
    ):
        if inv.get("channel") != CHANNEL_GENOCLAB:
            continue
        if _invoice_year(inv) != year_sel:
            continue
        dec_lines.append(
            f"{inv.get('invoice_number','')},"
            f"{fmt_date(inv.get('created_at',''))},"
            f"\"{inv.get('client_name','')}\"," 
            f"\"{inv.get('institution','')}\"," 
            f"{float(inv.get('total_ht',0)):.2f},"
            f"{float(inv.get('total_vat',0)):.2f},"
            f"{float(inv.get('total_ttc',0)):.2f},"
            f"{'Réglée' if inv.get('paid') else 'Non réglée'}"
        )

    st.download_button(
        label               = f"📥 Télécharger déclaration TVA {year_sel} (CSV)",
        data                = "\n".join(dec_lines),
        file_name           = f"declaration_tva_{year_sel}.csv",
        mime                = "text/csv",
        key                 = "export_vat_csv",
        use_container_width = False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Overdue Tracking
# ══════════════════════════════════════════════════════════════════════════════

def _tab_overdue(actor: dict) -> None:
    st.markdown("## 🔴 Suivi des impayés")

    col_t1, col_t2 = st.columns([2, 5])
    with col_t1:
        threshold = st.number_input(
            "Seuil (jours)",
            min_value = 7,
            max_value = 180,
            value     = 30,
            step      = 7,
            key       = "overdue_threshold",
        )

    try:
        overdue_list = get_overdue_invoices(overdue_days=int(threshold))
    except Exception as e:
        st.error(f"❌ {e}")
        return

    if not overdue_list:
        render_empty_state(
            "✅", "Aucun impayé",
            f"Aucune facture non réglée depuis plus de {threshold} jours.",
        )
        return

    total_overdue = sum(float(i.get("total_ttc", 0)) for i in overdue_list)

    st.error(
        f"🔴 **{len(overdue_list)} facture(s) en souffrance** "
        f"depuis plus de {threshold} jours.  \n"
        f"Montant total: **{fmt_currency(total_overdue)}**"
    )

    render_kpi_row([
        {"label": "🔴 Factures en retard",   "value": len(overdue_list)},
        {"label": "💸 Total en souffrance",  "value": f"{total_overdue:,.0f} DZD"},
        {"label": "⏱️ Retard max (jours)",
         "value": max(i.get("days_overdue", 0) for i in overdue_list)},
        {"label": "📅 Retard moy. (jours)",
         "value": round(
             sum(i.get("days_overdue", 0) for i in overdue_list) /
             len(overdue_list), 1
         )},
    ])
    st.divider()

    # ── Overdue table ─────────────────────────────────────────────────────────
    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([2, 3, 2, 2, 1])
    for col, label in zip(
        [col_h1, col_h2, col_h3, col_h4, col_h5],
        ["N° Facture", "Client", "TTC", "Jours retard", "Canal"],
    ):
        col.markdown(f"**{label}**")
    st.divider()

    for inv in overdue_list:
        enriched = _enrich_invoice(inv)
        c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 2, 1])
        days = inv.get("days_overdue", 0)
        severity = "🔴" if days > 60 else "🟡"

        c1.markdown(f"`{inv.get('invoice_number','–')}`")
        c2.markdown(
            f"**{enriched.get('requester_name','–')}**  \n"
            f"_{enriched.get('institution','–')}_"
        )
        c3.markdown(
            f"**{fmt_currency(float(inv.get('total_ttc',0)))}**"
        )
        c4.markdown(
            f"{severity} **{days} jours**  \n"
            f"_{fmt_date(inv.get('created_at',''))}_"
        )
        c5.markdown(inv.get("channel", "–"))
        st.divider()

    # ── Export overdue list ───────────────────────────────────────────────────
    csv_lines = [
        "N° Facture,Canal,Client,Institution,TTC (DZD),"
        "Date émission,Jours retard,Email client"
    ]
    for inv in overdue_list:
        enriched = _enrich_invoice(inv)
        csv_lines.append(
            f"{inv.get('invoice_number','')},"
            f"{enriched.get('channel','')},"
            f"\"{enriched.get('requester_name','')}\"," 
            f"\"{enriched.get('institution','')}\"," 
            f"{float(inv.get('total_ttc',0)):.2f},"
            f"{fmt_date(inv.get('created_at',''))},"
            f"{inv.get('days_overdue',0)},"
            f"{enriched.get('requester_email','')}"
        )

    st.download_button(
        label               = "📥 Exporter liste impayés (CSV)",
        data                = "\n".join(csv_lines),
        file_name           = (
            f"impayes_plagenor_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        ),
        mime                = "text/csv",
        key                 = "export_overdue_csv",
        use_container_width = False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — Finance Audit Log
# ══════════════════════════════════════════════════════════════════════════════

def _tab_audit(actor: dict) -> None:
    st.markdown("## 🔍 Journal financier")

    logs = _load_audit_logs()

    # Filter to financial-relevant actions only
    fin_keywords = {
        "INVOICE", "PAYMENT", "QUOTE", "BUDGET",
        "FINANCIAL", "TRANSITION", "ASSIGN",
    }
    fin_logs = [
        l for l in logs
        if any(kw in l.get("action", "").upper() for kw in fin_keywords)
    ]
    fin_logs = sorted(
        fin_logs,
        key     = lambda x: x.get("timestamp", ""),
        reverse = True,
    )

    col1, col2 = st.columns(2)
    with col1:
        action_filter = st.text_input(
            "🔍 Filtrer par action",
            key         = "fin_audit_action",
            placeholder = "Ex: INVOICE, PAYMENT, QUOTE…",
        )
    with col2:
        max_entries = st.slider(
            "Max entrées",
            min_value = 20,
            max_value = 200,
            value     = 50,
            step      = 10,
            key       = "fin_audit_max",
        )

    if action_filter:
        sq       = action_filter.upper()
        fin_logs = [l for l in fin_logs if sq in l.get("action","").upper()]

    st.caption(
        f"**{min(len(fin_logs), max_entries)}** / {len(fin_logs)} "
        "entrée(s) affichée(s)"
    )

    if fin_logs:
        csv_lines = [
            "timestamp,action,entity_type,entity_id,username,details"
        ]
        for l in fin_logs[:max_entries]:
            csv_lines.append(
                f"{l.get('timestamp','')[:16]},"
                f"{l.get('action','')},"
                f"{l.get('entity_type','')},"
                f"{str(l.get('entity_id',''))[:8]},"
                f"{l.get('username','')},"
                f"\"{l.get('details','')}\""
            )
        st.download_button(
            label               = "📥 Exporter journal financier (CSV)",
            data                = "\n".join(csv_lines),
            file_name           = (
                f"journal_financier_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            ),
            mime                = "text/csv",
            key                 = "export_fin_audit_csv",
            use_container_width = False,
        )

    st.divider()

    for log in fin_logs[:max_entries]:
        ts      = log.get("timestamp", "")[:16]
        action  = log.get("action",      "–")
        eid     = str(log.get("entity_id", ""))[:8]
        uname   = log.get("username",    "–")
        details = log.get("details",     "")

        if "PAID" in action or "PAYMENT" in action:
            icon = "💳"
        elif "INVOICE" in action:
            icon = "🧾"
        elif "QUOTE" in action:
            icon = "💵"
        elif "BUDGET" in action:
            icon = "💰"
        elif "TRANSITION" in action:
            icon = "🔀"
        else:
            icon = "📋"

        st.markdown(
            f"{icon} `{ts}` | **{action}** "
            f"| `{eid}` | 👤 `{uname}`"
            + (f"  \n_{details}_" if details else "")
        )
        st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def render() -> None:
    user = require_roles(config.ROLE_FINANCE)
    render_sidebar_user(user)

    st.title("💰 PLAGENOR 4.0 — Gestion Financière")
    st.caption(
        f"Connecté en tant que: **{user.get('username')}** "
        f"| Rôle: `{user.get('role')}`"
    )

    # ── Global header KPIs ────────────────────────────────────────────────────
    try:
        current_year = datetime.utcnow().year
        header_summary = get_revenue_summary(year=current_year)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric(
            "🧾 Factures émises",
            header_summary["total_invoices"],
        )
        c2.metric(
            "✅ Réglées",
            header_summary["paid_invoices"],
        )
        c3.metric(
            "⏳ En attente",
            header_summary["unpaid_invoices"],
        )
        c4.metric(
            f"💰 CA {current_year} TTC",
            f"{header_summary['total_ttc']:,.0f} DZD",
        )
        c5.metric(
            "📈 Recouvrement",
            f"{header_summary['collection_rate_pct']:.0f}%",
        )
        st.divider()
    except Exception:
        pass

    tabs = st.tabs([
        "🧾 Factures",
        "💳 Paiements",
        "📊 Analytique",
        "🧮 TVA",
        "🔴 Impayés",
        "🔍 Journal",
    ])

    with tabs[0]: _tab_invoices(user)
    with tabs[1]: _tab_payment(user)
    with tabs[2]: _tab_analytics(user)
    with tabs[3]: _tab_vat(user)
    with tabs[4]: _tab_overdue(user)
    with tabs[5]: _tab_audit(user)