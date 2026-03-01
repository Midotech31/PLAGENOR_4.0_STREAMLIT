# ui/super_admin_dashboard.py
# ── PLAGENOR 4.0 — Super Admin Dashboard ─────────────────────────────────────
# Serves  : ROLE_SUPER_ADMIN
# Scope   : Full platform control — users, members, services, system config,
#           workflow oversight, forced transitions, platform health,
#           full audit trail, data integrity.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import uuid
import hashlib
from datetime import datetime
from typing import Optional

import config
from ui.auth import require_roles
from ui.shared_components import (
    render_sidebar_user,
    render_request_card,
    render_empty_state,
    render_workflow_progress,
    confirm_action,
    resolve_service_name,
    resolve_username,
)
from core.repository import (
    get_all_users,       save_user,
    get_all_members,     save_member,
    get_all_services,    save_service,
    get_all_active_requests,
    get_all_archived_requests,
    get_all_invoices,
    get_all_audit_logs,
    get_all_notifications,
    get_all_documents,
    get_request,         save_request,
    get_member,
    get_user,
)
from core.audit_engine        import safe_get_all_audit_logs
from core.workflow_engine     import transition
from core.productivity_engine import recalculate_all, recalculate_member
from core.exceptions          import PlagenorError


# ── Constants ─────────────────────────────────────────────────────────────────
CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB

ALL_ROLES = [
    config.ROLE_SUPER_ADMIN,
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_MEMBER,
    config.ROLE_FINANCE,
    config.ROLE_REQUESTER,
    config.ROLE_CLIENT,
]

PRODUCTIVITY_EMOJI_MAP = {
    "EXCELLENT": "🟢",
    "GOOD":      "🔵",
    "NORMAL":    "🟡",
    "LOW":       "🔴",
}

ALL_IBTIKAR_STATES = [
    "SUBMITTED", "VALIDATION", "APPROVED", "REJECTED",
    "ASSIGNED", "ANALYSIS_IN_PROGRESS", "ANALYSIS_FINISHED",
    "REPORT_UPLOADED", "COMPLETED",
]
ALL_GENOCLAB_STATES = [
    "SUBMITTED", "VALIDATION", "APPROVED", "REJECTED",
    "QUOTE_DRAFT", "QUOTE_SENT", "QUOTE_VALIDATED_BY_CLIENT",
    "QUOTE_REJECTED_BY_CLIENT", "INVOICE_GENERATED",
    "ASSIGNED", "ANALYSIS_IN_PROGRESS", "ANALYSIS_FINISHED",
    "REPORT_UPLOADED", "COMPLETED",
]


# ── Utility helpers ───────────────────────────────────────────────────────────
def _fmt_date(iso: str) -> str:
    if not iso:
        return "–"
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso[:16]


def _action_ok(msg: str) -> None:
    st.success(f"✅ {msg}")


def _action_err(e: Exception) -> None:
    st.error(f"❌ {e}")


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# ── Data loaders ──────────────────────────────────────────────────────────────
def _load_users() -> list:
    return get_all_users() or []


def _load_members() -> list:
    return get_all_members() or []


def _load_services() -> list:
    return get_all_services() or []


def _load_active_requests() -> list:
    return get_all_active_requests() or []


def _load_archived_requests() -> list:
    return get_all_archived_requests() or []


def _load_invoices() -> list:
    return get_all_invoices() or []


def _load_audit_logs() -> list:
    return safe_get_all_audit_logs()


def _load_notifications() -> list:
    return get_all_notifications() or []


