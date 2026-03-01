# ui/member_dashboard.py
# ── PLAGENOR 4.0 — Member Dashboard ──────────────────────────────────────────
# Serves  : ROLE_MEMBER (analysts / lab technicians)
# Scope   : Only their own assigned requests, tasks, appointments, profile.
#           Members CANNOT see other members' data or admin panels.

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
    get_member_by_user_id,
    save_request,
    get_request,
)
from core.workflow_engine   import transition
from core.task_engine       import add_task, complete_task, get_tasks_for_request
from core.productivity_engine import recalculate_member
from core.exceptions        import PlagenorError


# ── Constants ─────────────────────────────────────────────────────────────────
CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB

PRODUCTIVITY_LABEL_MAP = {
    "EXCELLENT": ("🟢", "Excellent",   "success"),
    "GOOD":      ("🔵", "Bien",        "info"),
    "NORMAL":    ("🟡", "Normal",      "warning"),
    "LOW":       ("🔴", "Insuffisant", "error"),
}

ANALYSIS_STATES = {
    "ANALYSIS_IN_PROGRESS",
    "ANALYSIS_FINISHED",
    "REPORT_UPLOADED",
}

MEMBER_VISIBLE_STATES = {
    "ASSIGNED",
    "ANALYSIS_IN_PROGRESS",
    "ANALYSIS_FINISHED",
    "REPORT_UPLOADED",
    "COMPLETED",
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
    """Transition + rerun. Never raises."""
    try:
        transition(request_id=req["id"], to_state=to, actor=actor, notes=notes)
        st.success(f"✅ Demande avancée → `{to}`")
        st.cache_data.clear()
        st.rerun()
    except PlagenorError as e:
        st.error(f"❌ {e}")


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=10)
def _load_active_requests() -> list:
    return get_all_active_requests()


@st.cache_data(ttl=10)
def _load_archived_requests() -> list:
    return get_all_archived_requests()


def _get_member_profile(user: dict) -> Optional[dict]:
    """Returns the Member record linked to this user account. None if not found."""
    try:
        return get_member_by_user_id(user["id"])
    except Exception:
        return None


def _my_requests(member: dict, requests: list) -> list:
    """Filter requests assigned to this member only."""
    mid = member.get("id", "")
    return [
        r for r in requests
        if r.get("assigned_member_id") == mid
        and r.get("status") in MEMBER_VISIBLE_STATES
    ]


def _request_selector(requests: list, key: str) -> Optional[dict]:
    if not requests:
        return None
    opts = {
        f"[{r.get('channel','?')}] {r['id'][:8]} — "
        f"{resolve_service_name(r.get('service_id',''))} "
        f"({r.get('status','')})" : r
        for r in requests
    }
    sel = st.selectbox("Sélectionner une demande", list(opts.keys()), key=key)
    return opts[sel]


# ── Tab: My Requests ──────────────────────────────────────────────────────────
def _tab_my_requests(member: dict, actor: dict) -> None:
    st.markdown("## 📋 Mes demandes assignées")

    active   = _load_active_requests()
    archived = _load_archived_requests()
    all_reqs = active + archived

    mine = _my_requests(member, all_reqs)

    if not mine:
        render_empty_state(
            "📭", "Aucune demande assignée",
            "Vous n'avez pas encore de demandes assignées.",
        )
        return

    # Filter controls
    col1, col2 = st.columns(2)
    with col1:
        ch_filter = st.selectbox(
            "Canal", ["Tous", CHANNEL_IBTIKAR, CHANNEL_GENOCLAB],
            key="mr_ch"
        )
    with col2:
        statuses = sorted({r.get("status", "") for r in mine})
        st_filter = st.selectbox("Statut", ["Tous"] + statuses, key="mr_st")

    filtered = mine
    if ch_filter != "Tous":
        filtered = [r for r in filtered if r.get("channel") == ch_filter]
    if st_filter != "Tous":
        filtered = [r for r in filtered if r.get("status") == st_filter]

    filtered = sorted(filtered, key=lambda r: r.get("created_at", ""), reverse=True)

    st.caption(f"**{len(filtered)}** demande(s) affichée(s)")
    st.divider()

    for req in filtered:
        render_request_card(req)
        days = _days_since(req.get("created_at", ""))
        age_icon = "🔴" if days > 7 else ("🟡" if days > 3 else "🟢")
        st.caption(
            f"{age_icon} Assignée il y a: **{days} jour(s)** | "
            f"Canal: `{req.get('channel', '–')}` | "
            f"Service: {resolve_service_name(req.get('service_id', ''))}"
        )
        st.divider()


