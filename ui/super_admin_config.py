"""
PLAGENOR SUPER_ADMIN Configuration Panel
Clone services, modify fields, change pricing, update templates.
STRICTLY: no direct state mutation, no workflow bypass.
"""
import sys, os, json, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
import config
from core.repository import get_all_services, save_service, get_all_services
from core.audit_engine import log_event
import uuid


def render_super_admin_config(user: dict):
    if user.get("role") != config.ROLE_SUPER_ADMIN:
        st.error("❌ Access denied. SUPER_ADMIN only.")
        return

    st.markdown("## ⚙️ SUPER_ADMIN — System Configuration")

    tabs = st.tabs([
        "🗂️ Service Management",
        "📧 Email Templates",
        "🌐 CMS Content",
        "👥 Members & Roles",
        "📊 Override Audit Log",
    ])

    # ── Tab 1: Service Management ─────────────────────────────────────────────
    with tabs[0]:
        st.markdown("### Service Registry")
        st.warning(
            "⚠️ Modifications affect pricing and form display only. "
            "Workflow engine and financial logic cannot be modified here.")

        services  = get_all_services()
        svc_names = {s["code"]: s for s in services}
        sel_code  = st.selectbox(
            "Select service to edit", list(svc_names.keys()),
            key="sa_svc_sel")
        svc       = copy.deepcopy(svc_names[sel_code])

        col1, col2 = st.columns(2)
        with col1:
            svc["name"]       = st.text_input(
                "Service Name", value=svc.get("name", ""), key="sa_name")
            svc["base_price"] = st.number_input(
                "Base Price (DZD)", value=float(svc.get("base_price", 0)),
                step=100.0, key="sa_bp")
            svc["price_min"]  = st.number_input(
                "Price Min (DZD)", value=float(svc.get("price_min", 0)),
                step=100.0, key="sa_pmin")
            svc["price_max"]  = st.number_input(
                "Price Max (DZD)", value=float(svc.get("price_max") or 0),
                step=100.0, key="sa_pmax")
        with col2:
            svc["turnaround_days"] = st.number_input(
                "Turnaround Days", value=int(svc.get("turnaround_days") or 0),
                key="sa_tad")
            svc["active"] = st.checkbox(
                "Service Active", value=svc.get("active", True), key="sa_act")
            svc["description"] = st.text_area(
                "Description", value=svc.get("description", ""), key="sa_desc")

        col_s, col_c = st.columns(2)
        with col_s:
            if st.button("💾 Save Changes", use_container_width=True,
                         key="sa_save"):
                save_service(svc)
                log_event("CONFIG", svc["id"], "SERVICE_UPDATED",
                          user["id"],
                          {"code": svc["code"], "changes": svc})
                st.success(f"✅ Service `{svc['code']}` updated.")
                st.rerun()
        with col_c:
            if st.button("📋 Clone Service", use_container_width=True,
                         key="sa_clone"):
                cloned       = copy.deepcopy(svc)
                cloned["id"] = str(uuid.uuid4())
                cloned["code"] = svc["code"] + "_COPY"
                cloned["name"] = svc["name"] + " (Copy)"
                cloned["active"] = False
                save_service(cloned)
                log_event("CONFIG", cloned["id"], "SERVICE_CLONED",
                          user["id"],
                          {"source_code": svc["code"],
                           "new_code": cloned["code"]})
                st.success(
                    f"✅ Service cloned as `{cloned['code']}` (inactive). "
                    f"Edit and activate when ready.")
                st.rerun()

    # ── Tab 2: Email Templates ─────────────────────────────────────────────────
    with tabs[1]:
        st.markdown("### Email Template Editor")
        templates_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "email_templates.json")

        if os.path.exists(templates_path):
            with open(templates_path, "r", encoding="utf-8") as f:
                templates = json.load(f)
        else:
            templates = {
                "REQUEST_SUBMITTED":  {
                    "subject": "PLAGENOR — Request {request_id} Received",
                    "body":    "Dear {full_name},\n\nYour request {request_id} "
                               "for {service_code} has been submitted.\n"
                               "Estimated cost: {amount} DZD.\n\n"
                               "PLAGENOR Team"
                },
                "REQUEST_VALIDATED":  {
                    "subject": "PLAGENOR — Request {request_id} Validated",
                    "body":    "Dear {full_name},\n\nYour request has been "
                               "validated at {validated_price} DZD.\n\n"
                               "PLAGENOR Team"
                },
                "REQUEST_REJECTED":   {
                    "subject": "PLAGENOR — Request {request_id} Rejected",
                    "body":    "Dear {full_name},\n\nYour request has been "
                               "rejected.\nReason: {reason}\n\nPLAGENOR Team"
                },
                "ASSIGNMENT_CREATED": {
                    "subject": "PLAGENOR — New Assignment {request_id}",
                    "body":    "Dear {member_name},\n\nYou have been assigned "
                               "request {request_id}.\nPlease accept or "
                               "decline in your dashboard.\n\nPLAGENOR Team"
                },
            }

        tpl_names = list(templates.keys())
        sel_tpl   = st.selectbox("Select template", tpl_names, key="sa_tpl")
        tpl       = templates[sel_tpl]

        new_subject = st.text_input(
            "Subject", value=tpl.get("subject", ""), key="sa_tpl_sub")
        new_body    = st.text_area(
            "Body (use {placeholders})", value=tpl.get("body", ""),
            height=200, key="sa_tpl_body")
        st.caption(
            "Available placeholders: {full_name}, {request_id}, "
            "{service_code}, {amount}, {validated_price}, {reason}, "
            "{member_name}, {appointment}")

        if st.button("💾 Save Template", key="sa_tpl_save"):
            templates[sel_tpl]["subject"] = new_subject
            templates[sel_tpl]["body"]    = new_body
            os.makedirs(os.path.dirname(templates_path), exist_ok=True)
            with open(templates_path, "w", encoding="utf-8") as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)
            log_event("CONFIG", sel_tpl, "EMAIL_TEMPLATE_UPDATED",
                      user["id"], {"template": sel_tpl})
            st.success(f"✅ Template `{sel_tpl}` saved.")

    # ── Tab 3: CMS Content ─────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown("### CMS — Platform Content")
        cms_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "cms_content.json")

        if os.path.exists(cms_path):
            with open(cms_path, "r", encoding="utf-8") as f:
                cms = json.load(f)
        else:
            cms = {
                "ibtikar_overview": (
                    "PLAGENOR is officially registered on the IBTIKAR national "
                    "platform operated by the DGRSDT. This channel is exclusively "
                    "reserved for PhD students, academic researchers, and affiliated "
                    "laboratory teams. Services are subsidised and subject to an "
                    "annual allocation cap of 200,000 DZD per requester."
                ),
                "genoclab_overview": (
                    "GENOCLAB is the commercial branch of PLAGENOR dedicated to "
                    "private companies, agri-food industries, clinical laboratories, "
                    "and international partners requiring certified genomic analysis "
                    "with full commercial traceability."
                ),
                "platform_name":    "PLAGENOR",
                "institution":      "ESSBO — Oran, Algeria",
                "contact_email":    "mohamed.merzoug.essbo@gmail.com",
            }

        cms_keys = list(cms.keys())
        sel_cms  = st.selectbox("Select content block", cms_keys, key="sa_cms")
        new_val  = st.text_area(
            f"Edit: {sel_cms}", value=cms[sel_cms], height=150,
            key="sa_cms_val")

        if st.button("💾 Save Content", key="sa_cms_save"):
            cms[sel_cms] = new_val
            os.makedirs(os.path.dirname(cms_path), exist_ok=True)
            with open(cms_path, "w", encoding="utf-8") as f:
                json.dump(cms, f, ensure_ascii=False, indent=2)
            log_event("CONFIG", sel_cms, "CMS_UPDATED",
                      user["id"], {"key": sel_cms})
            st.success(f"✅ Content block `{sel_cms}` updated.")

    # ── Tab 4: Members & Roles ─────────────────────────────────────────────────
    with tabs[3]:
        st.markdown("### Member Management")
        from core.repository import get_all_members, save_member
        members = get_all_members()
        for m in members:
            with st.expander(
                f"{m.get('name', m['id'][:8])} — {m.get('role', 'MEMBER')}"):
                col1, col2 = st.columns(2)
                with col1:
                    new_avail = st.checkbox(
                        "Available for assignment",
                        value=m.get("available", True),
                        key=f"avail_{m['id']}")
                    new_load  = st.number_input(
                        "Max concurrent load",
                        value=int(m.get("max_load", 5)),
                        min_value=1, max_value=20,
                        key=f"maxload_{m['id']}")
                with col2:
                    new_role = st.selectbox(
                        "Role",
                        [config.ROLE_MEMBER, config.ROLE_PLATFORM_ADMIN,
                         config.ROLE_SUPER_ADMIN, config.ROLE_FINANCE,
                         config.ROLE_CLIENT],
                        index=[config.ROLE_MEMBER, config.ROLE_PLATFORM_ADMIN,
                               config.ROLE_SUPER_ADMIN, config.ROLE_FINANCE,
                               config.ROLE_CLIENT].index(
                                   m.get("role", config.ROLE_MEMBER)),
                        key=f"role_{m['id']}")
                if st.button("💾 Save", key=f"save_m_{m['id']}"):
                    m["available"] = new_avail
                    m["max_load"]  = new_load
                    m["role"]      = new_role
                    save_member(m)
                    log_event("CONFIG", m["id"], "MEMBER_UPDATED",
                              user["id"],
                              {"available": new_avail, "role": new_role})
                    st.success("Member updated.")
                    st.rerun()

    # ── Tab 5: Override Audit Log ──────────────────────────────────────────────
    with tabs[4]:
        st.markdown("### Budget Override Audit Log (Immutable)")
        from core.repository import get_override_log
        overrides = get_override_log()
        if not overrides:
            st.info("No override events recorded.")
        else:
            import pandas as pd
            df = pd.DataFrame(overrides)
            st.dataframe(df[[
                "timestamp", "requester_id", "override_by",
                "amount_requested", "budget_used_before",
                "justification"
            ]], use_container_width=True)
            st.caption(
                f"Total overrides: **{len(overrides)}** — "
                "All records are immutable and permanently logged.")