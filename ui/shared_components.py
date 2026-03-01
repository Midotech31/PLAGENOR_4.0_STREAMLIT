# ui/shared_components.py
# ── PLAGENOR 4.0 — Shared UI Components ──────────────────────────────────────
# Reusable widgets, helpers, and resolvers used across ALL dashboards.
# No business logic here — pure UI + lightweight data resolution only.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime
from typing import Optional, Callable

import config


# ── Constants ─────────────────────────────────────────────────────────────────
CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB

# ── Workflow step definitions ─────────────────────────────────────────────────
# Used by render_workflow_progress() to show visual pipeline bar.
IBTIKAR_PIPELINE: list[tuple[str, str]] = [
    ("SUBMITTED",           "📥 Soumise"),
    ("VALIDATION",          "🔍 Validation"),
    ("APPROVED",            "✅ Approuvée"),
    ("ASSIGNED",            "🧬 Assignée"),
    ("ANALYSIS_IN_PROGRESS","🔬 Analyse"),
    ("ANALYSIS_FINISHED",   "✅ Terminée"),
    ("REPORT_UPLOADED",     "📄 Rapport"),
    ("COMPLETED",           "🏁 Clôturée"),
]

GENOCLAB_PIPELINE: list[tuple[str, str]] = [
    ("SUBMITTED",                 "📥 Soumise"),
    ("VALIDATION",                "🔍 Validation"),
    ("APPROVED",                  "✅ Approuvée"),
    ("QUOTE_SENT",                "💵 Devis envoyé"),
    ("QUOTE_VALIDATED_BY_CLIENT", "🤝 Devis accepté"),
    ("INVOICE_GENERATED",         "🧾 Facture"),
    ("ASSIGNED",                  "🧬 Assignée"),
    ("ANALYSIS_IN_PROGRESS",      "🔬 Analyse"),
    ("ANALYSIS_FINISHED",         "✅ Terminée"),
    ("REPORT_UPLOADED",           "📄 Rapport"),
    ("COMPLETED",                 "🏁 Clôturée"),
]

# Terminal / non-progressing states
TERMINAL_STATES = {
    "REJECTED",
    "QUOTE_REJECTED_BY_CLIENT",
    "ARCHIVED",
}

# Status → (icon, label_fr, level)
STATUS_DISPLAY: dict[str, tuple[str, str, str]] = {
    "SUBMITTED":                  ("📥", "Soumise",                       "info"),
    "VALIDATION":                 ("🔍", "En cours de validation",         "info"),
    "APPROVED":                   ("✅", "Approuvée",                      "success"),
    "REJECTED":                   ("🚫", "Rejetée",                        "error"),
    "QUOTE_DRAFT":                ("📝", "Devis en préparation",           "info"),
    "QUOTE_SENT":                 ("📧", "Devis envoyé",                   "warning"),
    "QUOTE_VALIDATED_BY_CLIENT":  ("🤝", "Devis accepté",                  "success"),
    "QUOTE_REJECTED_BY_CLIENT":   ("🚫", "Devis refusé par le client",     "error"),
    "INVOICE_GENERATED":          ("🧾", "Facture générée",                "success"),
    "ASSIGNED":                   ("🧬", "Analyste assigné",               "info"),
    "ANALYSIS_IN_PROGRESS":       ("🔬", "Analyse en cours",               "info"),
    "ANALYSIS_FINISHED":          ("✅", "Analyse terminée",               "success"),
    "REPORT_UPLOADED":            ("📄", "Rapport disponible",             "success"),
    "COMPLETED":                  ("🏁", "Clôturée",                       "success"),
    "ARCHIVED":                   ("📦", "Archivée",                       "info"),
}

# Channel → badge HTML
CHANNEL_BADGE_HTML: dict[str, str] = {
    CHANNEL_IBTIKAR:  '<span class="channel-ibtikar">IBTIKAR</span>',
    CHANNEL_GENOCLAB: '<span class="channel-genoclab">GENOCLAB</span>',
}