# ── Tab: Platform Health ──────────────────────────────────────────────────────
def _tab_health(actor: dict) -> None:
    st.error("🔴 TEST BANNER — _tab_health IS RENDERING")
    st.markdown("## 🏥 Santé de la plateforme")

    users        = _load_users()
    members      = _load_members()
    services     = _load_services()
    active_reqs  = _load_active_requests()
    archived     = _load_archived_requests()
    invoices     = _load_invoices()
    notifs       = _load_notifications()
    logs         = _load_audit_logs() or []   # ← single line, guarded
    # ── Global KPIs ───────────────────────────────────────────────────────────
    st.markdown("### 📊 Vue globale")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("👥 Utilisateurs",        len(users))
    c2.metric("🧬 Membres",             len(members))
    c3.metric("🔬 Services",            len(services))
    c4.metric("📋 Demandes actives",    len(active_reqs))
    c5.metric("📦 Archivées",           len(archived))
    c6.metric("🧾 Factures",            len(invoices))
    st.divider()

    # ── User activity ─────────────────────────────────────────────────────────
    st.markdown("### 👥 Utilisateurs par rôle")
    role_counts: dict = {}
    for u in users:
        role = u.get("role", "UNKNOWN")
        role_counts[role] = role_counts.get(role, 0) + 1

    cols = st.columns(len(ALL_ROLES))
    for i, role in enumerate(ALL_ROLES):
        count    = role_counts.get(role, 0)
        active_u = sum(
            1 for u in users
            if u.get("role") == role and u.get("active", True)
        )
        cols[i].metric(
            role.replace("ROLE_", "").replace("_", " ").title(),
            count,
            delta = f"{active_u} actif(s)" if count else None,
        )
    st.divider()

    # ── Request pipeline ──────────────────────────────────────────────────────
    st.markdown("### 📋 Pipeline des demandes actives")
    status_counts: dict = {}
    for req in active_reqs:
        s = req.get("status", "UNKNOWN")
        status_counts[s] = status_counts.get(s, 0) + 1

    if status_counts:
        cols = st.columns(min(len(status_counts), 5))
        for i, (status, count) in enumerate(
            sorted(status_counts.items(), key=lambda x: x[1], reverse=True)
        ):
            cols[i % len(cols)].metric(status, count)
    else:
        st.info("Aucune demande active.")

    st.divider()

    # ── Data file health check ────────────────────────────────────────────────
    st.markdown("### 🗂️ Vérification des fichiers de données")
    data_files = {
        "Utilisateurs":          getattr(config, "USERS_FILE",               "data/users.json"),
        "Membres":               getattr(config, "MEMBERS_FILE",             "data/members.json"),
        "Services":              getattr(config, "SERVICES_FILE",            "data/services.json"),
        "Demandes actives":      getattr(config, "ACTIVE_REQUESTS_FILE",     "data/active_requests.json"),
        "Demandes archivées":    getattr(config, "ARCHIVED_REQUESTS_FILE",   "data/archived_requests.json"),
        "Factures":              getattr(config, "INVOICES_FILE",            "data/invoices.json"),
        "Séquence factures":     getattr(config, "INVOICE_SEQUENCE_FILE",    "data/invoice_sequence.json"),
        "Audit logs":            getattr(config, "AUDIT_LOGS_FILE",          "data/audit_logs.json"),
        "Documents":             getattr(config, "DOCUMENTS_FILE",           "data/documents.json"),
        "Notifications":         getattr(config, "NOTIFICATIONS_FILE",       "data/notifications.json"),
    }

    col1, col2 = st.columns(2)
    for i, (label, path) in enumerate(data_files.items()):
        col = col1 if i % 2 == 0 else col2
        exists = os.path.exists(path)
        size   = (
            f"{os.path.getsize(path) / 1024:.1f} KB"
            if exists else "–"
        )
        with col:
            if exists:
                st.markdown(f"✅ **{label}** — `{path}` ({size})")
            else:
                st.error(f"❌ **{label}** — `{path}` MANQUANT")

    st.divider()

    # ── Notification stats ────────────────────────────────────────────────────
    st.markdown("### 🔔 Notifications système")
    unread = sum(1 for n in notifs if not n.get("read"))
    c1, c2, c3 = st.columns(3)
    c1.metric("🔔 Total notifications", len(notifs))
    c2.metric("🔵 Non lues",            unread)
    c3.metric("📋 Logs d'audit",        len(logs))

    # ── Member availability ───────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🧬 Disponibilité des membres")
    available   = [m for m in members if m.get("available",  True)]
    unavailable = [m for m in members if not m.get("available", True)]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**🟢 Disponibles ({len(available)})**")
        for m in available:
            load = f"{m.get('current_load',0)}/{m.get('max_load',5)}"
            st.markdown(f"- **{m.get('name','–')}** — Charge: `{load}`")
    with c2:
        st.markdown(f"**🔴 Indisponibles ({len(unavailable)})**")
        for m in unavailable:
            st.markdown(f"- **{m.get('name','–')}**")


