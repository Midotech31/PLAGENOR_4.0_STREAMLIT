# app.py
# ── PLAGENOR 4.0 — Master Application Entry Point ────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta

import streamlit as st

# Safe import block to debug Cloud issues
try:
    from werkzeug.security import generate_password_hash, check_password_hash  # ← FIX

    import config
    from core.repository import (
        ensure_data_directory,
        get_user_by_username,
        get_user,
        get_unread_notifications_for_user,
        mark_all_notifications_read_for_user,
        get_member_by_user_id,
    )
    from core.audit_engine import log_auth_event

    init_error = None
except Exception as e:
    init_error = str(e)

# If imports failed, show the error and stop
if init_error:
    st.write("INIT ERROR:")
    st.code(init_error)
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title            = f"{config.PLATFORM_NAME}",
    page_icon             = "🔬",
    layout                = "wide",
    initial_sidebar_state = "expanded",
    menu_items            = {
        "Get Help":    None,
        "Report a bug": None,
        "About": (
            f"**{config.PLATFORM_NAME}**  \n"
            f"{config.PLATFORM_SUBTITLE}  \n"
            f"{config.PLATFORM_INSTITUTION}  \n"
            f"© {config.PLATFORM_YEAR} {config.PLATFORM_AUTHOR}"
        ),
    },
)


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL CSS
# ══════════════════════════════════════════════════════════════════════════════