# ── Tab: Tasks ────────────────────────────────────────────────────────────────
def _tab_tasks(member: dict, actor: dict) -> None:
    st.markdown("## 📝 Mes tâches")

    active = _load_active_requests()
    mine   = _my_requests(member, active)

    # Flatten all tasks assigned to this member across all their requests
    my_tasks: list = []
    for req in mine:
        tasks = get_tasks_for_request(req["id"])
        for task in tasks:
            if task.get("assigned_to") == member.get("id"):
                my_tasks.append({"req": req, "task": task})

    # Summary counters
    total     = len(my_tasks)
    done      = sum(1 for t in my_tasks if t["task"].get("done"))
    pending   = total - done

    col1, col2, col3 = st.columns(3)
    col1.metric("📋 Total tâches",    total)
    col2.metric("✅ Terminées",        done)
    col3.metric("🔲 En attente",       pending)

    st.divider()

    if not my_tasks:
        render_empty_state(
            "📝", "Aucune tâche assignée",
            "Vos tâches apparaîtront ici une fois assignées par l'admin.",
        )
        return

    # Group by request
    from collections import defaultdict
    grouped: dict = defaultdict(list)
    for item in my_tasks:
        grouped[item["req"]["id"]].append(item)

    for req_id, items in grouped.items():
        req      = items[0]["req"]
        svc_name = resolve_service_name(req.get("service_id", ""))
        with st.expander(
            f"📂 Demande `{req_id[:8]}` — {svc_name} "
            f"({req.get('status', '–')})",
            expanded=True,
        ):
            for item in items:
                task = item["task"]
                tid  = task.get("id", "")
                done = task.get("done", False)

                col_icon, col_title, col_action = st.columns([1, 6, 3])
                with col_icon:
                    st.markdown("✅" if done else "🔲")
                with col_title:
                    title = task.get("title", "–")
                    if done:
                        st.markdown(f"~~{title}~~")
                        completed_at = task.get("completed_at", "")
                        if completed_at:
                            st.caption(f"Terminée: {completed_at[:10]}")
                    else:
                        st.markdown(f"**{title}**")
                with col_action:
                    if not done:
                        if st.button(
                            "Marquer terminée",
                            key  = f"done_task_{tid}",
                            type = "primary",
                        ):
                            try:
                                complete_task(tid, actor)
                                st.success("✅ Tâche marquée comme terminée.")
                                st.cache_data.clear()
                                st.rerun()
                            except PlagenorError as e:
                                _action_err(e)
                    else:
                        st.caption("Terminée")