# ── Date / currency formatters ─────────────────────────────────────────────────
def fmt_date(iso: str) -> str:
    if not iso:
        return "–"
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%d/%m/%Y")
    except Exception:
        return iso[:10]


def fmt_datetime(iso: str) -> str:
    if not iso:
        return "–"
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso[:16]


def fmt_currency(amount: float) -> str:
    return f"{amount:,.0f} DZD"


def days_since(iso_date: str) -> int:
    if not iso_date:
        return 0
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return max((datetime.utcnow() - dt.replace(tzinfo=None)).days, 0)
    except Exception:
        return 0


# ── Resolvers (cache-aware, no circular imports) ───────────────────────────────
@st.cache_data(ttl=60)
def resolve_service_name(service_id: str) -> str:
    """Resolves a service_id to its human-readable name."""
    if not service_id:
        return "–"
    try:
        from core.repository import get_all_services
        services = get_all_services()
        for svc in services:
            if svc.get("id") == service_id:
                return svc.get("name", service_id)
        return service_id[:8]
    except Exception:
        return service_id[:8]


@st.cache_data(ttl=60)
def resolve_username(user_id: str) -> str:
    """Resolves a user_id to its username."""
    if not user_id:
        return "–"
    try:
        from core.repository import get_all_users
        users = get_all_users()
        for u in users:
            if u.get("id") == user_id:
                return u.get("username", user_id[:8])
        return user_id[:8]
    except Exception:
        return user_id[:8]


@st.cache_data(ttl=60)
def resolve_member_name(member_id: str) -> str:
    """Resolves a member_id to its display name."""
    if not member_id:
        return "–"
    try:
        from core.repository import get_all_members
        members = get_all_members()
        for m in members:
            if m.get("id") == member_id:
                return m.get("name", member_id[:8])
        return member_id[:8]
    except Exception:
        return member_id[:8]


# ── Sidebar user block ────────────────────────────────────────────────────────
def render_sidebar_user(user: dict) -> None:
    """
    Renders the user identity + logout button in the sidebar.
    Must be called once per page render, near the top of render().
    """
    with st.sidebar:
        # Platform logo / header
        st.markdown(
            """
            <div style="text-align:center; padding: 10px 0 20px 0;">
                <div style="font-size: 2.2rem;">🔬</div>
                <div style="font-size: 1.1rem; font-weight:700;
                            color:#ffffff; letter-spacing:1px;">
                    PLAGENOR 4.0
                </div>
                <div style="font-size: 0.72rem; color:#1ABC9C;
                            font-weight:600; letter-spacing:2px;">
                    ESSBO · ORAN
                </div>
            </div>
            """,
            unsafe_allow_html = True,
        )
        st.divider()

        # User info
        role_label = (
            user.get("role", "–")
            .replace("ROLE_", "")
            .replace("_", " ")
            .title()
        )
        st.markdown(
            f"👤 **{user.get('username','–')}**  \n"
            f"🎭 `{role_label}`"
        )
        if user.get("organization_id"):
            st.caption(f"🏛️ Org: `{user.get('organization_id')}`")
        if user.get("email"):
            st.caption(f"📧 {user.get('email')}")

        st.divider()

        # Logout
        if st.button(
            "🚪 Déconnexion",
            key                 = "sidebar_logout_btn",
            use_container_width = True,
        ):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        st.divider()
        st.caption("© 2026 Prof. Mohamed Merzoug  \nESSBO · IBTIKAR-DGRSDT")


# ── Status badge ──────────────────────────────────────────────────────────────
def render_status_badge(status: str) -> None:
    """
    Renders a coloured inline HTML badge for a request status.
    Uses the .status-* CSS classes defined in app.py global CSS.
    """
    icon, label, _ = STATUS_DISPLAY.get(status, ("📋", status, "info"))
    css_class       = f"status-{status.lower().replace('_', '-')}"
    st.markdown(
        f'<span class="status-badge {css_class}">{icon} {label}</span>',
        unsafe_allow_html = True,
    )