# ── Tab: Users ────────────────────────────────────────────────────────────────
def _tab_users(actor: dict) -> None:
    st.markdown("## 👥 Gestion des comptes utilisateurs")

    users = _load_users()

    # ── User list ─────────────────────────────────────────────────────────────
    st.markdown("### 📋 Comptes existants")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        role_filter = st.selectbox(
            "Filtrer par rôle", ["Tous"] + ALL_ROLES, key="usr_role_filter"
        )
    with col_f2:
        status_filter = st.selectbox(
            "Statut", ["Tous", "🟢 Actifs", "🔴 Désactivés"],
            key = "usr_status_filter",
        )

    filtered = users
    if role_filter != "Tous":
        filtered = [u for u in filtered if u.get("role") == role_filter]
    if status_filter == "🟢 Actifs":
        filtered = [u for u in filtered if u.get("active", True)]
    elif status_filter == "🔴 Désactivés":
        filtered = [u for u in filtered if not u.get("active", True)]

    st.caption(f"**{len(filtered)}** / {len(users)} compte(s)")
    st.divider()

    for u in filtered:
        icon     = "🟢" if u.get("active", True) else "🔴"
        role_tag = u.get("role", "–").replace("ROLE_", "")
        org      = u.get("organization_id", "–") or "–"

        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
        with col1:
            st.markdown(
                f"{icon} **{u.get('username','–')}**  \n"
                f"ID: `{u.get('id','')[:8]}`"
            )
        with col2:
            st.markdown(f"Rôle: `{role_tag}`  \nOrg: `{org}`")
        with col3:
            # Toggle active/inactive
            current_active = u.get("active", True)
            new_active = st.toggle(
                "Actif",
                value = current_active,
                key   = f"toggle_user_{u['id']}",
            )
            if new_active != current_active:
                u_copy = dict(u)
                u_copy["active"] = new_active
                save_user(u_copy)
                _action_ok(
                    f"Utilisateur '{u.get('username')}' "
                    f"{'activé' if new_active else 'désactivé'}."
                )
                st.cache_data.clear()
                st.rerun()
        with col4:
            # Role change
            new_role = st.selectbox(
                "Rôle",
                ALL_ROLES,
                index   = ALL_ROLES.index(u.get("role", ALL_ROLES[-1]))
                          if u.get("role") in ALL_ROLES else 0,
                key     = f"role_sel_{u['id']}",
                label_visibility = "collapsed",
            )
            if new_role != u.get("role"):
                if confirm_action(
                    key     = f"change_role_{u['id']}",
                    label   = "Changer le rôle",
                    message = (
                        f"Changer le rôle de '{u.get('username')}' "
                        f"de `{u.get('role')}` → `{new_role}` ?"
                    ),
                ):
                    u_copy = dict(u)
                    u_copy["role"] = new_role
                    save_user(u_copy)
                    _action_ok(f"Rôle mis à jour → `{new_role}`.")
                    st.cache_data.clear()
                    st.rerun()
        st.divider()

    # ── Create new user ───────────────────────────────────────────────────────
    st.markdown("### ➕ Créer un nouvel utilisateur")
    with st.form("create_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            new_username = st.text_input("Nom d'utilisateur *", key="new_uname")
            new_password = st.text_input("Mot de passe *", type="password", key="new_pw")
        with col2:
            new_role = st.selectbox("Rôle *", ALL_ROLES, key="new_role")
            new_email = st.text_input("Email (optionnel)", key="new_email")
        new_org = st.text_input("Organisation ID (optionnel)", key="new_org")

        if st.form_submit_button("➕ Créer l'utilisateur", use_container_width=True):
            if not new_username.strip() or not new_password.strip():
                st.warning("⚠️ Nom d'utilisateur et mot de passe obligatoires.")
            elif any(u.get("username") == new_username for u in users):
                st.error(f"❌ L'utilisateur '{new_username}' existe déjà.")
            else:
                save_user({
                    "id":              str(uuid.uuid4()),
                    "username":        new_username.strip(),
                    "password_hash":   _hash_password(new_password),
                    "role":            new_role,
                    "email":           new_email.strip() or None,
                    "organization_id": new_org.strip() or None,
                    "active":          True,
                    "created_at":      datetime.utcnow().isoformat(),
                    "created_by":      actor.get("id", "system"),
                })
                _action_ok(f"Utilisateur '{new_username}' créé avec le rôle `{new_role}`.")
                st.cache_data.clear()
                st.rerun()

    # ── Change password ───────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🔑 Réinitialiser un mot de passe")
    with st.form("reset_pw_form"):
        users_opts = {u["username"]: u for u in users}
        sel_user   = st.selectbox(
            "Sélectionner l'utilisateur", list(users_opts.keys()),
            key = "reset_pw_sel",
        )
        new_pw1 = st.text_input("Nouveau mot de passe *",    type="password", key="new_pw1")
        new_pw2 = st.text_input("Confirmer le mot de passe", type="password", key="new_pw2")

        if st.form_submit_button("🔑 Réinitialiser", use_container_width=True):
            if not new_pw1.strip():
                st.warning("⚠️ Le mot de passe ne peut pas être vide.")
            elif new_pw1 != new_pw2:
                st.error("❌ Les mots de passe ne correspondent pas.")
            else:
                target = dict(users_opts[sel_user])
                target["password_hash"] = _hash_password(new_pw1)
                save_user(target)
                _action_ok(f"Mot de passe de '{sel_user}' réinitialisé.")
                st.cache_data.clear()
                st.rerun()


# ── Tab: Members ──────────────────────────────────────────────────────────────
def _tab_members(actor: dict) -> None:
    st.markdown("## 🧬 Gestion des membres (analystes)")

    members  = _load_members()
    users    = _load_users()
    services = _load_services()

    # ── Member list ───────────────────────────────────────────────────────────
    st.markdown("### 📋 Membres enregistrés")
    if not members:
        render_empty_state(
            "🧬", "Aucun membre",
            "Enregistrez des membres ci-dessous.",
        )
    else:
        for m in members:
            avail   = "🟢 Disponible" if m.get("available", True) else "🔴 Indisponible"
            load    = f"{m.get('current_load',0)}/{m.get('max_load',5)}"
            score   = float(m.get("productivity_score", 50))
            label   = m.get("productivity_label", "NORMAL")
            emoji   = PRODUCTIVITY_EMOJI_MAP.get(label, "📊")

            col1, col2, col3 = st.columns([4, 3, 2])
            with col1:
                st.markdown(
                    f"**{m.get('name','–')}** — `{m.get('id','')[:8]}`  \n"
                    f"User lié: `{m.get('user_id','–')[:8]}`"
                )
            with col2:
                st.markdown(
                    f"{avail}  \n"
                    f"Charge: `{load}` | "
                    f"{emoji} Score: `{score:.1f}`"
                )
            with col3:
                new_av = st.toggle(
                    "Disponible",
                    value = m.get("available", True),
                    key   = f"avail_{m['id']}",
                )
                if new_av != m.get("available", True):
                    m_copy = dict(m)
                    m_copy["available"] = new_av
                    save_member(m_copy)
                    _action_ok(f"Disponibilité de '{m.get('name')}' mise à jour.")
                    st.cache_data.clear()
                    st.rerun()
            st.divider()

    # ── Register member ───────────────────────────────────────────────────────
    st.markdown("### ➕ Enregistrer un nouveau membre")
    user_accounts = [
        u for u in users if u.get("role") == config.ROLE_MEMBER
    ]
    if not user_accounts:
        st.info(
            "ℹ️ Aucun compte avec le rôle ROLE_MEMBER trouvé.  \n"
            "Créez d'abord un compte utilisateur dans l'onglet **👥 Utilisateurs**."
        )
    else:
        with st.form("create_member_form"):
            u_opts   = {u["username"]: u["id"] for u in user_accounts}
            sel_u    = st.selectbox("Lier au compte utilisateur *", list(u_opts.keys()))
            m_name   = st.text_input("Nom complet *", key="m_name")
            m_maxl   = st.number_input("Charge maximale", min_value=1, max_value=20, value=5)

            if st.form_submit_button("➕ Enregistrer", use_container_width=True):
                if not m_name.strip():
                    st.warning("⚠️ Le nom est obligatoire.")
                elif any(
                    m.get("user_id") == u_opts[sel_u] for m in members
                ):
                    st.error("❌ Ce compte est déjà lié à un membre.")
                else:
                    save_member({
                        "id":                 str(uuid.uuid4()),
                        "user_id":            u_opts[sel_u],
                        "name":               m_name.strip(),
                        "skills":             {},
                        "current_load":       0,
                        "max_load":           int(m_maxl),
                        "available":          True,
                        "productivity_score": 50.0,
                        "productivity_label": "NORMAL",
                        "productivity_history": [],
                        "created_at":         datetime.utcnow().isoformat(),
                    })
                    _action_ok(f"Membre '{m_name}' enregistré.")
                    st.cache_data.clear()
                    st.rerun()

    # ── Edit member skills ────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🎯 Éditer les compétences d'un membre")
    if members and services:
        with st.form("skill_edit_form"):
            mem_opts = {m["name"]: m for m in members}
            svc_opts = {s["name"]: s for s in services}
            sel_m    = st.selectbox("Membre", list(mem_opts.keys()), key="sk_m")
            sel_s    = st.selectbox("Service", list(svc_opts.keys()), key="sk_s")
            sk_score = st.slider("Score de compétence (0–100)", 0.0, 100.0, 50.0, key="sk_v")

            if st.form_submit_button("💾 Enregistrer", use_container_width=True):
                m_obj = dict(mem_opts[sel_m])
                s_obj = svc_opts[sel_s]
                m_obj.setdefault("skills", {})[s_obj["id"]] = float(sk_score)
                save_member(m_obj)
                _action_ok(f"Compétence '{sel_s}' pour '{sel_m}' → {sk_score:.0f}.")
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("Aucun membre ou service disponible.")

    # ── Productivity management ───────────────────────────────────────────────
    st.divider()
    st.markdown("### 📊 Gestion de la productivité")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("#### 🔄 Recalculer tous les scores")
        if st.button(
            "Recalculer tous les membres",
            key                 = "sa_recalc_all",
            use_container_width = True,
        ):
            with st.spinner("Recalcul en cours..."):
                try:
                    results = recalculate_all(actor)
                    _action_ok(f"{len(results)} membres recalculés.")
                    st.cache_data.clear()
                    st.rerun()
                except PlagenorError as e:
                    _action_err(e)

    with col_r2:
        st.markdown("#### 📊 Recalculer un membre")
        if members:
            with st.form("sa_recalc_single"):
                m_opts = {m["name"]: m["id"] for m in members}
                sel_m2 = st.selectbox("Membre", list(m_opts.keys()), key="sa_recalc_sel")
                if st.form_submit_button("Recalculer", use_container_width=True):
                    try:
                        result = recalculate_member(m_opts[sel_m2], user=actor)
                        st.success(
                            f"Score: {float(result.get('score',0)):.1f} — "
                            f"Niveau: {result.get('label','–')}"
                        )
                        st.cache_data.clear()
                        st.rerun()
                    except PlagenorError as e:
                        _action_err(e)


# ── Tab: Services ─────────────────────────────────────────────────────────────
def _tab_services(actor: dict) -> None:
    st.markdown("## 🔬 Catalogue des services")

    services = _load_services()

    # ── Service list ──────────────────────────────────────────────────────────
    st.markdown("### 📋 Services enregistrés")
    if not services:
        render_empty_state(
            "🔬", "Aucun service",
            "Ajoutez des services ci-dessous.",
        )
    else:
        ch_filter = st.selectbox(
            "Filtrer par canal",
            ["Tous", CHANNEL_IBTIKAR, CHANNEL_GENOCLAB],
            key = "svc_filter",
        )
        filtered = services
        if ch_filter != "Tous":
            filtered = [s for s in services if s.get("channel") == ch_filter]

        for svc in filtered:
            active_icon  = "🟢" if svc.get("active", True) else "🔴"
            base_price   = float(svc.get("base_price", 0))
            channel_icon = "🌱" if svc.get("channel") == CHANNEL_IBTIKAR else "🧬"

            col1, col2, col3 = st.columns([4, 3, 2])
            with col1:
                st.markdown(
                    f"{active_icon} **{svc.get('name','–')}**  \n"
                    f"ID: `{svc.get('id','')[:8]}`  \n"
                    f"{channel_icon} Canal: `{svc.get('channel','–')}`"
                )
            with col2:
                st.markdown(
                    f"Prix de base: **{base_price:,.0f} DZD**  \n"
                    f"_{svc.get('description','–')[:60]}_"
                )
            with col3:
                new_active = st.toggle(
                    "Actif",
                    value = svc.get("active", True),
                    key   = f"svc_active_{svc['id']}",
                )
                if new_active != svc.get("active", True):
                    svc_copy = dict(svc)
                    svc_copy["active"] = new_active
                    save_service(svc_copy)
                    _action_ok(
                        f"Service '{svc.get('name')}' "
                        f"{'activé' if new_active else 'désactivé'}."
                    )
                    st.cache_data.clear()
                    st.rerun()
            st.divider()

    # ── Add service ───────────────────────────────────────────────────────────
    st.markdown("### ➕ Ajouter un service")
    with st.form("add_service_form"):
        col1, col2 = st.columns(2)
        with col1:
            svc_name  = st.text_input("Nom du service *", key="svc_name")
            svc_chan  = st.selectbox(
                "Canal *", [CHANNEL_IBTIKAR, CHANNEL_GENOCLAB], key="svc_chan"
            )
        with col2:
            svc_price = st.number_input(
                "Prix de base (DZD)", min_value=0.0, step=500.0, key="svc_price"
            )
            svc_code  = st.text_input(
                "Code service (optionnel)", key="svc_code",
                placeholder = "Ex: WGS-001"
            )
        svc_desc = st.text_area("Description", key="svc_desc", height=80)

        if st.form_submit_button("➕ Ajouter le service", use_container_width=True):
            if not svc_name.strip():
                st.warning("⚠️ Le nom du service est obligatoire.")
            elif any(s.get("name") == svc_name for s in services):
                st.error(f"❌ Le service '{svc_name}' existe déjà.")
            else:
                save_service({
                    "id":          str(uuid.uuid4()),
                    "name":        svc_name.strip(),
                    "channel":     svc_chan,
                    "description": svc_desc.strip(),
                    "base_price":  float(svc_price),
                    "code":        svc_code.strip() or None,
                    "active":      True,
                    "created_at":  datetime.utcnow().isoformat(),
                    "created_by":  actor.get("id", "system"),
                })
                _action_ok(f"Service '{svc_name}' ajouté.")
                st.cache_data.clear()
                st.rerun()

    # ── Edit service price ────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 💰 Modifier le prix d'un service")
    if services:
        with st.form("edit_price_form"):
            svc_opts  = {s["name"]: s for s in services}
            sel_svc   = st.selectbox("Service", list(svc_opts.keys()), key="ep_svc")
            new_price = st.number_input(
                "Nouveau prix de base (DZD)",
                min_value = 0.0,
                value     = float(svc_opts[sel_svc].get("base_price", 0)),
                step      = 500.0,
                key       = "ep_price",
            )
            if st.form_submit_button("💾 Enregistrer", use_container_width=True):
                svc_copy = dict(svc_opts[sel_svc])
                svc_copy["base_price"]  = float(new_price)
                svc_copy["updated_at"]  = datetime.utcnow().isoformat()
                svc_copy["updated_by"]  = actor.get("id", "system")
                save_service(svc_copy)
                _action_ok(f"Prix de '{sel_svc}' → {new_price:,.0f} DZD.")
                st.cache_data.clear()
                st.rerun()


# ── Tab: Workflow Supervision ─────────────────────────────────────────────────
def _tab_workflow(actor: dict) -> None:
    st.markdown("## ⚙️ Supervision et forçage des transitions")
    st.caption(
        "⚠️ **Zone de supervision.** Les transitions forcées contournent "
        "les règles métier normales. Utiliser uniquement en cas de blocage avéré."
    )

    active_reqs = _load_active_requests()
    if not active_reqs:
        render_empty_state(
            "⚙️", "Aucune demande active",
            "Aucune demande à superviser.",
        )
        return

    # ── Request selector ──────────────────────────────────────────────────────
    opts = {
        f"[{r.get('channel','?')}] {r['id'][:8]} — "
        f"{resolve_service_name(r.get('service_id',''))} "
        f"({r.get('status','')})" : r
        for r in active_reqs
    }
    sel = st.selectbox("Sélectionner une demande", list(opts.keys()), key="wf_sel")
    req = opts[sel]

    render_request_card(req)
    render_workflow_progress(req.get("channel", ""), req.get("status", ""))
    st.divider()

    # ── Request details ───────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f"**ID:** `{req['id']}`  \n"
            f"**Canal:** `{req.get('channel','–')}`  \n"
            f"**Statut actuel:** `{req.get('status','–')}`  \n"
            f"**Assigné à:** `{req.get('assigned_member_name','–')}`"
        )
    with col2:
        st.markdown(
            f"**Soumis le:** {req.get('created_at','–')[:10]}  \n"
            f"**Dernière MAJ:** {req.get('updated_at','–')[:10]}  \n"
            f"**Soumis par:** `{resolve_username(req.get('submitted_by_user_id',''))}`"
        )

    # ── Status history ────────────────────────────────────────────────────────
    history = req.get("status_history", [])
    if history:
        with st.expander("📅 Historique des transitions"):
            for entry in reversed(history):
                st.markdown(
                    f"- `{entry.get('timestamp','')[:16]}` → "
                    f"**{entry.get('to_state', entry.get('state','–'))}** "
                    + (f"— _{entry.get('notes','')}_" if entry.get('notes') else "")
                )

    st.divider()

    # ── Forced transition ─────────────────────────────────────────────────────
    st.markdown("### 🔧 Forcer une transition d'état")
    st.warning(
        "⚠️ Cette action contourne le moteur de workflow. "
        "Elle est enregistrée dans l'audit trail."
    )

    channel      = req.get("channel", CHANNEL_IBTIKAR)
    state_options = (
        ALL_GENOCLAB_STATES if channel == CHANNEL_GENOCLAB
        else ALL_IBTIKAR_STATES
    )

    with st.form(f"force_transition_{req['id']}"):
        target_state = st.selectbox(
            "État cible *",
            [s for s in state_options if s != req.get("status")],
            key = f"ft_state_{req['id']}",
        )
        force_note = st.text_area(
            "Justification obligatoire *",
            key         = f"ft_note_{req['id']}",
            height      = 80,
            placeholder = "Ex: Blocage technique après redémarrage du serveur.",
        )
        confirmed = st.form_submit_button(
            f"🔧 Forcer → {target_state}",
            use_container_width = True,
        )
        if confirmed:
            if not force_note.strip():
                st.warning("⚠️ La justification est obligatoire pour un forçage.")
            else:
                try:
                    # Directly save the request bypassing normal transition rules
                    from core.repository import save_request as _save_req
                    from core.audit_engine import log_action
                    req_copy = dict(req)
                    prev_status = req_copy.get("status", "–")
                    req_copy["status"]     = target_state
                    req_copy["updated_at"] = datetime.utcnow().isoformat()
                    history_entry = {
                        "from_state": prev_status,
                        "to_state":   target_state,
                        "timestamp":  datetime.utcnow().isoformat(),
                        "actor_id":   actor.get("id", "system"),
                        "forced":     True,
                        "notes":      force_note,
                    }
                    req_copy.setdefault("status_history", []).append(history_entry)
                    _save_req(req_copy)
                    try:
                        log_action(
                            action      = "FORCED_TRANSITION",
                            entity_type = "REQUEST",
                            entity_id   = req["id"],
                            actor       = actor,
                            details     = (
                                f"{prev_status} → {target_state} | "
                                f"Justif: {force_note}"
                            ),
                        )
                    except Exception:
                        pass
                    _action_ok(
                        f"Transition forcée: `{prev_status}` → `{target_state}`."
                    )
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    _action_err(e)

    # ── Manual field edit ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📝 Modifier des champs libres de la demande")
    st.caption(
        "Pour corriger des données erronées: "
        "quote_amount, approved_budget, assigned_member_name."
    )
    with st.form(f"field_edit_{req['id']}"):
        col1, col2 = st.columns(2)
        with col1:
            new_quote = st.number_input(
                "quote_amount (DZD HT)",
                min_value = 0.0,
                value     = float(req.get("quote_amount", 0)),
                step      = 1_000.0,
                key       = f"fe_quote_{req['id']}",
            )
            new_budget = st.number_input(
                "approved_budget (DZD)",
                min_value = 0.0,
                value     = float(req.get("approved_budget", 0)),
                step      = 1_000.0,
                key       = f"fe_budget_{req['id']}",
            )
        with col2:
            new_member_name = st.text_input(
                "assigned_member_name",
                value = req.get("assigned_member_name", ""),
                key   = f"fe_mname_{req['id']}",
            )
            new_member_id = st.text_input(
                "assigned_member_id",
                value = req.get("assigned_member_id", ""),
                key   = f"fe_mid_{req['id']}",
            )
        edit_note = st.text_input(
            "Note de modification *",
            key         = f"fe_note_{req['id']}",
            placeholder = "Ex: Correction montant devis après erreur de saisie.",
        )
        if st.form_submit_button("💾 Enregistrer les modifications", use_container_width=True):
            if not edit_note.strip():
                st.warning("⚠️ La note de modification est obligatoire.")
            else:
                from core.repository import save_request as _save_req
                req_copy = dict(req)
                req_copy["quote_amount"]          = float(new_quote)
                req_copy["approved_budget"]        = float(new_budget)
                req_copy["assigned_member_name"]   = new_member_name.strip() or None
                req_copy["assigned_member_id"]     = new_member_id.strip() or None
                req_copy["updated_at"]             = datetime.utcnow().isoformat()
                req_copy.setdefault("edit_history", []).append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "actor_id":  actor.get("id", "system"),
                    "note":      edit_note,
                })
                _save_req(req_copy)
                _action_ok("Champs mis à jour.")
                st.cache_data.clear()
                st.rerun()


