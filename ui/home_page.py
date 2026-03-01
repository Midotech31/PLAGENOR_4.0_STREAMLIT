# ui/home_page.py
# ── PLAGENOR 4.0 — Public Home / Landing Page ────────────────────────────────

from datetime import datetime, timezone

import streamlit as st
from werkzeug.security import check_password_hash   # ← FIX: replaced hashlib

import config


def render() -> None:
    """
    Public landing page shown to unauthenticated visitors.
    """

    # ── Hide sidebar ──────────────────────────────────────────────────────────
    st.markdown("""
        <style>
        [data-testid="stSidebar"] { display: none; }
        .block-container { padding-top: 1rem; }
        </style>
    """, unsafe_allow_html=True)

    # ── Hero banner ───────────────────────────────────────────────────────────
    st.markdown("""
        <div style="
            background: linear-gradient(135deg, #0B2545, #1B4F72, #1ABC9C);
            border-radius: 18px;
            padding: 48px 40px 40px 40px;
            text-align: center;
            margin-bottom: 28px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.18);
        ">
            <div style="font-size:3.2rem; margin-bottom:6px;">🔬</div>
            <div style="
                font-size: 2.4rem; font-weight: 900;
                color: #FFFFFF; letter-spacing: 2px; margin-bottom: 6px;
            ">PLAGENOR 4.0</div>
            <div style="font-size:1.05rem; color:#AED6F1;
                        font-weight:500; margin-bottom:4px;">
                Plateforme de Gestion des Demandes d'Analyses Génomiques
            </div>
            <div style="font-size:0.88rem; color:#85C1E9;">
                ESSBO — École Supérieure des Sciences Biologiques d'Oran
            </div>
        </div>
    """, unsafe_allow_html=True)

    # ── Two columns: Login + Services ─────────────────────────────────────────
    col_login, col_info = st.columns([1, 1], gap="large")

    # ── LOGIN PANEL ───────────────────────────────────────────────────────────
    with col_login:
        st.markdown("""
            <div style="
                background: rgba(27,79,114,0.12);
                border: 1px solid rgba(26,188,156,0.30);
                border-radius: 14px;
                padding: 24px 22px 8px 22px;
                margin-bottom: 8px;
            ">
                <div style="font-size:1.15rem; font-weight:700;
                            color:#1ABC9C; text-align:center;
                            margin-bottom:16px;">
                    🔐 Connexion à la plateforme
                </div>
            </div>
        """, unsafe_allow_html=True)

        if st.session_state.get("_logout_message"):
            st.info(st.session_state.pop("_logout_message"))

        if st.session_state.get("_home_login_error"):
            st.error(st.session_state.pop("_home_login_error"))

        username = st.text_input(
            "👤 Identifiant",
            placeholder = "Entrez votre identifiant",
            key         = "home_username_input",
        )
        password = st.text_input(
            "🔑 Mot de passe",
            type        = "password",
            placeholder = "••••••••",
            key         = "home_password_input",
        )

        if st.button(
            "🚀 Se connecter",
            use_container_width = True,
            type                = "primary",
            key                 = "home_login_btn",
        ):
            _process_login(username.strip(), password)

        attempts = st.session_state.get("login_attempts", 0)
        max_att  = getattr(config, "MAX_LOGIN_ATTEMPTS", 5)
        if attempts >= max_att:
            st.error("🚫 Trop de tentatives. Contactez l'administrateur.")
        elif attempts > 0:
            st.caption(f"⚠️ {max_att - attempts} tentative(s) restante(s).")

        st.markdown("""
            <div style="text-align:center; margin-top:14px;
                        font-size:0.76rem; color:#7F8C8D;">
                Accès réservé au personnel autorisé et aux utilisateurs enregistrés.<br>
                Pour tout problème de connexion, contactez l'administrateur.
            </div>
        """, unsafe_allow_html=True)

    # ── SERVICES PANEL ────────────────────────────────────────────────────────
    with col_info:
        st.markdown("#### 🧬 Services disponibles")

        services_display = [
            ("🧫", "Whole Genome Sequencing",    "Illumina MiSeq — bactéries & microorganismes"),
            ("🔬", "Extraction d'ADN génomique", "Tissus, cultures, sang — haute qualité"),
            ("⚗️",  "PCR & Amplification",        "PCR standard, nichée, quantitative"),
            ("🧪", "Séquençage Sanger",           "Vérification de clones, identification"),
            ("💊", "Lyophilisation",              "Conservation longue durée de cultures"),
            ("🔭", "Imagerie & Microscopie",      "Microscopie à épifluorescence"),
            ("📐", "Synthèse d'amorces",          "Oligonucléotides personnalisés"),
        ]

        for icon, name, desc in services_display:
            st.markdown(
                f"""<div style="
                    background: rgba(26,188,156,0.08);
                    border-left: 3px solid #1ABC9C;
                    border-radius: 8px;
                    padding: 8px 14px;
                    margin-bottom: 8px;
                ">
                    <span style="font-weight:600; color:#ECF0F1;">{icon} {name}</span><br>
                    <span style="font-size:0.78rem; color:#AED6F1;">{desc}</span>
                </div>""",
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Channels overview ──────────────────────────────────────────────────────
    st.markdown("### 📡 Deux canaux de financement")
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown("""
            <div style="
                background: linear-gradient(135deg, #1B4F72, #154360);
                border-radius: 14px; padding: 22px 20px; text-align: center;
            ">
                <div style="font-size:2rem;">🏛️</div>
                <div style="font-size:1.1rem; font-weight:800;
                            color:#FFFFFF; margin:6px 0;">IBTIKAR</div>
                <div style="font-size:0.82rem; color:#AED6F1;">
                    Financement institutionnel DGRSDT<br>
                    Réservé aux chercheurs ESSBO<br>
                    Budget annuel plafonné à
                    <b style="color:#1ABC9C;">200 000 DZD</b>
                </div>
            </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
            <div style="
                background: linear-gradient(135deg, #1A5276, #117A65);
                border-radius: 14px; padding: 22px 20px; text-align: center;
            ">
                <div style="font-size:2rem;">🏢</div>
                <div style="font-size:1.1rem; font-weight:800;
                            color:#FFFFFF; margin:6px 0;">GENOCLAB</div>
                <div style="font-size:0.82rem; color:#AED6F1;">
                    Prestations de service externes<br>
                    Ouvert aux clients institutionnels<br>
                    Facturation avec
                    <b style="color:#1ABC9C;">TVA 19%</b>
                </div>
            </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── Stats row ──────────────────────────────────────────────────────────────
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("🧬 Services",       "9+")
    s2.metric("🏛️ Canal IBTIKAR",  "Chercheurs")
    s3.metric("🏢 Canal GENOCLAB", "Clients")
    s4.metric("📍 Localisation",   "Oran, DZ")

    st.divider()

    # ── Footer ─────────────────────────────────────────────────────────────────
    st.markdown("""
        <div style="text-align:center; font-size:0.78rem; color:#566573;
                    padding:10px 0 4px 0;">
            <b>PLAGENOR 4.0</b> &nbsp;|&nbsp;
            ESSBO — Cité Emir Abdelkader, Oran, Algérie &nbsp;|&nbsp;
            contact@essbo.dz &nbsp;|&nbsp;
            © 2025–2026
        </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN LOGIC  ← FIX: replaced hashlib.sha256 with werkzeug check_password_hash
# ══════════════════════════════════════════════════════════════════════════════

def _process_login(username: str, password: str) -> None:
    """Validates credentials and sets session state on success."""
    from core.repository import get_user_by_username

    if not username or not password:
        st.session_state["_home_login_error"] = "⚠️ Identifiant et mot de passe requis."
        st.rerun()
        return

    attempts = st.session_state.get("login_attempts", 0)
    max_att  = getattr(config, "MAX_LOGIN_ATTEMPTS", 5)
    if attempts >= max_att:
        st.session_state["_home_login_error"] = "🚫 Compte verrouillé. Contactez l'administrateur."
        st.session_state.pop("_home_rendered", None)
        st.rerun()
        return

    user = get_user_by_username(username)

    if not user:
        st.session_state["login_attempts"]    = attempts + 1
        st.session_state["_home_login_error"] = (
            f"❌ Identifiant ou mot de passe incorrect. ({attempts + 1}/{max_att})"
        )
        st.session_state.pop("_home_rendered", None)
        st.rerun()
        return

    if not user.get("active", True):
        st.session_state["_home_login_error"] = (
            "🔒 Ce compte est désactivé. Contactez l'administrateur."
        )
        st.session_state.pop("_home_rendered", None)
        st.rerun()
        return

    # ── FIX: use check_password_hash — supports scrypt, pbkdf2, and SHA-256 ──
    stored = user.get("password_hash", "")
    verified = False
    try:
        verified = check_password_hash(stored, password)
    except Exception:
        pass
    if not verified:
        # Fallback for any legacy SHA-256 accounts not yet migrated
        try:
            import hashlib
            verified = (hashlib.sha256(password.encode("utf-8")).hexdigest() == stored)
        except Exception:
            pass

    if not verified:
        st.session_state["login_attempts"]    = attempts + 1
        st.session_state["_home_login_error"] = (
            f"❌ Identifiant ou mot de passe incorrect. ({attempts + 1}/{max_att})"
        )
        st.session_state.pop("_home_rendered", None)
        st.rerun()
        return

    # ── Success ───────────────────────────────────────────────────────────────
    st.session_state["authenticated"]  = True
    st.session_state["user"]           = user
    st.session_state["user_id"]        = user["id"]
    st.session_state["last_activity"]  = datetime.now(timezone.utc).isoformat()
    st.session_state["login_attempts"] = 0
    st.session_state.pop("_home_login_error", None)
    st.session_state.pop("_home_rendered",    None)

    try:
        from core.audit_engine import log_auth_event
        log_auth_event("LOGIN", username, success=True)
    except Exception:
        pass

    st.rerun()