def _inject_global_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        :root {
            --blue-dark:   #1B4F72;
            --blue-mid:    #2980B9;
            --teal:        #1ABC9C;
            --teal-light:  #A9DFBF;
            --orange:      #F39C12;
            --red:         #E74C3C;
            --green:       #27AE60;
            --grey-light:  #F8FAFC;
            --grey-mid:    #E0E8F0;
            --grey-text:   #7F8C8D;
            --text-dark:   #2C3E50;
            --white:       #FFFFFF;
        }

        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif !important;
            color: var(--text-dark);
        }

        #MainMenu  { visibility: hidden; }
        footer     { visibility: hidden; }
        header     { visibility: hidden; }

        .block-container {
            padding-top:    1.5rem !important;
            padding-bottom: 2rem   !important;
            max-width:      1400px !important;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #1B4F72 0%, #154360 100%);
            border-right: 1px solid #1ABC9C;
        }
        [data-testid="stSidebar"] * { color: #ECF0F1 !important; }
        [data-testid="stSidebar"] .stButton > button {
            background:    rgba(26,188,156,0.15) !important;
            border:        1px solid #1ABC9C     !important;
            color:         #1ABC9C               !important;
            font-weight:   600                   !important;
            border-radius: 8px                   !important;
            transition:    all 0.2s              !important;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: #1ABC9C !important;
            color:      #FFFFFF !important;
        }
        [data-testid="stSidebar"] hr {
            border-color: rgba(26,188,156,0.3) !important;
        }

        [data-testid="metric-container"] {
            background:    var(--grey-light)       !important;
            border:        1px solid var(--grey-mid) !important;
            border-radius: 12px                    !important;
            padding:       12px 16px               !important;
            box-shadow:    0 2px 6px rgba(27,79,114,0.06) !important;
        }
        [data-testid="metric-container"] label {
            color: var(--grey-text) !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
        }
        [data-testid="metric-container"] [data-testid="stMetricValue"] {
            color: var(--blue-dark) !important;
            font-weight: 700 !important;
        }

        .stButton > button {
            border-radius: 8px !important;
            font-weight:   600 !important;
            transition:    all 0.2s !important;
        }
        .stButton > button[kind="primary"] {
            background:   var(--teal)  !important;
            border-color: var(--teal)  !important;
            color:        var(--white) !important;
        }
        .stButton > button[kind="primary"]:hover {
            background:   #17A589 !important;
            border-color: #17A589 !important;
        }

        .stDownloadButton > button {
            background:    rgba(27,79,114,0.08)    !important;
            border:        1px solid var(--blue-dark) !important;
            color:         var(--blue-dark)           !important;
            border-radius: 8px                        !important;
            font-weight:   600                        !important;
        }
        .stDownloadButton > button:hover {
            background: var(--blue-dark) !important;
            color:      var(--white)     !important;
        }

        .stTabs [data-baseweb="tab-list"] {
            background:    var(--grey-light)         !important;
            border-bottom: 2px solid var(--grey-mid) !important;
            gap:           4px                       !important;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px 8px 0 0       !important;
            font-weight:   600               !important;
            color:         var(--grey-text)  !important;
            padding:       8px 18px          !important;
        }
        .stTabs [aria-selected="true"] {
            background:   var(--blue-dark) !important;
            color:        var(--white)     !important;
            border-color: var(--blue-dark) !important;
        }

        [data-testid="stForm"] {
            background:    var(--grey-light)         !important;
            border:        1px solid var(--grey-mid) !important;
            border-radius: 12px !important;
            padding:       20px !important;
        }

        [data-testid="stExpander"] {
            background:    var(--grey-light)         !important;
            border:        1px solid var(--grey-mid) !important;
            border-radius: 10px !important;
        }
        [data-testid="stExpander"] summary {
            font-weight: 600 !important;
            color: var(--blue-dark) !important;
        }

        [data-testid="stAlert"] {
            border-radius: 10px !important;
            font-weight:   500  !important;
        }

        .stProgress > div > div {
            background:    linear-gradient(90deg, var(--teal), var(--blue-mid)) !important;
            border-radius: 10px !important;
        }

        hr { border-color: var(--grey-mid) !important; margin: 0.6rem 0 !important; }

        .channel-ibtikar {
            background: var(--blue-dark); color: var(--white);
            padding: 2px 10px; border-radius: 10px;
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.5px;
        }
        .channel-genoclab {
            background: var(--teal); color: var(--white);
            padding: 2px 10px; border-radius: 10px;
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.5px;
        }

        .status-badge {
            padding: 3px 10px; border-radius: 12px;
            font-size: 0.75rem; font-weight: 600; display: inline-block;
        }
        .status-submitted                  { background:#EBF5FB; color:#2980B9; }
        .status-validation                 { background:#EBF5FB; color:#1B4F72; }
        .status-approved                   { background:#EAFAF1; color:#27AE60; }
        .status-rejected                   { background:#FDEDEC; color:#E74C3C; }
        .status-quote-draft                { background:#FEF9E7; color:#F39C12; }
        .status-quote-sent                 { background:#FEF9E7; color:#D68910; }
        .status-quote-validated-by-client  { background:#EAFAF1; color:#27AE60; }
        .status-quote-rejected-by-client   { background:#FDEDEC; color:#E74C3C; }
        .status-invoice-generated          { background:#EBF5FB; color:#1B4F72; }
        .status-assigned                   { background:#EAF2F8; color:#1B4F72; }
        .status-analysis-in-progress       { background:#E8F8F5; color:#1ABC9C; }
        .status-analysis-finished          { background:#EAFAF1; color:#27AE60; }
        .status-report-uploaded            { background:#E8F8F5; color:#1ABC9C; }
        .status-completed                  { background:#EAFAF1; color:#1E8449; }
        .status-archived                   { background:#F2F3F4; color:#717D7E; }

        .budget-ok      { color: var(--green);  font-weight: 600; }
        .budget-warning { color: var(--orange); font-weight: 600; }
        .budget-danger  { color: var(--red);    font-weight: 700; }

        .ibtikar-section {
            border-left: 4px solid var(--blue-dark);
            padding-left: 12px; margin: 8px 0;
        }
        .genoclab-section {
            border-left: 4px solid var(--teal);
            padding-left: 12px; margin: 8px 0;
        }

        .login-card {
            background: var(--white); border: 1px solid var(--grey-mid);
            border-radius: 20px; padding: 40px 48px;
            box-shadow: 0 8px 32px rgba(27,79,114,0.12);
            max-width: 480px; margin: 0 auto;
        }

        .notif-dot {
            display: inline-block; width: 10px; height: 10px;
            background: var(--red); border-radius: 50%;
            margin-left: 6px; vertical-align: middle;
        }

        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: var(--grey-light); }
        ::-webkit-scrollbar-thumb { background: var(--blue-dark); border-radius: 3px; }

        @media (max-width: 768px) {
            .block-container { padding: 1rem 0.5rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE BOOTSTRAP
# ══════════════════════════════════════════════════════════════════════════════

def _init_session() -> None:
    defaults = {
        "authenticated":            False,
        "user":                     None,
        "user_id":                  None,
        "login_attempts":           0,
        "login_error":              "",
        "last_activity":            datetime.utcnow().isoformat(),
        "notifications_checked_at": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _update_activity() -> None:
    st.session_state["last_activity"] = datetime.utcnow().isoformat()


def _check_session_timeout() -> bool:
    """Returns True and reruns if session has timed out."""
    if not st.session_state.get("authenticated"):
        return False
    last = st.session_state.get("last_activity")
    if not last:
        return False
    try:
        elapsed = (datetime.utcnow() - datetime.fromisoformat(last)).total_seconds()
        timeout = getattr(config, "SESSION_TIMEOUT_SECONDS",
                          config.SESSION_TIMEOUT_MINUTES * 60)
        if elapsed > timeout:
            for key in ["authenticated", "user", "user_id",
                        "last_activity", "_home_rendered"]:
                st.session_state.pop(key, None)
            st.session_state["_logout_message"] = (
                "⏱️ Session expirée. Veuillez vous reconnecter."
            )
            st.rerun()
            return True
    except Exception:
        pass
    return False


def _logout(timeout: bool = False) -> None:
    if timeout:
        st.warning(
            f"⏱️ Session expirée après "
            f"{config.SESSION_TIMEOUT_MINUTES // 60}h d'inactivité."
        )
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION  ← FIX: replaced hashlib.sha256 with werkzeug
# ══════════════════════════════════════════════════════════════════════════════

def _hash_password(pw: str) -> str:
    """Hashes a password using Werkzeug (scrypt on Python 3.12)."""
    return generate_password_hash(pw)


def _verify_password(plain: str, stored_hash: str) -> bool:
    """
    Verifies a plain password against a stored hash.
    Supports Werkzeug hashes (scrypt/pbkdf2) AND legacy SHA-256 hex hashes.
    """
    if not plain or not stored_hash:
        return False
    # Try Werkzeug first (new hashes)
    try:
        if check_password_hash(stored_hash, plain):
            return True
    except Exception:
        pass
    # Fallback: legacy SHA-256 hex (unmigrated accounts)
    try:
        import hashlib
        if hashlib.sha256(plain.encode("utf-8")).hexdigest() == stored_hash:
            return True
    except Exception:
        pass
    return False


def _render_login() -> None:
    """Renders the full-page login form."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f"""
            <div class="login-card">
                <div style="text-align:center; margin-bottom:24px;">
                    <div style="font-size:3.5rem;">🔬</div>
                    <div style="font-size:1.5rem; font-weight:800;
                                color:#1B4F72; letter-spacing:1px;">
                        {config.PLATFORM_NAME}
                    </div>
                    <div style="font-size:0.82rem; color:#7F8C8D; margin-top:4px;">
                        {config.PLATFORM_INSTITUTION}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("#### 🔐 Connexion à la plateforme")

        error_msg = st.session_state.get("login_error", "")
        if error_msg:
            st.error(error_msg)

        attempts = st.session_state.get("login_attempts", 0)
        if attempts >= config.MAX_LOGIN_ATTEMPTS:
            st.error(
                f"🔒 Compte temporairement verrouillé après "
                f"{config.MAX_LOGIN_ATTEMPTS} tentatives échouées. "
                f"Contactez l'administrateur."
            )
            return

        remaining = config.MAX_LOGIN_ATTEMPTS - attempts
        if attempts > 0:
            st.warning(f"⚠️ {remaining} tentative(s) restante(s).")

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input(
                "👤 Identifiant",
                key         = "login_username",
                placeholder = "Votre identifiant",
            )
            password = st.text_input(
                "🔑 Mot de passe",
                type        = "password",
                key         = "login_password",
                placeholder = "••••••••",
            )
            submitted = st.form_submit_button(
                "🚀 Se connecter",
                use_container_width = True,
                type                = "primary",
            )

        if submitted:
            _process_login(username.strip(), password)

        st.divider()
        st.markdown(
            f"""
            <div style="text-align:center; font-size:0.75rem;
                        color:#7F8C8D; margin-top:8px;">
                Accès réservé au personnel autorisé et aux utilisateurs enregistrés.<br>
                Pour tout problème de connexion, contactez l'administrateur.<br><br>
                © {config.PLATFORM_YEAR} {config.PLATFORM_AUTHOR}
                &nbsp;|&nbsp; {config.PLATFORM_EMAIL}<br>
                <b>{config.PLATFORM_NAME}</b> v{config.PLATFORM_VERSION}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _process_login(username: str, password: str) -> None:
    """Validates credentials and creates session on success."""
    if not username or not password:
        st.session_state["login_error"] = "⚠️ Identifiant et mot de passe obligatoires."
        st.rerun()
        return

    user = get_user_by_username(username)

    # Unknown user
    if not user:
        st.session_state["login_attempts"] += 1
        st.session_state["login_error"] = (
            f"❌ Identifiant ou mot de passe incorrect. "
            f"({st.session_state['login_attempts']}/{config.MAX_LOGIN_ATTEMPTS})"
        )
        try:
            log_auth_event("LOGIN_FAILED", username, success=False)
        except Exception:
            pass
        st.rerun()
        return

    # Inactive account
    if not user.get("active", True):
        st.session_state["login_error"] = (
            "🔒 Ce compte est désactivé. "
            "Contactez l'administrateur de la plateforme."
        )
        try:
            log_auth_event("LOGIN_FAILED_DISABLED", username, success=False)
        except Exception:
            pass
        st.rerun()
        return

    # ── FIX: use _verify_password instead of hash comparison ─────────────────
    if not _verify_password(password, user.get("password_hash", "")):
        st.session_state["login_attempts"] += 1
        st.session_state["login_error"] = (
            f"❌ Identifiant ou mot de passe incorrect. "
            f"({st.session_state['login_attempts']}/{config.MAX_LOGIN_ATTEMPTS})"
        )
        try:
            log_auth_event("LOGIN_FAILED", username, success=False)
        except Exception:
            pass
        st.rerun()
        return

    # ── Success ───────────────────────────────────────────────────────────────
    st.session_state["authenticated"]  = True
    st.session_state["user"]           = user
    st.session_state["user_id"]        = user["id"]
    st.session_state["login_attempts"] = 0
    st.session_state["login_error"]    = ""
    st.session_state["last_activity"]  = datetime.utcnow().isoformat()

    try:
        log_auth_event("LOGIN", username, success=True)
    except Exception:
        pass

    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION BADGE
# ══════════════════════════════════════════════════════════════════════════════

def _render_notification_badge(user: dict) -> None:
    now          = datetime.utcnow()
    last_checked = st.session_state.get("notifications_checked_at")
    should_refresh = (
        last_checked is None
        or (now - datetime.fromisoformat(last_checked)).seconds > 30
    )

    if should_refresh:
        try:
            unread = get_unread_notifications_for_user(user["id"])
            st.session_state["_unread_notif_count"] = len(unread)
            st.session_state["_unread_notifs"]       = unread
            st.session_state["notifications_checked_at"] = now.isoformat()
        except Exception:
            st.session_state["_unread_notif_count"] = 0
            st.session_state["_unread_notifs"]       = []

    count = st.session_state.get("_unread_notif_count", 0)

    with st.sidebar:
        st.divider()
        if count > 0:
            st.markdown(
                f'🔔 **Notifications** '
                f'<span class="notif-dot"></span> '
                f'<span style="color:#E74C3C; font-weight:700;">'
                f'{count} non lue(s)</span>',
                unsafe_allow_html=True,
            )
            notifs = st.session_state.get("_unread_notifs", [])
            with st.expander("Voir les notifications", expanded=False):
                for n in notifs[:5]:
                    level = n.get("level", "info")
                    icon  = {"info": "ℹ️", "success": "✅",
                             "warning": "⚠️", "error": "🚫"}.get(level, "🔔")
                    st.markdown(
                        f"{icon} **{n.get('title','–')}**  \n"
                        f"_{n.get('message','')[:80]}_"
                    )
                    st.divider()
                if count > 5:
                    st.caption(f"+ {count - 5} autre(s)…")
                if st.button(
                    "✅ Tout marquer comme lu",
                    key                 = "mark_all_read",
                    use_container_width = True,
                ):
                    try:
                        mark_all_notifications_read_for_user(user["id"])
                        st.session_state["_unread_notif_count"] = 0
                        st.session_state["_unread_notifs"]       = []
                        st.session_state["notifications_checked_at"] = None
                        st.rerun()
                    except Exception:
                        pass
        else:
            st.markdown("🔔 Aucune nouvelle notification.")


# ══════════════════════════════════════════════════════════════════════════════
# ROLE-BASED DASHBOARD DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def _dispatch(user: dict) -> None:
    role = user.get("role", "")
    try:
        if role == config.ROLE_SUPER_ADMIN:
            from ui.super_admin_dashboard import render
            render()
        elif role == config.ROLE_PLATFORM_ADMIN:
            from ui.platform_admin_dashboard import render
            render()
        elif role == config.ROLE_MEMBER:
            from ui.member_dashboard import render
            render()
        elif role == config.ROLE_FINANCE:
            from ui.finance_dashboard import render
            render()
        elif role == config.ROLE_REQUESTER:
            from ui.requester_dashboard import render
            render()
        elif role == config.ROLE_CLIENT:
            from ui.client_dashboard import render
            render()
        else:
            _render_unknown_role(role)
    except Exception as e:
        _render_dashboard_error(e, role)


def _render_unknown_role(role: str) -> None:
    st.error(
        f"❌ Rôle non reconnu: `{role}`  \n"
        f"Contactez l'administrateur de la plateforme."
    )
    st.info(f"Rôles valides: {', '.join(f'`{r}`' for r in config.ALL_ROLES)}")
    if st.button("🚪 Se déconnecter", key="logout_unknown_role"):
        _logout()


def _render_dashboard_error(error: Exception, role: str) -> None:
    st.error("❌ Une erreur inattendue s'est produite lors du chargement du tableau de bord.")
    with st.expander("🔍 Détails de l'erreur (pour le support technique)"):
        st.code(
            f"Role:  {role}\n"
            f"Error: {type(error).__name__}: {error}",
            language="text",
        )
        import traceback
        st.code(traceback.format_exc(), language="python")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Recharger", key="reload_after_error",
                     use_container_width=True):
            st.rerun()
    with col2:
        if st.button("🚪 Se déconnecter", key="logout_after_error",
                     use_container_width=True):
            _logout()


# ══════════════════════════════════════════════════════════════════════════════
# FIRST-RUN SEED
# ══════════════════════════════════════════════════════════════════════════════

def _seed_default_admin() -> None:
    """Creates default super_admin if no users exist. Change password on first login."""
    from core.repository import get_all_users, save_user
    import uuid

    if get_all_users():
        return

    save_user({
        "id":              str(uuid.uuid4()),
        "username":        "admin",
        "password_hash":   generate_password_hash("plagenor2026"),  # ← FIX
        "role":            config.ROLE_SUPER_ADMIN,
        "email":           config.PLATFORM_EMAIL,
        "organization_id": None,
        "active":          True,
        "created_at":      datetime.utcnow().isoformat(),
        "created_by":      "system",
        "note":            "Compte par défaut — changer le mot de passe immédiatement.",
    })


def _seed_default_services() -> None:
    """Seeds default service catalogue if empty."""
    from core.repository import get_all_services, save_service
    import uuid

    if get_all_services():
        return

    defaults = [
        {
            "id": str(uuid.uuid4()), "name": "Séquençage Whole Genome (WGS)",
            "channel": config.CHANNEL_GENOCLAB,
            "description": "Séquençage complet du génome bactérien — Illumina",
            "base_price": 45_000.0, "code": "WGS-001", "active": True,
            "created_at": datetime.utcnow().isoformat(), "created_by": "system",
        },
        {
            "id": str(uuid.uuid4()), "name": "Identification Moléculaire (16S rRNA)",
            "channel": config.CHANNEL_GENOCLAB,
            "description": "Identification par séquençage 16S ARNr",
            "base_price": 12_000.0, "code": "ID-16S-001", "active": True,
            "created_at": datetime.utcnow().isoformat(), "created_by": "system",
        },
        {
            "id": str(uuid.uuid4()), "name": "Typage MLST",
            "channel": config.CHANNEL_GENOCLAB,
            "description": "Multi-Locus Sequence Typing bactérien",
            "base_price": 18_000.0, "code": "MLST-001", "active": True,
            "created_at": datetime.utcnow().isoformat(), "created_by": "system",
        },
        {
            "id": str(uuid.uuid4()), "name": "Analyse Résistome / ARGs",
            "channel": config.CHANNEL_GENOCLAB,
            "description": "Détection des gènes de résistance aux antibiotiques",
            "base_price": 25_000.0, "code": "RES-001", "active": True,
            "created_at": datetime.utcnow().isoformat(), "created_by": "system",
        },
        {
            "id": str(uuid.uuid4()), "name": "Analyse Génomique Comparative",
            "channel": config.CHANNEL_IBTIKAR,
            "description": "Projet de recherche — comparaison génomique multi-souches",
            "base_price": 80_000.0, "code": "IBT-GEN-001", "active": True,
            "created_at": datetime.utcnow().isoformat(), "created_by": "system",
        },
        {
            "id": str(uuid.uuid4()), "name": "Métagénomique Environnementale",
            "channel": config.CHANNEL_IBTIKAR,
            "description": "Analyse métagénomique de microbiomes environnementaux",
            "base_price": 100_000.0, "code": "IBT-META-001", "active": True,
            "created_at": datetime.utcnow().isoformat(), "created_by": "system",
        },
    ]
    for svc in defaults:
        save_service(svc)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    _inject_global_css()
    ensure_data_directory()
    _seed_default_admin()
    _seed_default_services()
    _init_session()

    if _check_session_timeout():
        return

    if not st.session_state.get("authenticated"):
        from ui.home_page import render as render_home
        render_home()
        return

    user_id = st.session_state.get("user_id")
    user    = get_user(user_id) if user_id else None

    if not user or not user.get("active", True):
        st.warning("⚠️ Votre compte a été modifié ou désactivé. Veuillez vous reconnecter.")
        _logout()
        return

    st.session_state["user"] = user
    _update_activity()
    _render_notification_badge(user)
    _dispatch(user)


if __name__ == "__main__":
    main()
