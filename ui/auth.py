# ui/auth.py
# ── PLAGENOR 4.0 — Authentication & Session Guard ────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from typing import Optional, Union

import streamlit as st
from werkzeug.security import generate_password_hash, check_password_hash

import config
from core.repository import (
    get_user,
    get_user_by_username,
    update_user_password,
)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

MIN_PASSWORD_LENGTH = 8

_KEY_AUTH       = "authenticated"
_KEY_USER       = "user"
_KEY_USER_ID    = "user_id"
_KEY_LAST_ACT   = "last_activity"
_KEY_LOGIN_ATT  = "login_attempts"
_KEY_LOGIN_ERR  = "login_error"

_ROLE_BADGE_COLOURS = {
    config.ROLE_SUPER_ADMIN:    ("#1B4F72", "#FFFFFF"),
    config.ROLE_PLATFORM_ADMIN: ("#154360", "#FFFFFF"),
    config.ROLE_MEMBER:         ("#1ABC9C", "#FFFFFF"),
    config.ROLE_FINANCE:        ("#8E44AD", "#FFFFFF"),
    config.ROLE_REQUESTER:      ("#2980B9", "#FFFFFF"),
    config.ROLE_CLIENT:         ("#27AE60", "#FFFFFF"),
}


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION MATRIX
# ══════════════════════════════════════════════════════════════════════════════