# ── Tab: System Config ────────────────────────────────────────────────────────
def _tab_config(actor: dict) -> None:
    st.markdown("## ⚙️ Configuration système")
    st.caption(
        "Affichage des paramètres actuels de `config.py`.  \n"
        "Pour les modifier, éditez `config.py` et redémarrez l'application."
    )

    # ── Key config params ──────────────────────────────────────────────────────
    st.markdown("### 🔧 Paramètres actifs")

    config_params = {
        "ROLE_SUPER_ADMIN":         getattr(config, "ROLE_SUPER_ADMIN",         "–"),
        "ROLE_PLATFORM_ADMIN":      getattr(config, "ROLE_PLATFORM_ADMIN",      "–"),
        "ROLE_MEMBER":              getattr(config, "ROLE_MEMBER",              "–"),
        "ROLE_FINANCE":             getattr(config, "ROLE_FINANCE",             "–"),
        "ROLE_REQUESTER":           getattr(config, "ROLE_REQUESTER",           "–"),
        "ROLE_CLIENT":              getattr(config, "ROLE_CLIENT",              "–"),
        "CHANNEL_IBTIKAR":          getattr(config, "CHANNEL_IBTIKAR",          "–"),
        "CHANNEL_GENOCLAB":         getattr(config, "CHANNEL_GENOCLAB",         "–"),
        "VAT_RATE":                 getattr(config, "VAT_RATE",                 "–"),
        "IBTIKAR_BUDGET_CAP":       getattr(config, "IBTIKAR_BUDGET_CAP",       "–"),
        "INVOICE_SEQUENCE_FILE":    getattr(config, "INVOICE_SEQUENCE_FILE",    "–"),
        "ACTIVE_REQUESTS_FILE":     getattr(config, "ACTIVE_REQUESTS_FILE",     "–"),
        "ARCHIVED_REQUESTS_FILE":   getattr(config, "ARCHIVED_REQUESTS_FILE",   "–"),
        "NOTIFICATIONS_FILE":       getattr(config, "NOTIFICATIONS_FILE",       "–"),
    }

    col1, col2 = st.columns(2)
    for i, (key, val) in enumerate(config_params.items()):
        col = col1 if i % 2 == 0 else col2
        with col:
            st.markdown(f"**`{key}`** = `{val}`")

    st.divider()

    # ── Data directory ────────────────────────────────────────────────────────
    st.markdown("### 🗂️ Répertoire de données")
    data_dir = getattr(config, "DATA_DIR", "data")
    if os.path.exists(data_dir):
        files = os.listdir(data_dir)
        st.success(f"✅ `{data_dir}/` — {len(files)} fichier(s)")
        for f in sorted(files):
            fpath = os.path.join(data_dir, f)
            size  = os.path.getsize(fpath) / 1024
            st.markdown(f"- `{f}` — {size:.1f} KB")
    else:
        st.error(f"❌ Répertoire `{data_dir}/` introuvable.")
        if st.button("📁 Créer le répertoire data/", key="create_data_dir"):
            try:
                os.makedirs(data_dir, exist_ok=True)
                _action_ok(f"Répertoire `{data_dir}/` créé.")
                st.rerun()
            except Exception as e:
                _action_err(e)

    st.divider()

    # ── Cache management ──────────────────────────────────────────────────────
    st.markdown("### 🔄 Gestion du cache")
    st.caption("Vide le cache Streamlit @st.cache_data pour forcer le rechargement.")
    if st.button(
        "🔄 Vider le cache de l'application",
        key                 = "clear_cache_btn",
        use_container_width = True,
    ):
        st.cache_data.clear()
        _action_ok("Cache vidé. Les données seront rechargées au prochain accès.")
        st.rerun()

    st.divider()

    # ── Workflow transitions config ───────────────────────────────────────────
    st.markdown("### 🔀 Transitions workflow configurées")

    col_ib, col_gc = st.columns(2)
    with col_ib:
        st.markdown("**🌱 IBTIKAR**")
        ibtikar_t = getattr(config, "IBTIKAR_TRANSITIONS", {})
        if ibtikar_t:
            for from_s, to_s in ibtikar_t.items():
                st.markdown(f"- `{from_s}` → `{to_s}`")
        else:
            st.caption("Non configuré dans config.py")

    with col_gc:
        st.markdown("**🧬 GENOCLAB**")
        genoclab_t = getattr(config, "GENOCLAB_TRANSITIONS", {})
        if genoclab_t:
            for from_s, to_s in genoclab_t.items():
                st.markdown(f"- `{from_s}` → `{to_s}`")
        else:
            st.caption("Non configuré dans config.py")


