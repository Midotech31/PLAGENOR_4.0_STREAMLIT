"""
PLAGENOR Member Assignment Panel
Member sees assignments, accepts/declines, views full IBTIKAR summary.
Admin sees scoring breakdown with weight controls.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from datetime import datetime
import config
from core.repository import (
    get_all_active_requests, get_active_request_by_id, save_active_request,
)
from core.assignment_engine import assign_best_member, get_all_scores
from core.workflow_engine import transition_request
from core.audit_engine import log_event
from core.budget_engine import get_remaining_budget
from services.notification_service import notify


def render_member_assignment_view(user: dict):
    """For MEMBER role: accept/decline, view full request summary."""
    st.markdown("## 📥 My Assignments")

    assigned = [
        r for r in get_all_active_requests()
        if r.get("assigned_member_id") == user["id"]
        and r.get("status") in ("ASSIGNED", "PROCESSING")
    ]

    if not assigned:
        st.info("No active assignments at this time.")
        return

    for req in assigned:
        form_data  = req.get("form_data", {})
        req_info   = form_data.get("requester", {})
        svc_code   = req.get("service_code", "N/A")
        accepted   = req.get("member_accepted")

        with st.expander(
            f"{'✅' if accepted else '⏳'} "
            f"{req['id'][:8].upper()} — {svc_code} — "
            f"{req_info.get('full_name', 'Unknown')}",
            expanded=(accepted is None)
        ):
            # Full request summary
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Service:**")
                st.code(svc_code)
                st.markdown("**Requester:**")
                st.write(req_info.get("full_name", ""))
                st.write(req_info.get("institution", ""))
                analysis = form_data.get("analysis_info", {})
                st.write(f"Project: {analysis.get('project_title', '')}")
                st.write(f"Director: {analysis.get('director', '')}")

            with col2:
                # Budget snapshot (read-only)
                if req.get("channel") == config.CHANNEL_IBTIKAR:
                    budget = get_remaining_budget(req.get("requester_id", ""))
                    st.markdown("**Budget Snapshot (read-only):**")
                    st.markdown(f"""
                    <div style="background:#f0f8ff;border-radius:8px;padding:8px 12px;
                                border-left:3px solid #1B4F72;font-size:0.85rem;">
                      Validated: <strong>{req.get('validated_price', 0):,.0f} DZD</strong>
                      &nbsp;·&nbsp; Annual used: <strong>{budget['used']:,.0f}</strong>
                      / {budget['cap']:,.0f} DZD
                    </div>
                    """, unsafe_allow_html=True)

            # Samples summary
            samples = form_data.get("samples", [])
            if samples:
                st.markdown(f"**{len(samples)} sample(s):**")
                for i, s in enumerate(samples[:5]):
                    st.caption(
                        f"#{i+1} · {s.get('code', '')} · "
                        f"{s.get('organism_type', s.get('sample_type', ''))}")
                if len(samples) > 5:
                    st.caption(f"...and {len(samples)-5} more")

            # Biosafety alert
            biosafety = form_data.get("biosafety", {})
            if biosafety.get("is_pathogenic"):
                st.error(
                    f"🔴 PATHOGENIC SAMPLES — BSL: "
                    f"{biosafety.get('biosafety_level')}")

            # Appointment
            appt = req.get("appointment")
            if appt:
                st.info(f"📅 Appointment: **{appt}**")

            st.markdown("---")

            # Acceptance
            if accepted is None and req.get("status") == "ASSIGNED":
                st.markdown("**⚠️ You must accept this assignment before processing.**")
                col_a, col_d = st.columns(2)
                with col_a:
                    if st.button(
                        "✅ Accept Assignment",
                        key=f"acc_{req['id']}",
                        use_container_width=True
                    ):
                        r = get_active_request_by_id(req["id"])
                        r["member_accepted"]    = True
                        r["member_accepted_at"] = datetime.utcnow().isoformat()
                        save_active_request(r)
                        log_event("ASSIGNMENT", req["id"],
                                  "ASSIGNMENT_ACCEPTED", user["id"], {})
                        notify(
                            r.get("requester_id"),
                            f"Request {req['id'][:8]} — Processing Started",
                            f"Your {svc_code} request has been accepted by "
                            f"the assigned analyst and is now being processed.")
                        st.success("Assignment accepted. You may now proceed.")
                        st.rerun()
                with col_d:
                    with st.form(key=f"decline_{req['id']}"):
                        dec_reason = st.text_area(
                            "Decline reason *", key=f"dr_{req['id']}")
                        if st.form_submit_button(
                            "❌ Decline", use_container_width=True):
                            if not dec_reason.strip():
                                st.error("Reason required.")
                            else:
                                r = get_active_request_by_id(req["id"])
                                r["member_accepted"]    = False
                                r["member_decline_reason"] = dec_reason
                                save_active_request(r)
                                log_event("ASSIGNMENT", req["id"],
                                          "ASSIGNMENT_DECLINED", user["id"],
                                          {"reason": dec_reason})
                                notify(
                                    config.ADMIN_NOTIFICATION_EMAIL,
                                    f"Assignment declined — {req['id'][:8]}",
                                    f"Member declined assignment for {svc_code}. "
                                    f"Reason: {dec_reason}. Reassignment needed.")
                                st.warning("Declined. Admin notified.")
                                st.rerun()

            elif accepted:
                st.success("✅ Assignment accepted — processing in progress.")


def render_admin_assignment_panel(user: dict):
    """For ADMIN/SUPER_ADMIN: smart assignment with score breakdown."""
    st.markdown("## 🎯 Smart Assignment Panel")

    validated = [
        r for r in get_all_active_requests()
        if r.get("status") == "VALIDATED"
        and not r.get("assigned_member_id")
    ]

    if not validated:
        st.info("No validated requests pending assignment.")
        return

    st.info(f"**{len(validated)}** request(s) ready for assignment.")

    for req in validated:
        svc_code = req.get("service_code", "N/A")
        svc_id   = req.get("service_id", "")
        form_data = req.get("form_data", {})
        req_info  = form_data.get("requester", {})

        with st.expander(
            f"🔬 {req['id'][:8].upper()} — {svc_code} — "
            f"{req_info.get('full_name', 'Unknown')}",
            expanded=False
        ):
            # Weight controls
            st.markdown("#### ⚙️ Scoring Weights (Admin adjustable)")
            st.caption("Adjust to fine-tune assignment fairness.")
            c1, c2, c3, c4 = st.columns(4)
            w_skill = c1.slider("Skill",        0, 100, 50,
                                key=f"ws_{req['id']}") / 100
            w_load  = c2.slider("Load",         0, 100, 30,
                                key=f"wl_{req['id']}") / 100
            w_avail = c3.slider("Availability", 0, 100, 10,
                                key=f"wa_{req['id']}") / 100
            w_prod  = c4.slider("Productivity", 0, 100, 10,
                                key=f"wp_{req['id']}") / 100

            total_w = w_skill + w_load + w_avail + w_prod
            if abs(total_w - 1.0) > 0.05:
                st.warning(
                    f"⚠️ Weights sum to {total_w*100:.0f}% — should sum to 100%.")

            weights = {
                "skill": w_skill, "load": w_load,
                "availability": w_avail, "productivity": w_prod
            }

            # Score breakdown table
            st.markdown("#### 📊 Member Scoring Breakdown")
            try:
                scores = get_all_scores(svc_id, weights)
                if scores:
                    import pandas as pd
                    rows = []
                    for entry in scores[:10]:
                        m  = entry["member"]
                        bd = entry["breakdown"]
                        rows.append({
                            "Member":       m.get("name", m["id"][:8]),
                            "Total Score":  f"{entry['score']:.1f}",
                            "Skill":        f"{bd.get('skill_component', 0):.1f}",
                            "Load":         f"{bd.get('load_component', 0):.1f}",
                            "Availability": f"{bd.get('availability_penalty', 0):.1f}",
                            "Productivity": f"{bd.get('productivity_component', 0):.1f}",
                            "Status": "✅ Available" if m.get("available") else "⛔ Busy",
                        })
                    st.dataframe(pd.DataFrame(rows), use_container_width=True)
            except Exception as e:
                st.caption(f"Score preview unavailable: {e}")

            # Assign button
            if st.button(
                f"🎯 Auto-Assign Best Member",
                key=f"assign_{req['id']}",
                use_container_width=True
            ):
                with st.spinner("Scoring and assigning..."):
                    try:
                        best, score, breakdown = assign_best_member(
                            req["id"], svc_id, user, weights)
                        r = get_active_request_by_id(req["id"])
                        r["assigned_member_id"] = best["id"]
                        r["assignment_score"]   = score
                        r["assignment_breakdown"] = breakdown
                        r["assigned_at"]        = datetime.utcnow().isoformat()
                        r["member_accepted"]    = None
                        save_active_request(r)
                        transition_request(req["id"], "ASSIGNED", user)
                        notify(
                            best["id"],
                            f"New Assignment — {svc_code}",
                            f"You have been assigned request "
                            f"{req['id'][:8]} ({svc_code}). "
                            f"Assignment score: {score:.1f}. "
                            f"Please accept or decline in your dashboard.")
                        st.success(
                            f"✅ Assigned to **{best.get('name', best['id'][:8])}** "
                            f"(score: {score:.1f}). "
                            f"Member notified — acceptance required.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))