_PERMISSIONS: dict[str, set[str]] = {
    config.ROLE_SUPER_ADMIN: {
        "view_all_requests", "create_request", "edit_request", "delete_request",
        "transition_any", "force_transition", "assign_member", "manage_users",
        "manage_members", "manage_services", "view_audit_logs", "export_data",
        "view_finance", "manage_invoices", "record_payment", "view_productivity",
        "manage_platform_config", "generate_documents", "view_reports",
        "bulk_archive", "view_notifications", "manage_notifications",
        "ibtikar_submit", "genoclab_submit", "view_budget", "approve_request",
        "reject_request", "validate_report", "upload_report",
        "view_member_dashboard", "view_client_dashboard",
        "view_requester_dashboard", "impersonate",
    },
    config.ROLE_PLATFORM_ADMIN: {
        "view_all_requests", "create_request", "edit_request", "transition_any",
        "assign_member", "manage_members", "manage_services", "view_audit_logs",
        "export_data", "view_finance", "manage_invoices", "view_productivity",
        "generate_documents", "view_reports", "bulk_archive", "view_notifications",
        "approve_request", "reject_request", "validate_report", "upload_report",
        "view_budget",
    },
    config.ROLE_MEMBER: {
        "view_assigned_requests", "upload_report", "view_productivity",
        "view_notifications", "view_reports", "accept_assignment",
        "update_analysis_status",
    },
    config.ROLE_FINANCE: {
        "view_finance", "manage_invoices", "record_payment", "export_data",
        "view_notifications", "view_all_requests",
    },
    config.ROLE_REQUESTER: {
        "ibtikar_submit", "view_own_requests", "view_notifications",
        "view_reports", "view_budget",
    },
    config.ROLE_CLIENT: {
        "genoclab_submit", "view_own_requests", "view_notifications",
        "view_reports", "validate_quote", "reject_quote", "view_invoices",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD HELPERS  ← FIX: replaced hashlib.sha256 with werkzeug
# ══════════════════════════════════════════════════════════════════════════════

def _hash_pw(pw: str) -> str:
    """Hashes a plain-text password using Werkzeug (scrypt/pbkdf2)."""
    return generate_password_hash(pw, method="pbkdf2:sha256")


def _verify_pw(plain: str, stored_hash: str) -> bool:
    """
    Verifies a plain password against a stored hash.
    Supports both Werkzeug hashes (scrypt/pbkdf2) AND legacy SHA-256 hex hashes
    so that any remaining old accounts still work after migration.
    """
    if not plain or not stored_hash:
        return False
    # Try Werkzeug first (new format)
    try:
        if check_password_hash(stored_hash, plain):
            return True
    except Exception:
        pass
    # Fallback: legacy SHA-256 hex (old accounts not yet migrated)
    try:
        import hashlib
        if hashlib.sha256(plain.encode("utf-8")).hexdigest() == stored_hash:
            return True
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════════════════════════
# SESSION READERS
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user() -> Optional[dict]:
    if not st.session_state.get(_KEY_AUTH):
        return None
    return st.session_state.get(_KEY_USER)


def get_current_user_id() -> Optional[str]:
    user = get_current_user()
    return user.get("id") if user else None


def get_current_role() -> Optional[str]:
    user = get_current_user()
    return user.get("role") if user else None


def is_authenticated() -> bool:
    return bool(st.session_state.get(_KEY_AUTH))


# ══════════════════════════════════════════════════════════════════════════════
# ROLE CHECK HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def is_super_admin(user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    return bool(u and u.get("role") == config.ROLE_SUPER_ADMIN)


def is_platform_admin(user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    return bool(u and u.get("role") in {
        config.ROLE_SUPER_ADMIN, config.ROLE_PLATFORM_ADMIN,
    })


def is_member(user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    return bool(u and u.get("role") == config.ROLE_MEMBER)


def is_finance(user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    return bool(u and u.get("role") == config.ROLE_FINANCE)


def is_requester(user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    return bool(u and u.get("role") == config.ROLE_REQUESTER)


def is_client(user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    return bool(u and u.get("role") == config.ROLE_CLIENT)


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION CHECK
# ══════════════════════════════════════════════════════════════════════════════

def has_permission(action: str, user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    if not u:
        return False
    role = u.get("role", "")
    return action in _PERMISSIONS.get(role, set())


def require_permission(
    action: str,
    user:   Optional[dict] = None,
    stop:   bool = True,
) -> bool:
    if has_permission(action, user):
        return True
    _render_access_denied(f"Action `{action}` non autorisée pour votre rôle.")
    if stop:
        st.stop()
    return False


# ══════════════════════════════════════════════════════════════════════════════
# REQUIRE ROLE GATE
# ══════════════════════════════════════════════════════════════════════════════

def require_role(
    allowed_roles: Union[str, list[str]],
    stop:          bool = True,
) -> Optional[dict]:
    """
    Verifies the current session user has one of the allowed roles.
    Returns the user dict if authorised, None otherwise.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]

    if not is_authenticated():
        st.error("🔐 Session expirée. Veuillez vous reconnecter.")
        if stop:
            st.stop()
        return None

    user = get_current_user()

    # Re-check account active status
    user_id   = user.get("id", "")
    live_user = get_user(user_id) if user_id else None
    if live_user and not live_user.get("active", True):
        _force_logout_disabled()
        return None

    role = user.get("role", "")
    if role not in allowed_roles:
        _render_access_denied(
            f"Rôle requis: "
            f"{', '.join(config.ROLE_LABELS.get(r, r) for r in allowed_roles)}  \n"
            f"Votre rôle: **{config.ROLE_LABELS.get(role, role)}**"
        )
        if stop:
            st.stop()
        return None

    st.session_state[_KEY_LAST_ACT] = datetime.utcnow().isoformat()
    return user


def require_roles(*allowed_roles: str) -> dict:
    """
    Variadic alias for require_role().
    Usage: user = require_roles(config.ROLE_PLATFORM_ADMIN, config.ROLE_SUPER_ADMIN)
    """
    result = require_role(list(allowed_roles), stop=True)
    return result or {}


def require_any_staff(stop: bool = True) -> Optional[dict]:
    return require_role(
        [
            config.ROLE_SUPER_ADMIN,
            config.ROLE_PLATFORM_ADMIN,
            config.ROLE_MEMBER,
            config.ROLE_FINANCE,
        ],
        stop=stop,
    )


# ══════════════════════════════════════════════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════════════════════════════════════════════

def logout(actor: Optional[dict] = None, message: str = "") -> None:
    u = actor or get_current_user()
    if u:
        try:
            from core.audit_engine import log_auth_event
            log_auth_event("LOGOUT", u.get("username", "–"), success=True)
        except Exception:
            pass

    flash = message.strip()
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    if flash:
        st.session_state["_logout_message"] = flash
    st.rerun()


def _force_logout_disabled() -> None:
    try:
        from core.audit_engine import log_auth_event
        user = get_current_user()
        if user:
            log_auth_event(
                "SESSION_TERMINATED_ACCOUNT_DISABLED",
                user.get("username", "–"),
                success=False,
            )
    except Exception:
        pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.error(
        "🔒 Votre compte a été désactivé par un administrateur. "
        "Contactez le responsable de la plateforme."
    )
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD CHANGE FORM
# ══════════════════════════════════════════════════════════════════════════════

def render_change_password_form(
    user:        dict,
    form_key:    str  = "change_pw_form",
    require_old: bool = True,
) -> bool:
    changed = False

    with st.form(form_key):
        st.markdown("#### 🔑 Changer le mot de passe")

        if require_old:
            old_pw = st.text_input(
                "Mot de passe actuel",
                type        = "password",
                placeholder = "••••••••",
            )
        else:
            old_pw = None
            st.info(f"ℹ️ Réinitialisation pour **{user.get('username', '–')}**.")

        new_pw = st.text_input(
            "Nouveau mot de passe",
            type        = "password",
            placeholder = f"Minimum {MIN_PASSWORD_LENGTH} caractères",
        )
        confirm_pw = st.text_input(
            "Confirmer le nouveau mot de passe",
            type        = "password",
            placeholder = "••••••••",
        )

        submitted = st.form_submit_button(
            "💾 Enregistrer",
            use_container_width = True,
            type                = "primary",
        )

    if submitted:
        error = _validate_password_change(
            user        = user,
            old_pw      = old_pw,
            new_pw      = new_pw,
            confirm_pw  = confirm_pw,
            require_old = require_old,
        )
        if error:
            st.error(error)
        else:
            new_hash = _hash_pw(new_pw)
            try:
                update_user_password(user["id"], new_hash)
                current = get_current_user()
                if current and current.get("id") == user["id"]:
                    st.session_state[_KEY_USER]["password_hash"] = new_hash
                st.success("✅ Mot de passe mis à jour avec succès.")
                try:
                    from core.audit_engine import log_action
                    log_action(
                        action      = "PASSWORD_CHANGED",
                        entity_type = "USER",
                        entity_id   = user["id"],
                        actor       = get_current_user() or user,
                        details     = f"Utilisateur: {user.get('username','–')}",
                    )
                except Exception:
                    pass
                changed = True
            except Exception as e:
                st.error(f"❌ Erreur lors de la mise à jour: {e}")

    return changed


def _validate_password_change(
    user:        dict,
    old_pw:      Optional[str],
    new_pw:      str,
    confirm_pw:  str,
    require_old: bool,
) -> Optional[str]:
    # ── FIX: use _verify_pw instead of _hash_pw comparison ───────────────────
    if require_old:
        if not old_pw or not old_pw.strip():
            return "⚠️ Le mot de passe actuel est requis."
        if not _verify_pw(old_pw, user.get("password_hash", "")):
            return "❌ Mot de passe actuel incorrect."

    if not new_pw or not new_pw.strip():
        return "⚠️ Le nouveau mot de passe ne peut pas être vide."

    if len(new_pw) < MIN_PASSWORD_LENGTH:
        return (
            f"⚠️ Le mot de passe doit contenir au moins "
            f"{MIN_PASSWORD_LENGTH} caractères."
        )

    if new_pw != confirm_pw:
        return "❌ Les mots de passe ne correspondent pas."

    if require_old and old_pw and new_pw == old_pw:
        return "⚠️ Le nouveau mot de passe doit être différent de l'ancien."

    if not any(c.isdigit() for c in new_pw):
        return "⚠️ Le mot de passe doit contenir au moins un chiffre."

    return None


# ══════════════════════════════════════════════════════════════════════════════
# USER PROFILE CARD
# ══════════════════════════════════════════════════════════════════════════════

def render_user_profile_card(
    user:         dict,
    show_logout:  bool = True,
    show_pw_link: bool = True,
) -> None:
    role  = user.get("role", "")
    label = config.ROLE_LABELS.get(role, role)
    bg, fg = _ROLE_BADGE_COLOURS.get(role, ("#7F8C8D", "#FFFFFF"))

    username = user.get("username", "–")
    email    = user.get("email",    "")

    avatar = {
        config.ROLE_SUPER_ADMIN:    "⚙️",
        config.ROLE_PLATFORM_ADMIN: "🛠️",
        config.ROLE_MEMBER:         "🔬",
        config.ROLE_FINANCE:        "💼",
        config.ROLE_REQUESTER:      "📋",
        config.ROLE_CLIENT:         "🏢",
    }.get(role, "👤")

    st.sidebar.markdown(
        f"""
        <div style="
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 10px;
        ">
            <div style="font-size:1.8rem; text-align:center;">{avatar}</div>
            <div style="font-weight:700; font-size:0.95rem; text-align:center;
                        color:#ECF0F1; margin-top:4px;">{username}</div>
            <div style="text-align:center; margin:6px 0;">
                <span style="background:{bg}; color:{fg}; padding:2px 10px;
                             border-radius:10px; font-size:0.72rem;
                             font-weight:700;">{label}</span>
            </div>
            {"<div style='font-size:0.72rem;color:#BDC3C7;text-align:center;'>"
             + email + "</div>" if email else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if show_pw_link:
        with st.sidebar.expander("🔑 Changer le mot de passe", expanded=False):
            render_change_password_form(
                user     = user,
                form_key = f"sidebar_pw_{user.get('id','x')[:8]}",
            )

    if show_logout:
        if st.sidebar.button(
            "🚪 Se déconnecter",
            key                 = "sidebar_logout_btn",
            use_container_width = True,
        ):
            logout(actor=user)


# ══════════════════════════════════════════════════════════════════════════════
# ACCESS DENIED
# ══════════════════════════════════════════════════════════════════════════════

def _render_access_denied(reason: str = "") -> None:
    st.error(
        "🚫 **Accès refusé**  \n"
        + (reason if reason else "Vous n'avez pas les droits nécessaires.")
    )
    st.markdown(
        """
        <div style="background:#FDEDEC; border:1px solid #E74C3C;
                    border-radius:10px; padding:16px 20px; margin-top:8px;">
            <p style="color:#922B21; margin:0;">
                Contactez l'administrateur :
                <a href="mailto:{email}" style="color:#922B21;"><b>{email}</b></a>
            </p>
        </div>
        """.format(email=getattr(config, "PLATFORM_EMAIL", "admin@essbo.dz")),
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT PAGE ACCESS
# ══════════════════════════════════════════════════════════════════════════════

def audit_page_access(page_name: str, user: Optional[dict] = None) -> None:
    u = user or get_current_user()
    if not u:
        return
    try:
        from core.audit_engine import log_action
        log_action(
            action      = "PAGE_ACCESS",
            entity_type = "UI",
            entity_id   = page_name,
            actor       = u,
            details     = f"Page: {page_name}",
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CHANNEL ACCESS GUARD
# ══════════════════════════════════════════════════════════════════════════════

def can_access_channel(channel: str, user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    if not u:
        return False
    role = u.get("role", "")
    if channel == config.CHANNEL_IBTIKAR:
        return role in {
            config.ROLE_SUPER_ADMIN, config.ROLE_PLATFORM_ADMIN,
            config.ROLE_MEMBER, config.ROLE_REQUESTER,
        }
    if channel == config.CHANNEL_GENOCLAB:
        return role in {
            config.ROLE_SUPER_ADMIN, config.ROLE_PLATFORM_ADMIN,
            config.ROLE_MEMBER, config.ROLE_FINANCE, config.ROLE_CLIENT,
        }
    return False


def require_channel_access(
    channel: str,
    user:    Optional[dict] = None,
    stop:    bool = True,
) -> bool:
    if can_access_channel(channel, user):
        return True
    _render_access_denied(f"Votre rôle n'a pas accès au canal **{channel}**.")
    if stop:
        st.stop()
    return False


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST OWNERSHIP GUARD
# ══════════════════════════════════════════════════════════════════════════════

def can_view_request(request: dict, user: Optional[dict] = None) -> bool:
    u = user or get_current_user()
    if not u:
        return False
    role = u.get("role", "")
    uid  = u.get("id",   "")

    if role in {config.ROLE_SUPER_ADMIN, config.ROLE_PLATFORM_ADMIN}:
        return True
    if role == config.ROLE_MEMBER:
        return (
            request.get("assigned_member_id") == uid or
            request.get("assigned_member_user_id") == uid
        )
    if role == config.ROLE_FINANCE:
        return request.get("channel") == config.CHANNEL_GENOCLAB
    if role in {config.ROLE_REQUESTER, config.ROLE_CLIENT}:
        return request.get("submitted_by_user_id") == uid
    return False


def require_request_access(
    request: dict,
    user:    Optional[dict] = None,
    stop:    bool = True,
) -> bool:
    if can_view_request(request, user):
        return True
    _render_access_denied("Vous n'avez pas accès à cette demande.")
    if stop:
        st.stop()
    return False