# ── Tab: Full Audit Trail ─────────────────────────────────────────────────────
def _tab_audit(actor: dict) -> None:
    st.markdown("## 🔍 Journal d'audit complet")

    logs = sorted(
        _load_audit_logs() or [],
        key     = lambda x: x.get("timestamp", ""),
        reverse = True,
    )

    # ── Filter controls ───────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        action_filter = st.text_input(
            "🔍 Filtrer par action",
            key         = "sa_audit_action",
            placeholder = "Ex: TRANSITION, INVOICE, ASSIGN…",
        )
    with col2:
        entity_filter = st.text_input(
            "🔍 Filtrer par entité",
            key         = "sa_audit_entity",
            placeholder = "Ex: REQUEST, USER, INVOICE…",
        )
    with col3:
        user_filter = st.text_input(
            "🔍 Filtrer par utilisateur",
            key         = "sa_audit_user",
            placeholder = "Nom ou ID…",
        )

    max_entries = st.slider(
        "Nombre max d'entrées à afficher",
        min_value = 50,
        max_value = 500,
        value     = 100,
        step      = 50,
        key       = "sa_audit_max",
    )

    filtered = logs

    if action_filter:
        sq = action_filter.upper()
        filtered = [l for l in filtered if sq in l.get("action", "").upper()]

    if entity_filter:
        sq = entity_filter.upper()
        filtered = [
            l for l in filtered
            if sq in l.get("entity_type", "").upper()
        ]

    if user_filter:
        sq = user_filter.lower()
        filtered = [
            l for l in filtered
            if sq in resolve_username(l.get("user_id", "")).lower()
            or sq in l.get("user_id", "").lower()
        ]

    st.caption(
        f"Affichage: **{min(len(filtered), max_entries)}** "
        f"sur {len(filtered)} entrée(s) filtrée(s) "
        f"(total: {len(logs)})"
    )

    # ── Export audit log as CSV ───────────────────────────────────────────────
    if filtered:
        csv_lines = ["timestamp,action,entity_type,entity_id,user,details"]
        for l in filtered[:max_entries]:
            csv_lines.append(
                f"{l.get('timestamp','')[:16]},"
                f"{l.get('action','')},"
                f"{l.get('entity_type','')},"
                f"{str(l.get('entity_id',''))[:8]},"
                f"{resolve_username(l.get('user_id',''))},"
                f"\"{l.get('details', l.get('notes',''))}\""
            )
        st.download_button(
            label               = "📥 Exporter l'audit (CSV)",
            data                = "\n".join(csv_lines),
            file_name           = f"audit_plagenor_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            mime                = "text/csv",
            key                 = "export_audit_csv",
            use_container_width = False,
        )

    st.divider()

    if not filtered:
        render_empty_state("🔍", "Aucun log", "Aucune entrée ne correspond aux filtres.")
        return

    for log in filtered[:max_entries]:
        ts      = log.get("timestamp", "")[:16]
        action  = log.get("action", "–")
        etype   = log.get("entity_type", "–")
        eid     = str(log.get("entity_id", ""))[:8]
        uid     = log.get("user_id", "")
        uname   = resolve_username(uid)
        details = log.get("details", log.get("notes", ""))
        forced  = log.get("forced", False)

        forced_badge = " 🔧 **FORCÉ**" if forced else ""

        # Colour-code by action category
        if "FORCED" in action:
            icon = "🔧"
        elif "TRANSITION" in action or "ADVANCE" in action:
            icon = "🔀"
        elif "ASSIGN" in action:
            icon = "🧬"
        elif "INVOICE" in action or "PAYMENT" in action:
            icon = "🧾"
        elif "QUOTE" in action:
            icon = "💵"
        elif "USER" in action or "AUTH" in action:
            icon = "👤"
        elif "REJECT" in action:
            icon = "🚫"
        elif "CREATE" in action or "SUBMIT" in action:
            icon = "✅"
        elif "ARCHIVE" in action:
            icon = "📦"
        else:
            icon = "📋"

        st.markdown(
            f"{icon} `{ts}` | **{action}**{forced_badge} "
            f"| `{etype}` `{eid}` "
            f"| 👤 `{uname}`"
            + (f"  \n  _{details}_" if details else "")
        )
        st.divider()