# ── Tab: Analysis ─────────────────────────────────────────────────────────────
def _tab_analysis(member: dict, actor: dict) -> None:
    st.markdown("## 🔬 Suivi et mise à jour des analyses")

    active        = _load_active_requests()
    mine          = _my_requests(member, active)
    in_analysis   = [
        r for r in mine
        if r.get("status") in {"ASSIGNED", "ANALYSIS_IN_PROGRESS"}
    ]

    if not in_analysis:
        render_empty_state(
            "🔬", "Aucune analyse en cours",
            "Vos analyses actives apparaîtront ici.",
        )
        return

    req = _request_selector(in_analysis, "analysis_sel")
    if not req:
        return

    render_request_card(req)
    render_workflow_progress(req.get("channel", ""), req.get("status", ""))

    status = req.get("status", "")
    st.divider()

    # Progress checklist
    st.markdown("### 📋 Checklist d'analyse")
    checklist_key = f"checklist_{req['id']}"
    checks = req.get("analysis_checklist", {})

    items = [
        ("sample_received",   "📦 Échantillons reçus et étiquetés"),
        ("prep_done",         "🧪 Préparation des librairies terminée"),
        ("run_started",       "▶️ Run/analyse démarré(e)"),
        ("qc_passed",         "✅ Contrôle qualité validé"),
        ("data_exported",     "💾 Données exportées"),
        ("report_drafted",    "📄 Rapport rédigé"),
    ]

    updated_checks = dict(checks)
    for field, label in items:
        current_val = checks.get(field, False)
        new_val = st.checkbox(label, value=current_val, key=f"{checklist_key}_{field}")
        updated_checks[field] = new_val

    if updated_checks != checks:
        if st.button("💾 Enregistrer la checklist", key=f"save_check_{req['id']}"):
            r = get_request(req["id"])
            if r:
                r["analysis_checklist"] = updated_checks
                save_request(r)
                st.success("✅ Checklist enregistrée.")
                st.cache_data.clear()
                st.rerun()

    st.divider()

    # Add a note
    st.markdown("### 📝 Ajouter une note d'analyse")
    with st.form(f"note_form_{req['id']}"):
        note_text = st.text_area(
            "Note",
            height      = 80,
            placeholder = "Ex: Rendement d'extraction correct, run qualité OK.",
        )
        if st.form_submit_button("💾 Enregistrer la note", use_container_width=True):
            r = get_request(req["id"])
            if r:
                notes_list = r.get("analysis_notes", [])
                notes_list.append({
                    "text":      note_text,
                    "author_id": actor.get("id", ""),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                r["analysis_notes"] = notes_list
                save_request(r)
                st.success("✅ Note enregistrée.")
                st.cache_data.clear()
                st.rerun()

    # Display existing notes
    existing_notes = req.get("analysis_notes", [])
    if existing_notes:
        st.markdown("**Notes précédentes:**")
        for note in reversed(existing_notes[-5:]):
            st.markdown(
                f"> {note.get('text', '–')}  \n"
                f"> _{note.get('timestamp', '')[:16]}_"
            )

    st.divider()

    # Advance to ANALYSIS_IN_PROGRESS
    if status == "ASSIGNED":
        st.markdown("### ▶️ Démarrer l'analyse")
        if confirm_action(
            key     = f"start_analysis_{req['id']}",
            label   = "▶️ Démarrer → ANALYSIS_IN_PROGRESS",
            message = f"Confirmer le démarrage de l'analyse `{req['id'][:8]}` ?",
        ):
            _advance(req, "ANALYSIS_IN_PROGRESS", actor)

    # Advance to ANALYSIS_FINISHED
    elif status == "ANALYSIS_IN_PROGRESS":
        all_done = all(updated_checks.get(f, False) for f, _ in items)
        if not all_done:
            st.warning(
                "⚠️ Certaines étapes de la checklist ne sont pas encore "
                "cochées. Vous pouvez quand même terminer si vous êtes sûr."
            )
        completion_note = st.text_area(
            "Note de fin d'analyse *",
            key         = f"fin_note_{req['id']}",
            height      = 80,
            placeholder = "Ex: Séquençage WGS terminé, 50x coverage atteint.",
        )
        if confirm_action(
            key     = f"finish_analysis_{req['id']}",
            label   = "✅ Marquer analyse terminée → ANALYSIS_FINISHED",
            message = f"Confirmer la fin de l'analyse `{req['id'][:8]}` ?",
        ):
            if not completion_note.strip():
                st.warning("⚠️ La note de fin d'analyse est obligatoire.")
            else:
                _advance(req, "ANALYSIS_FINISHED", actor, notes=completion_note)


# ── Tab: Appointments ─────────────────────────────────────────────────────────
def _tab_appointments(member: dict, actor: dict) -> None:
    st.markdown("## 📅 Mes rendez-vous et réceptions")

    active = _load_active_requests()
    mine   = _my_requests(member, active)

    # Requests with an appointment scheduled
    with_appt   = [r for r in mine if r.get("appointment")]
    without_appt = [
        r for r in mine
        if not r.get("appointment") and r.get("status") == "ASSIGNED"
    ]

    if not mine:
        render_empty_state(
            "📅", "Aucun rendez-vous",
            "Vos rendez-vous apparaîtront ici une fois planifiés.",
        )
        return

    # Upcoming appointments
    if with_appt:
        st.markdown("### 📅 Rendez-vous planifiés")
        for req in sorted(
            with_appt,
            key=lambda r: r.get("appointment", {}).get("date", ""),
        ):
            appt        = req.get("appointment", {})
            svc_name    = resolve_service_name(req.get("service_id", ""))
            form_data   = req.get("form_data", {})
            requester   = form_data.get("requester", {})

            with st.container():
                col1, col2 = st.columns([3, 2])
                with col1:
                    st.markdown(
                        f"**📂 {svc_name}** — `{req['id'][:8]}`  \n"
                        f"👤 {requester.get('full_name', '–')} "
                        f"({requester.get('institution', '–')})  \n"
                        f"📞 {requester.get('phone', '–')}"
                    )
                with col2:
                    st.markdown(
                        f"📅 **{appt.get('date', '–')}**  \n"
                        f"⏰ {appt.get('time', '–')}"
                    )
                    st.caption(f"Note: {appt.get('note', '–')}")
                    status_badge = render_status_badge(req.get("status", ""))

                st.divider()

    # Pending reception (ASSIGNED, no appointment yet)
    if without_appt:
        st.markdown("### ⏳ En attente de planification")
        for req in without_appt:
            svc_name = resolve_service_name(req.get("service_id", ""))
            st.info(
                f"📂 `{req['id'][:8]}` — {svc_name}  \n"
                f"⚠️ Aucun rendez-vous planifié. "
                f"Contactez l'admin pour fixer une date."
            )

    # Confirm reception
    assigned = [r for r in mine if r.get("status") == "ASSIGNED"]
    if assigned:
        st.divider()
        st.markdown("### ✅ Confirmer la réception des échantillons")
        st.caption(
            "Si vous avez reçu les échantillons et êtes prêt à démarrer, "
            "confirmez la réception ici."
        )
        rec_req = _request_selector(assigned, "reception_sel")
        if rec_req:
            reception_note = st.text_input(
                "Note de réception",
                key         = f"rec_note_{rec_req['id']}",
                placeholder = "Ex: 6 souches reçues, conditions correctes.",
            )
            if confirm_action(
                key     = f"receive_{rec_req['id']}",
                label   = "✅ Réception confirmée → ANALYSIS_IN_PROGRESS",
                message = (
                    f"Confirmer la réception pour `{rec_req['id'][:8]}` ?  \n"
                    f"L'analyse démarrera immédiatement."
                ),
            ):
                _advance(rec_req, "ANALYSIS_IN_PROGRESS", actor, notes=reception_note)


# ── Tab: My Profile ───────────────────────────────────────────────────────────
def _tab_profile(member: dict, actor: dict) -> None:
    st.markdown("## 👤 Mon profil & productivité")

    if not member:
        st.error(
            "❌ Profil membre introuvable. "
            "Contactez un administrateur pour lier votre compte."
        )
        return

    # Profile card
    score         = float(member.get("productivity_score", 50))
    label         = member.get("productivity_label", "NORMAL")
    emoji, label_fr, _ = PRODUCTIVITY_LABEL_MAP.get(label, ("📊", label, "info"))
    available     = member.get("available", True)
    avail_icon    = "🟢 Disponible" if available else "🔴 Indisponible"
    current_load  = member.get("current_load", 0)
    max_load      = member.get("max_load", 5)
    skills        = member.get("skills", {})

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(
            f"### {emoji} {member.get('name', '–')}\n"
            f"**Statut:** {avail_icon}  \n"
            f"**Charge:** `{current_load} / {max_load}` demandes  \n"
            f"**Niveau de productivité:** `{label_fr}`"
        )
    with col2:
        st.metric("🏆 Score de productivité", f"{score:.1f} / 100")
        st.progress(score / 100)

    st.divider()

    # Skills
    if skills:
        st.markdown("### 🎯 Mes compétences")
        st.caption("Scores définis par l'administrateur.")
        from core.repository import get_all_services
        services = {s["id"]: s["name"] for s in get_all_services()}
        for svc_id, skill_score in sorted(
            skills.items(), key=lambda x: x[1], reverse=True
        ):
            svc_name = services.get(svc_id, svc_id[:8])
            st.markdown(f"**{svc_name}:** `{skill_score:.0f} / 100`")
            st.progress(float(skill_score) / 100)
    else:
        st.info("Aucune compétence enregistrée. Contactez l'admin.")

    st.divider()

    # Productivity history
    st.markdown("### 📊 Historique de productivité")
    history = member.get("productivity_history", [])
    if history:
        for entry in reversed(history[-6:]):
            month  = entry.get("month", "–")
            yr     = entry.get("year", "–")
            sc     = float(entry.get("score", 0))
            lb     = entry.get("label", "NORMAL")
            em, _, _ = PRODUCTIVITY_LABEL_MAP.get(lb, ("📊", lb, "info"))
            st.markdown(f"{em} **{month}/{yr}** — Score: `{sc:.1f}` — Niveau: `{lb}`")
            st.progress(sc / 100)
    else:
        st.info("Aucun historique disponible.")

    st.divider()

    # Recalculate own score
    st.markdown("### 🔄 Recalculer mon score")
    st.caption(
        "Demandez le recalcul de votre score basé sur vos performances récentes."
    )
    if st.button(
        "🔄 Recalculer mon score de productivité",
        key                 = "recalc_self_btn",
        use_container_width = True,
    ):
        with st.spinner("Recalcul en cours..."):
            try:
                result = recalculate_member(member["id"], user=actor)
                new_score = float(result.get("score", 0))
                new_label = result.get("label", "–")
                em, _, _  = PRODUCTIVITY_LABEL_MAP.get(new_label, ("📊", new_label, "info"))
                st.success(
                    f"{em} Nouveau score: **{new_score:.1f} / 100** — "
                    f"Niveau: **{new_label}**"
                )
                st.cache_data.clear()
                st.rerun()
            except PlagenorError as e:
                _action_err(e)


# ── Tab: History ──────────────────────────────────────────────────────────────
def _tab_history(member: dict, actor: dict) -> None:
    st.markdown("## 📦 Historique de mes demandes")

    all_reqs  = _load_active_requests() + _load_archived_requests()
    mid       = member.get("id", "")
    completed = [
        r for r in all_reqs
        if r.get("assigned_member_id") == mid
        and r.get("status") in {"COMPLETED", "REPORT_UPLOADED"}
    ]

    if not completed:
        render_empty_state(
            "📦", "Aucun historique",
            "Vos demandes terminées apparaîtront ici.",
        )
        return

    st.caption(f"**{len(completed)}** demande(s) terminée(s)")
    st.divider()

    for req in sorted(
        completed,
        key     = lambda r: r.get("updated_at", r.get("created_at", "")),
        reverse = True,
    ):
        svc_name   = resolve_service_name(req.get("service_id", ""))
        channel    = req.get("channel", "–")
        status     = req.get("status", "–")
        updated_at = req.get("updated_at", req.get("created_at", ""))[:10]
        days_total = _days_since(req.get("created_at", ""))

        with st.container():
            col1, col2 = st.columns([4, 2])
            with col1:
                st.markdown(
                    f"📦 **{svc_name}** — `{req['id'][:8]}`  \n"
                    f"Canal: `{channel}` | Statut: `{status}`"
                )
            with col2:
                st.caption(f"Clôturée: {updated_at}")
                st.caption(f"Durée totale: {days_total} jour(s)")
            st.divider()


# ── Entry point ───────────────────────────────────────────────────────────────
def render() -> None:
    user   = require_roles(config.ROLE_MEMBER)
    render_sidebar_user(user)

    member = _get_member_profile(user)

    st.title("🧬 PLAGENOR 4.0 — Espace Analyste")
    st.caption(
        f"Connecté en tant que: **{user.get('username')}** "
        f"| Rôle: `{user.get('role')}`"
    )

    if not member:
        st.error(
            "❌ Votre compte utilisateur n'est pas encore lié à un profil membre.  \n"
            "Contactez un administrateur pour compléter la configuration."
        )
        st.stop()

    # KPI row
    active       = _load_active_requests()
    mid          = member.get("id", "")
    my_active    = [
        r for r in active
        if r.get("assigned_member_id") == mid
        and r.get("status") in MEMBER_VISIBLE_STATES
    ]
    my_tasks_all = []
    for req in my_active:
        try:
            tasks = get_tasks_for_request(req["id"])
            my_tasks_all += [
                t for t in tasks
                if t.get("assigned_to") == mid and not t.get("done")
            ]
        except Exception:
            pass

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📋 Demandes actives",       len(my_active))
    col2.metric("🔲 Tâches en attente",       len(my_tasks_all))
    col3.metric("🏆 Score productivité",
                f"{float(member.get('productivity_score', 0)):.1f}")
    col4.metric("⚡ Charge actuelle",
                f"{member.get('current_load', 0)} / {member.get('max_load', 5)}")

    st.divider()

    tabs = st.tabs([
        "📋 Mes demandes",
        "📝 Mes tâches",
        "🔬 Analyse",
        "📅 Rendez-vous",
        "👤 Mon profil",
        "📦 Historique",
    ])

    with tabs[0]: _tab_my_requests(member, user)
    with tabs[1]: _tab_tasks(member, user)
    with tabs[2]: _tab_analysis(member, user)
    with tabs[3]: _tab_appointments(member, user)
    with tabs[4]: _tab_profile(member, user)
    with tabs[5]: _tab_history(member, user)