# ── Channel badge ─────────────────────────────────────────────────────────────
def render_channel_badge(channel: str) -> None:
    """Renders an inline channel badge (IBTIKAR or GENOCLAB)."""
    html = CHANNEL_BADGE_HTML.get(
        channel,
        f'<span class="status-badge">{channel}</span>',
    )
    st.markdown(html, unsafe_allow_html=True)


# ── Workflow progress bar ─────────────────────────────────────────────────────
def render_workflow_progress(channel: str, current_status: str) -> None:
    """
    Renders a horizontal step-by-step workflow progress indicator.
    Completed steps = green, current = blue, future = grey.
    Terminal states (REJECTED etc.) show a red banner instead.
    """
    if current_status in TERMINAL_STATES:
        icon, label, _ = STATUS_DISPLAY.get(
            current_status, ("🚫", current_status, "error")
        )
        st.error(f"{icon} **Demande terminée — {label}**")
        return

    pipeline = (
        GENOCLAB_PIPELINE
        if channel == CHANNEL_GENOCLAB
        else IBTIKAR_PIPELINE
    )

    steps       = [p[0] for p in pipeline]
    labels      = [p[1] for p in pipeline]
    current_idx = steps.index(current_status) if current_status in steps else -1
    n           = len(steps)

    # Build HTML progress bar
    parts = []
    for i, (state, label) in enumerate(zip(steps, labels)):
        if i < current_idx:
            # Completed
            style = (
                "background:#1ABC9C; color:white; "
                "padding:4px 10px; border-radius:14px; "
                "font-size:0.72rem; font-weight:700; "
                "white-space:nowrap;"
            )
            parts.append(f'<span style="{style}">✅ {label}</span>')
        elif i == current_idx:
            # Current
            style = (
                "background:#1B4F72; color:white; "
                "padding:4px 12px; border-radius:14px; "
                "font-size:0.75rem; font-weight:700; "
                "box-shadow:0 2px 8px rgba(27,79,114,0.3); "
                "white-space:nowrap;"
            )
            parts.append(f'<span style="{style}">▶ {label}</span>')
        else:
            # Future
            style = (
                "background:#e8edf3; color:#7f8c8d; "
                "padding:4px 10px; border-radius:14px; "
                "font-size:0.72rem; font-weight:500; "
                "white-space:nowrap;"
            )
            parts.append(f'<span style="{style}">{label}</span>')

    arrow = '<span style="color:#1ABC9C; font-weight:700; margin:0 3px;">›</span>'
    html  = (
        '<div style="display:flex; flex-wrap:wrap; gap:4px; '
        'align-items:center; margin:10px 0 16px 0;">'
        + arrow.join(parts)
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)

    # Progress fraction
    if current_idx >= 0:
        pct = (current_idx + 1) / n
        st.progress(pct)
        st.caption(
            f"Étape **{current_idx + 1}** / {n} — "
            f"{int(pct * 100)}% du workflow"
        )


