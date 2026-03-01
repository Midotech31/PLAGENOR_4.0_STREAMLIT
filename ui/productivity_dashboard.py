"""
PLAGENOR Productivity Dashboard
Visualizes member performance, leaderboard, and declining alerts.
Zero business logic — display only.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from datetime import datetime
from core.productivity_engine import (
    get_leaderboard, recalculate_all, get_productivity_label,
    PRODUCTIVITY_BADGES, recalculate_member,
)
from core.repository import get_all_members
import config


def render_productivity_dashboard(user: dict):
    st.markdown("## 📊 Productivity Dashboard")
    now = datetime.utcnow()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"**Period:** {now.strftime('%B %Y')}")
    with col2:
        if user.get("role") == config.ROLE_SUPER_ADMIN:
            if st.button("🔄 Recalculate All", use_container_width=True):
                with st.spinner("Recalculating..."):
                    results = recalculate_all(user)
                st.success(f"✅ Recalculated {len(results)} members.")
                st.rerun()
    with col3:
        threshold_expander = st.expander("⚙️ Thresholds")

    with threshold_expander:
        if user.get("role") == config.ROLE_SUPER_ADMIN:
            st.caption("Adjust performance classification thresholds:")
            t_on_fire = st.slider("🔥 ON FIRE ≥", 60, 100,
                                  config.PRODUCTIVITY_THRESHOLDS.get("ON_FIRE", 85),
                                  key="thresh_on_fire")
            t_active  = st.slider("✅ ACTIVE ≥", 40, 90,
                                  config.PRODUCTIVITY_THRESHOLDS.get("ACTIVE", 60),
                                  key="thresh_active")
            t_normal  = st.slider("📊 NORMAL ≥", 20, 70,
                                  config.PRODUCTIVITY_THRESHOLDS.get("NORMAL", 40),
                                  key="thresh_normal")
            if st.button("Save Thresholds"):
                config.PRODUCTIVITY_THRESHOLDS["ON_FIRE"] = t_on_fire
                config.PRODUCTIVITY_THRESHOLDS["ACTIVE"]  = t_active
                config.PRODUCTIVITY_THRESHOLDS["NORMAL"]  = t_normal
                st.success("Thresholds updated.")
        else:
            st.info("Thresholds configurable by SUPER_ADMIN only.")

    st.markdown("---")

    # ── Leaderboard ────────────────────────────────────────────────────────────
    st.markdown("### 🏆 Member Performance Ranking")
    board = get_leaderboard()

    if not board:
        st.info("No productivity data available for this period. "
                "Run 'Recalculate All' to generate scores.")
        return

    # Summary KPI row
    scores = [m["score"] for m in board]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Average Score", f"{sum(scores)/len(scores):.1f}")
    k2.metric("Top Score",     f"{max(scores):.1f}")
    k3.metric("🔥 ON FIRE",    sum(1 for m in board if m["label"] == "ON_FIRE"))
    k4.metric("⚠️ Low Perf",  sum(1 for m in board if m["label"] == "LOW"))

    st.markdown("---")

    # Member cards
    for rank, member in enumerate(board, 1):
        emoji, color = PRODUCTIVITY_BADGES.get(member["label"], ("📊", "#F39C12"))
        declining_tag = (
            '<span style="color:#E74C3C;font-size:0.75rem;">'
            '📉 Declining Performance</span>'
            if member.get("declining") else ""
        )
        st.markdown(f"""
        <div style="
            background: white; border-radius: 12px; padding: 14px 20px;
            margin-bottom: 10px; border-left: 5px solid {color};
            box-shadow: 0 2px 6px rgba(0,0,0,0.06);
            display: flex; justify-content: space-between; align-items: center;
        ">
            <div>
                <span style="font-size:1.1rem;font-weight:700;color:#333;">
                    #{rank} {member['name']}
                </span>
                &nbsp;&nbsp;
                <span style="background:{color};color:white;padding:2px 8px;
                             border-radius:10px;font-size:0.75rem;font-weight:600;">
                    {emoji} {member['label']}
                </span>
                &nbsp; {declining_tag}
            </div>
            <div style="font-size:1.6rem;font-weight:800;color:{color};">
                {member['score']:.1f}
                <span style="font-size:0.8rem;color:#888;">/100</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Declining alerts
    declining = [m for m in board if m.get("declining")]
    if declining:
        st.warning(
            f"⚠️ **{len(declining)} member(s) showing declining performance "
            f"(>10 point drop):** "
            + ", ".join(m["name"] for m in declining)
        )

    # Detailed breakdown per member
    st.markdown("---")
    st.markdown("### 🔍 Individual Metrics")
    members     = get_all_members()
    member_opts = {m.get("name", m["id"][:8]): m for m in members}
    sel_name    = st.selectbox("Select member", list(member_opts.keys()),
                               key="prod_sel_member")
    sel_member  = member_opts[sel_name]
    metrics     = sel_member.get("productivity_metrics", {})

    if metrics:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Completion Rate",  f"{metrics.get('completion_rate', 0):.1f}%")
        m2.metric("Acceptance Rate",  f"{metrics.get('acceptance_rate', 0):.1f}%")
        m3.metric("Turnaround Score", f"{metrics.get('turnaround_score', 0):.1f}")
        m4.metric("Report Quality",   f"{metrics.get('report_quality', 0):.1f}")
        m5.metric("Load Efficiency",  f"{metrics.get('load_efficiency', 0):.1f}%")
        st.caption(
            f"Avg turnaround: **{metrics.get('avg_turnaround_days', 'N/A')} days** · "
            f"Assigned: {metrics.get('assigned', 0)} · "
            f"Completed: {metrics.get('completed', 0)}")
    else:
        st.info("No metrics computed for this member yet.")

    # 12-month history chart
    history = sel_member.get("productivity_history", [])
    if len(history) > 1:
        import pandas as pd
        df = pd.DataFrame(history)
        df["period"] = df["month"].astype(str) + "/" + df["year"].astype(str)
        df = df.sort_values(["year", "month"])
        st.line_chart(df.set_index("period")["score"],
                      use_container_width=True)