"""
PLAGENOR Admin Validation Panel — IBTIKAR Mode
Admin confirms/modifies price, rejects, adds notes.
Auto-generates Platform Note DOCX on validation.
NO invoice generation in IBTIKAR mode.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from datetime import datetime
import config
from core.repository import (
    get_all_active_requests, get_active_request_by_id, save_active_request,
)
from core.workflow_engine import transition_request
from core.audit_engine import log_event
from core.budget_engine import enforce_budget, get_remaining_budget
from services.document_service import generate_platform_note
from services.notification_service import notify


def render_admin_validation_panel(user: dict):
    st.markdown("## ✅ Request Validation — IBTIKAR Mode")

    pending = [
        r for r in get_all_active_requests()
        if r.get("channel") == config.CHANNEL_IBTIKAR
        and r.get("status") == "SUBMITTED"
    ]

    if not pending:
        st.success("✅ No pending requests awaiting validation.")
        return

    st.info(f"**{len(pending)}** request(s) pending validation.")

    for req in pending:
        form_data = req.get("form_data", {})
        req_info  = form_data.get("requester", {})
        pricing   = form_data.get("pricing", {})
        svc_code  = req.get("service_code", "N/A")

        with st.expander(
            f"📋 {req['id'][:8].upper()} — {svc_code} — "
            f"{req_info.get('full_name', 'Unknown Requester')}",
            expanded=False
        ):
            # Budget snapshot
            budget = get_remaining_budget(req.get("requester_id", ""))
            pct    = budget["pct_used"]
            color  = "#27AE60" if pct < 60 else "#F39C12" if pct < 85 else "#E74C3C"
            st.markdown(f"""
            <div style="background:#f0f8ff;border-radius:8px;padding:10px 16px;
                        border-left:4px solid {color};margin-bottom:12px;">
              <strong>Requester Annual Budget</strong><br/>
              Used: <strong style="color:{color};">{budget['used']:,.0f}</strong> /
              {budget['cap']:,.0f} DZD &nbsp;·&nbsp;
              Remaining: <strong>{budget['remaining']:,.0f} DZD</strong>
              ({budget['pct_used']}% used)
            </div>
            """, unsafe_allow_html=True)

            # Request summary
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Service:**", )
                st.code(svc_code)
                st.markdown("**Requester:**")
                st.write(req_info.get("full_name", ""))
                st.write(req_info.get("institution", ""))
                st.write(req_info.get("email", ""))
            with col2:
                st.markdown("**Estimated Cost:**")
                st.markdown(f"### {pricing.get('total_dzd', 0):,.0f} DZD")
                st.markdown("**Samples:**")
                samples = form_data.get("samples", [])
                st.write(f"{len(samples)} sample(s)")
                biosafety = form_data.get("biosafety", {})
                if biosafety.get("is_pathogenic"):
                    st.error(
                        f"🔴 PATHOGENIC — BSL: {biosafety.get('biosafety_level')}")

            st.markdown("---")
            st.markdown("### Admin Actions")

            col_price, col_notes = st.columns(2)
            with col_price:
                validated_price = st.number_input(
                    "Validated Price (DZD) *",
                    min_value=0.0,
                    value=float(pricing.get("total_dzd", 0)),
                    step=100.0,
                    key=f"vp_{req['id']}")
                price_changed = (
                    validated_price != pricing.get("total_dzd", 0))
                if price_changed:
                    st.warning(
                        f"ℹ️ Price modified from "
                        f"{pricing.get('total_dzd', 0):,.0f} DZD to "
                        f"{validated_price:,.0f} DZD")
            with col_notes:
                admin_notes = st.text_area(
                    "Internal Notes",
                    placeholder="Optional: justification, observations, conditions...",
                    key=f"an_{req['id']}")

            override_just = ""
            if validated_price > budget["remaining"]:
                st.error(
                    f"⚠️ This validation exceeds the requester's remaining budget "
                    f"({budget['remaining']:,.0f} DZD). "
                    f"SUPER_ADMIN override required.")
                if user.get("role") == config.ROLE_SUPER_ADMIN:
                    override_just = st.text_area(
                        "SUPER_ADMIN Override Justification (required) *",
                        key=f"ovj_{req['id']}")

            col_a, col_r = st.columns(2)
            with col_a:
                if st.button(
                    "✅ Validate & Generate Platform Note",
                    use_container_width=True,
                    key=f"val_{req['id']}"
                ):
                    if validated_price > budget["remaining"]:
                        if user.get("role") != config.ROLE_SUPER_ADMIN:
                            st.error("❌ Cannot validate: budget cap exceeded. "
                                     "SUPER_ADMIN required.")
                            return
                        if not override_just.strip():
                            st.error("❌ Override justification required.")
                            return
                        try:
                            enforce_budget(
                                req.get("requester_id"), validated_price,
                                user, override_just)
                        except Exception as e:
                            st.error(str(e))
                            return

                    with st.spinner("Validating and generating document..."):
                        r = get_active_request_by_id(req["id"])
                        r["validated_price"] = validated_price
                        r["admin_notes"]     = admin_notes
                        r["validated_by"]    = user["id"]
                        r["validated_at"]    = datetime.utcnow().isoformat()
                        r["price_modified"]  = price_changed
                        save_active_request(r)

                        transition_request(req["id"], "VALIDATED", user)

                        # Auto-generate Platform Note
                        try:
                            doc_path = generate_platform_note(r, user)
                            r2 = get_active_request_by_id(req["id"])
                            r2["platform_note_path"]    = doc_path
                            r2["platform_note_locked"]  = True
                            r2["platform_note_version"] = "V01"
                            save_active_request(r2)
                            log_event(
                                "DOCUMENT", req["id"],
                                "PLATFORM_NOTE_LOCKED", user["id"],
                                {"path": doc_path})
                            st.success(
                                f"✅ Request validated. Platform Note generated: "
                                f"`{os.path.basename(doc_path)}`")
                            with open(doc_path, "rb") as f:
                                st.download_button(
                                    "📥 Download Platform Note (DOCX)",
                                    data=f,
                                    file_name=os.path.basename(doc_path),
                                    mime="application/vnd.openxmlformats-"
                                         "officedocument.wordprocessingml.document",
                                    key=f"dl_{req['id']}")
                        except Exception as e:
                            st.warning(f"Note generated but download error: {e}")

                        notify(
                            req.get("requester_id"),
                            f"Request {req['id'][:8]} — Validated",
                            f"Your {svc_code} request has been validated at "
                            f"{validated_price:,.0f} DZD. "
                            f"Appointment scheduling will follow.")
                        st.rerun()

            with col_r:
                with st.form(key=f"reject_form_{req['id']}"):
                    reject_reason = st.text_area(
                        "Rejection reason (required) *",
                        key=f"rr_{req['id']}")
                    submitted = st.form_submit_button(
                        "❌ Reject Request",
                        use_container_width=True)
                    if submitted:
                        if not reject_reason.strip():
                            st.error("Rejection reason is mandatory.")
                        else:
                            r = get_active_request_by_id(req["id"])
                            r["rejection_reason"] = reject_reason.strip()
                            r["rejected_by"]      = user["id"]
                            r["rejected_at"]      = datetime.utcnow().isoformat()
                            save_active_request(r)
                            transition_request(req["id"], "REJECTED", user)
                            notify(
                                req.get("requester_id"),
                                f"Request {req['id'][:8]} — Rejected",
                                f"Your {svc_code} request has been rejected. "
                                f"Reason: {reject_reason.strip()}")
                            st.warning("Request rejected.")
                            st.rerun()