"""
PLAGENOR Budget Engine
Enforces the IBTIKAR annual cap of 200,000 DZD per requester.
SUPER_ADMIN override requires justification and is permanently logged.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import config
from core.repository import (
    get_all_active_requests, get_override_log, save_override_log
)
from core.audit_engine import log_event
from core.exceptions import BudgetCapExceededError, UnauthorizedError

IBTIKAR_ANNUAL_CAP = 200_000.0


def get_annual_usage(requester_id: str, year: int = None) -> float:
    """Sum all validated/processing IBTIKAR requests for a requester in a year."""
    year = year or datetime.utcnow().year
    total = 0.0
    for req in get_all_active_requests():
        if req.get("channel") != config.CHANNEL_IBTIKAR:
            continue
        if req.get("requester_id") != requester_id:
            continue
        if req.get("status") in ("REJECTED", "CANCELLED"):
            continue
        created = req.get("created_at", "")
        try:
            if int(created[:4]) != year:
                continue
        except Exception:
            continue
        total += float(req.get("validated_price") or req.get("estimated_budget") or 0.0)
    return round(total, 2)


def get_remaining_budget(requester_id: str, year: int = None) -> dict:
    year   = year or datetime.utcnow().year
    used   = get_annual_usage(requester_id, year)
    remain = max(0.0, IBTIKAR_ANNUAL_CAP - used)
    return {
        "requester_id": requester_id,
        "year":         year,
        "cap":          IBTIKAR_ANNUAL_CAP,
        "used":         used,
        "remaining":    remain,
        "pct_used":     round(used / IBTIKAR_ANNUAL_CAP * 100, 1),
        "cap_exceeded": used >= IBTIKAR_ANNUAL_CAP,
    }


def enforce_budget(requester_id: str, amount: float, user: dict,
                   override_justification: str = "") -> dict:
    """
    Enforce IBTIKAR annual cap.
    - If within cap: approve.
    - If exceeded: block unless SUPER_ADMIN provides justification.
    - Override permanently logged.
    """
    budget = get_remaining_budget(requester_id)

    if amount <= budget["remaining"]:
        return {
            "allowed":    True,
            "override":   False,
            "budget":     budget,
            "message":    f"Within annual cap. Remaining after this request: "
                          f"{budget['remaining'] - amount:,.0f} DZD",
        }

    # Cap exceeded
    if user.get("role") != config.ROLE_SUPER_ADMIN:
        raise BudgetCapExceededError(
            f"Annual IBTIKAR budget cap of {IBTIKAR_ANNUAL_CAP:,.0f} DZD exceeded. "
            f"Used: {budget['used']:,.0f} DZD. "
            f"This request requires: {amount:,.0f} DZD. "
            f"Remaining: {budget['remaining']:,.0f} DZD. "
            f"Only SUPER_ADMIN may override."
        )

    if not override_justification or not override_justification.strip():
        raise ValueError(
            "SUPER_ADMIN override requires a non-empty justification."
        )

    # Log override permanently — immutable
    override_entry = {
        "id":                  __import__("uuid").uuid4().__str__(),
        "requester_id":        requester_id,
        "override_by":         user["id"],
        "override_by_role":    user.get("role"),
        "amount_requested":    amount,
        "budget_used_before":  budget["used"],
        "cap":                 IBTIKAR_ANNUAL_CAP,
        "justification":       override_justification.strip(),
        "timestamp":           datetime.utcnow().isoformat(),
        "immutable":           True,
    }
    log = get_override_log()
    log.append(override_entry)
    save_override_log(log)

    log_event("BUDGET", requester_id, "CAP_OVERRIDE_GRANTED",
              user["id"], override_entry)

    return {
        "allowed":      True,
        "override":     True,
        "override_id":  override_entry["id"],
        "budget":       budget,
        "message":      f"SUPER_ADMIN override granted. Justification logged. "
                        f"Override ID: {override_entry['id'][:8]}",
    }


def render_budget_widget(budget: dict) -> str:
    """Returns HTML for the budget indicator widget."""
    pct   = budget["pct_used"]
    used  = budget["used"]
    cap   = budget["cap"]
    rem   = budget["remaining"]
    color = "#27AE60" if pct < 60 else "#F39C12" if pct < 85 else "#E74C3C"
    bar   = min(pct, 100)
    return f"""
<div style="background:#f8f9fa;border-radius:12px;padding:16px 20px;
            border-left:5px solid {color};margin:12px 0;">
  <div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;
              color:#666;font-weight:700;">IBTIKAR Annual Budget — {budget['year']}</div>
  <div style="font-size:1.8rem;font-weight:800;color:{color};margin:6px 0;">
    {used:,.0f} <span style="font-size:0.9rem;color:#888;">/ {cap:,.0f} DZD</span>
  </div>
  <div style="background:#e0e0e0;border-radius:6px;height:10px;margin:8px 0;">
    <div style="background:{color};width:{bar}%;height:10px;border-radius:6px;
                transition:width 0.4s ease;"></div>
  </div>
  <div style="font-size:0.85rem;color:#555;">
    Remaining: <strong style="color:{color};">{rem:,.0f} DZD</strong>
    &nbsp;·&nbsp; Used: <strong>{pct}%</strong>
  </div>
</div>
"""