# ── Entry point ───────────────────────────────────────────────────────────────
def render() -> None:
    user = st.session_state.get("user")
    if not user:
        st.error("Non authentifié.")
        return
    render_sidebar_user(user)

    st.title("🛡️ PLAGENOR 4.0 — Super Admin & Gouvernance")
    st.caption(
        f"Connecté en tant que: **{user.get('username')}** "
        f"| Rôle: `{user.get('role')}`  \n"
        f"⚠️ Accès complet à la plateforme — agir avec précaution."
    )

    # ── Global KPI header ──────────────────────────────────────────────────────
    users       = _load_users()
    members     = _load_members()
    active_reqs = _load_active_requests()
    invoices    = _load_invoices()
    avg_prod    = (
        sum(float(m.get("productivity_score", 50)) for m in members) / len(members)
        if members else 0.0
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("👥 Utilisateurs",       len(users))
    c2.metric("🧬 Membres",            len(members))
    c3.metric("📋 Demandes actives",   len(active_reqs))
    c4.metric("📦 Archivées",          len(_load_archived_requests()))
    c5.metric("🧾 Factures",           len(invoices))
    c6.metric("📊 Prod. moy.",         f"{avg_prod:.1f}")

    st.divider()

    tabs = st.tabs([
        "🏥 Santé",
        "👥 Utilisateurs",
        "🧬 Membres",
        "🔬 Services",
        "⚙️ Supervision",
        "🔧 Config",
        "🔍 Audit",
    ])

    with tabs[0]: _tab_health(user)
    with tabs[1]: _tab_users(user)
    with tabs[2]: _tab_members(user)
    with tabs[3]: _tab_services(user)
    with tabs[4]: _tab_workflow(user)
    with tabs[5]: _tab_config(user)
    with tabs[6]: _tab_audit(user)