# ── Request card ──────────────────────────────────────────────────────────────
def render_request_card(req: dict, show_workflow: bool = False) -> None:
    """
    Renders a compact summary card for a request.
    Used in dashboards listing / detail views.
    """
    status   = req.get("status", "–")
    channel  = req.get("channel", "–")
    svc_name = resolve_service_name(req.get("service_id", ""))

    icon, status_label, level = STATUS_DISPLAY.get(
        status, ("📋", status, "info")
    )
    channel_html = CHANNEL_BADGE_HTML.get(
        channel,
        f'<span class="status-badge">{channel}</span>',
    )
    status_css   = f"status-{status.lower().replace('_','-')}"

    form_data    = req.get("form_data", {})
    requester    = form_data.get("requester", {})
    req_name     = requester.get("full_name", "–")
    institution  = requester.get("institution", "–")
    quote_amount = float(req.get("quote_amount", 0))
    member_name  = req.get("assigned_member_name", "–") or "–"
    created      = fmt_date(req.get("created_at", ""))
    updated      = fmt_date(req.get("updated_at",  ""))

    st.markdown(
        f"""
        <div style="
            background:#ffffff;
            border:1px solid #e0e8f0;
            border-radius:12px;
            padding:14px 18px;
            margin-bottom:8px;
            box-shadow:0 2px 8px rgba(27,79,114,0.07);
            border-left:5px solid {'#1B4F72' if channel==CHANNEL_IBTIKAR else '#1ABC9C'};
        ">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <span style="font-size:1rem; font-weight:700; color:#1B4F72;">
                        🧬 {svc_name}
                    </span>
                    &nbsp;{channel_html}&nbsp;
                    <span class="status-badge {status_css}">{icon} {status_label}</span>
                </div>
                <div style="font-size:0.75rem; color:#7f8c8d;">
                    Réf: <code>{req['id'][:8]}</code>
                </div>
            </div>
            <div style="margin-top:8px; font-size:0.85rem; color:#2c3e50;">
                👤 <b>{req_name}</b> — {institution}
            </div>
            <div style="margin-top:4px; font-size:0.8rem; color:#7f8c8d;">
                📅 Soumise: {created} &nbsp;|&nbsp;
                🔄 MAJ: {updated} &nbsp;|&nbsp;
                🧬 Assignée: {member_name}
                {"&nbsp;|&nbsp; 💵 Devis: <b>" + fmt_currency(quote_amount) + " HT</b>"
                 if quote_amount > 0 else ""}
            </div>
        </div>
        """,
        unsafe_allow_html = True,
    )

    if show_workflow:
        render_workflow_progress(channel, status)


# ── Empty state ───────────────────────────────────────────────────────────────
def render_empty_state(
    icon:    str,
    title:   str,
    message: str,
    action_label: Optional[str] = None,
    action_key:   Optional[str] = None,
) -> bool:
    """
    Renders a centred empty-state block.
    If action_label is given, shows a button and returns True when clicked.
    """
    st.markdown(
        f"""
        <div style="
            text-align:center;
            padding:40px 20px;
            background:#f8fafc;
            border-radius:16px;
            border:2px dashed #d5e8f3;
            margin:20px 0;
        ">
            <div style="font-size:3rem; margin-bottom:12px;">{icon}</div>
            <div style="font-size:1.1rem; font-weight:700;
                        color:#1B4F72; margin-bottom:8px;">
                {title}
            </div>
            <div style="font-size:0.9rem; color:#7f8c8d; max-width:400px;
                        margin:0 auto;">
                {message}
            </div>
        </div>
        """,
        unsafe_allow_html = True,
    )
    if action_label and action_key:
        col = st.columns([1, 2, 1])[1]
        return col.button(
            action_label,
            key                 = action_key,
            use_container_width = True,
        )
    return False


# ── Confirm action (two-step button) ──────────────────────────────────────────
def confirm_action(
    key:     str,
    label:   str,
    message: str,
    danger:  bool = False,
) -> bool:
    """
    Two-step confirmation widget:
      First click  → shows confirmation prompt.
      Second click → returns True (action confirmed).

    Returns False until confirmed.
    Resets automatically after confirmation or cancellation.

    Usage:
        if confirm_action(key="del_x", label="🗑️ Supprimer", message="Supprimer X ?"):
            do_delete()
    """
    confirm_key = f"_confirm_pending_{key}"

    if not st.session_state.get(confirm_key, False):
        btn_type = "primary" if not danger else "primary"
        if st.button(label, key=key, type=btn_type, use_container_width=True):
            st.session_state[confirm_key] = True
            st.rerun()
        return False
    else:
        # Show confirmation prompt
        if danger:
            st.error(f"⚠️ {message}")
        else:
            st.warning(f"❓ {message}")
        col_yes, col_no = st.columns(2)
        confirmed = False
        with col_yes:
            if st.button(
                "✅ Confirmer",
                key                 = f"{key}_confirm_yes",
                type                = "primary",
                use_container_width = True,
            ):
                st.session_state[confirm_key] = False
                confirmed = True
        with col_no:
            if st.button(
                "❌ Annuler",
                key                 = f"{key}_confirm_no",
                use_container_width = True,
            ):
                st.session_state[confirm_key] = False
                st.rerun()
        return confirmed


# ── Pagination helper ─────────────────────────────────────────────────────────
def paginate(
    items:    list,
    page_key: str,
    per_page: int = 20,
) -> tuple[list, int, int]:
    """
    Paginates a list of items.

    Returns:
        (page_items, current_page, total_pages)

    Usage:
        page_items, page, total = paginate(items, "my_list", per_page=15)
        for item in page_items:
            render_item(item)
        render_pagination_controls(page_key, page, total)
    """
    total      = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    current    = st.session_state.get(page_key, 1)
    current    = max(1, min(current, total_pages))
    start      = (current - 1) * per_page
    end        = start + per_page
    return items[start:end], current, total_pages


def render_pagination_controls(
    page_key:    str,
    current:     int,
    total_pages: int,
) -> None:
    """Renders Previous / Next pagination controls for paginate()."""
    if total_pages <= 1:
        return
    col1, col2, col3 = st.columns([2, 3, 2])
    with col1:
        if current > 1:
            if st.button("← Précédent", key=f"{page_key}_prev"):
                st.session_state[page_key] = current - 1
                st.rerun()
    with col2:
        st.caption(f"Page **{current}** / {total_pages}")
    with col3:
        if current < total_pages:
            if st.button("Suivant →", key=f"{page_key}_next"):
                st.session_state[page_key] = current + 1
                st.rerun()


# ── Section header with channel accent ───────────────────────────────────────
def render_section_header(title: str, channel: Optional[str] = None) -> None:
    """
    Renders an accented section header with optional channel colour strip.
    """
    css_class = ""
    if channel == CHANNEL_IBTIKAR:
        css_class = "ibtikar-section"
    elif channel == CHANNEL_GENOCLAB:
        css_class = "genoclab-section"

    st.markdown(
        f'<div class="{css_class}"><h3 style="margin:0;padding:6px 0;">'
        f'{title}</h3></div>',
        unsafe_allow_html = True,
    )


# ── Metric card with delta trend ──────────────────────────────────────────────
def render_kpi_row(metrics: list[dict]) -> None:
    """
    Renders a row of st.metric() cards from a list of dicts.

    Each dict may contain:
        label, value, delta (optional), delta_color (optional), help (optional)

    Example:
        render_kpi_row([
            {"label": "Total", "value": 42},
            {"label": "Active", "value": 10, "delta": "+2"},
        ])
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        col.metric(
            label       = m.get("label",  "–"),
            value       = m.get("value",   0),
            delta       = m.get("delta"),
            delta_color = m.get("delta_color", "normal"),
            help        = m.get("help"),
        )


# ── Info / warning / error banners ────────────────────────────────────────────
def render_info_banner(
    message: str,
    level:   str = "info",
    icon:    str = "ℹ️",
) -> None:
    """Renders a styled info/warning/error banner with custom icon."""
    if level == "success":
        st.success(f"{icon} {message}")
    elif level == "warning":
        st.warning(f"{icon} {message}")
    elif level == "error":
        st.error(f"{icon} {message}")
    else:
        st.info(f"{icon} {message}")


# ── Document list ─────────────────────────────────────────────────────────────
def render_document_list(
    documents: list,
    allow_download: bool = True,
) -> None:
    """
    Renders a list of document records with optional download buttons.
    Each document dict must have: filename, path, type, created_at.
    """
    if not documents:
        st.caption("📂 Aucun document disponible.")
        return

    for doc in documents:
        filename  = doc.get("filename",   f"document_{doc.get('id','')[:8]}")
        doc_type  = doc.get("type",       "DOCUMENT")
        created   = fmt_date(doc.get("created_at", ""))
        path      = doc.get("path",       "")
        size_kb   = doc.get("size_kb",    "–")

        col1, col2 = st.columns([5, 2])
        with col1:
            st.markdown(
                f"📄 **{filename}**  \n"
                f"Type: `{doc_type}` | Ajouté: {created}"
                + (f" | {size_kb} KB" if size_kb != "–" else "")
            )
        with col2:
            if allow_download and path and os.path.exists(path):
                with open(path, "rb") as f:
                    ext  = os.path.splitext(filename)[-1].lower()
                    mime = {
                        ".pdf":  "application/pdf",
                        ".docx": (
                            "application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document"
                        ),
                        ".xlsx": (
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                        ".csv":  "text/csv",
                    }.get(ext, "application/octet-stream")
                    st.download_button(
                        label               = "📥 Télécharger",
                        data                = f.read(),
                        file_name           = filename,
                        mime                = mime,
                        key                 = f"dl_doc_{doc.get('id',filename)}",
                        use_container_width = True,
                    )
            elif allow_download:
                st.caption("⏳ En cours…")
        st.divider()


# ── Notes / timeline entry renderer ──────────────────────────────────────────
def render_notes_timeline(
    notes:        list,
    max_entries:  int = 20,
    show_author:  bool = True,
) -> None:
    """
    Renders a vertical timeline of notes / analysis entries.

    Each note dict should contain:
        text, timestamp, author_id (optional), author_name (optional)
    """
    if not notes:
        st.caption("📝 Aucune note enregistrée.")
        return

    for note in notes[-max_entries:][::-1]:
        author = (
            note.get("author_name")
            or resolve_username(note.get("author_id", ""))
        )
        ts    = fmt_datetime(note.get("timestamp", ""))
        text  = note.get("text", "–")
        level = note.get("level", "info")
        icon  = {"info": "📝", "success": "✅", "warning": "⚠️", "error": "🚫"}.get(
            level, "📝"
        )

        with st.container():
            meta = f"`{ts}`"
            if show_author and author and author != "–":
                meta += f" — 👤 **{author}**"
            st.markdown(f"{icon} {meta}")
            st.markdown(
                f"> {text}",
            )
            st.divider()


# ── Budget progress bar ───────────────────────────────────────────────────────
def render_budget_progress(
    label:     str,
    spent:     float,
    total:     float,
    currency:  bool = True,
) -> None:
    """
    Renders a labelled progress bar for budget consumption.
    Colour: green < 70%, orange 70-90%, red > 90%.
    """
    pct     = (spent / total) if total > 0 else 0.0
    pct_clamped = min(pct, 1.0)

    val_str = (
        f"{fmt_currency(spent)} / {fmt_currency(total)}"
        if currency else
        f"{spent:.1f} / {total:.1f}"
    )

    if pct < 0.70:
        css = "budget-ok"
        indicator = "🟢"
    elif pct < 0.90:
        css = "budget-warning"
        indicator = "🟡"
    else:
        css = "budget-danger"
        indicator = "🔴"

    st.markdown(
        f"**{label}** {indicator}  \n"
        f'<span class="{css}">{val_str} ({pct*100:.1f}%)</span>',
        unsafe_allow_html = True,
    )
    st.progress(pct_clamped)


# ── Productivity score badge ──────────────────────────────────────────────────
PRODUCTIVITY_THRESHOLDS = {
    "EXCELLENT": (80, "🟢", "#27AE60"),
    "GOOD":      (60, "🔵", "#2980B9"),
    "NORMAL":    (40, "🟡", "#F39C12"),
    "LOW":       (0,  "🔴", "#E74C3C"),
}


def render_productivity_badge(
    score: float,
    label: str,
    show_score: bool = True,
) -> None:
    """Renders an inline coloured productivity score badge."""
    emoji  = "📊"
    colour = "#7f8c8d"
    for lv, (threshold, em, col) in PRODUCTIVITY_THRESHOLDS.items():
        if score >= threshold:
            emoji  = em
            colour = col
            break

    score_str = f" ({score:.1f})" if show_score else ""
    st.markdown(
        f'<span style="'
        f"color:{colour}; font-weight:700; font-size:0.9rem;"
        f'">{emoji} {label}{score_str}</span>',
        unsafe_allow_html = True,
    )


# ── Form validation helpers ───────────────────────────────────────────────────
def validate_required(fields: dict[str, str]) -> list[str]:
    """
    Validates that all required fields are non-empty.

    Args:
        fields: {field_label: value}

    Returns:
        List of error messages (empty = all valid).
    """
    errors = []
    for label, value in fields.items():
        if not str(value).strip():
            errors.append(f"Le champ **{label}** est obligatoire.")
    return errors


def render_validation_errors(errors: list[str]) -> None:
    """Renders a list of validation errors as a single warning block."""
    if errors:
        st.warning(
            "⚠️ **Veuillez corriger les erreurs suivantes:**\n\n"
            + "\n".join(f"- {e}" for e in errors)
        )


# ── Quick stats expander ──────────────────────────────────────────────────────
def render_quick_stats(
    title:  str,
    stats:  dict[str, str],
    icon:   str = "📊",
) -> None:
    """
    Renders a collapsible quick-stats expander.

    Args:
        title: Expander heading
        stats: {label: value} ordered dict
    """
    with st.expander(f"{icon} {title}", expanded=False):
        for label, value in stats.items():
            col1, col2 = st.columns([3, 2])
            col1.markdown(f"**{label}**")
            col2.markdown(str(value))


# ── Appointment display ───────────────────────────────────────────────────────
def render_appointment_card(appointment: dict) -> None:
    """Renders an appointment block for a request."""
    if not appointment:
        st.caption("📅 Aucun rendez-vous planifié.")
        return

    date_str  = appointment.get("date",  "–")
    time_str  = appointment.get("time",  "–")
    note_str  = appointment.get("note",  "")
    status    = appointment.get("status","–")

    st.markdown(
        f"""
        <div style="
            background:#f0faf8;
            border:1px solid #1ABC9C;
            border-radius:10px;
            padding:12px 16px;
        ">
            <span style="font-weight:700; color:#1B4F72;">
                📅 Rendez-vous
            </span>
            <br>
            🗓️ <b>{date_str}</b> à <b>{time_str}</b>
            {"<br>📝 " + note_str if note_str else ""}
            <br>
            <span style="font-size:0.8rem; color:#7f8c8d;">
                Statut: <code>{status}</code>
            </span>
        </div>
        """,
        unsafe_allow_html = True,
    )


# ── Human-readable time ago ───────────────────────────────────────────────────
def time_ago(iso_date: str) -> str:
    """Returns a human-readable 'X jours', '2 heures', '5 minutes' ago string."""
    if not iso_date:
        return "–"
    try:
        dt      = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        delta   = datetime.utcnow() - dt.replace(tzinfo=None)
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "à l'instant"
        elif seconds < 3_600:
            m = seconds // 60
            return f"il y a {m} min"
        elif seconds < 86_400:
            h = seconds // 3_600
            return f"il y a {h}h"
        elif seconds < 86_400 * 30:
            d = seconds // 86_400
            return f"il y a {d} jour(s)"
        elif seconds < 86_400 * 365:
            mo = seconds // (86_400 * 30)
            return f"il y a {mo} mois"
        else:
            return fmt_date(iso_date)
    except Exception:
        return iso_date[:10]
    # ── Aliases — for dashboards that import short names ─────────────────────────
kpi_row              = render_kpi_row
status_badge         = render_status_badge
channel_badge        = render_channel_badge
workflow_progress    = render_workflow_progress
section_header       = render_section_header
budget_progress      = render_budget_progress
productivity_badge   = render_productivity_badge
empty_state          = render_empty_state
document_list        = render_document_list
notes_timeline       = render_notes_timeline
pagination_controls  = render_pagination_controls
sidebar_user         = render_sidebar_user
