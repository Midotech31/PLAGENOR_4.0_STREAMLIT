# core/audit_engine.py
# ── PLAGENOR 4.0 — Audit Engine ──────────────────────────────────────────────
# Central audit trail for the platform.
# Responsibilities:
#   - Structured action logging (append-only)
#   - Actor resolution (user context enrichment)
#   - Audit query helpers (by entity, actor, action, date range)
#   - Audit export (CSV, JSON)
#   - Compliance report generation
#   - Sensitive action detection / flagging
#   - Retention policy enforcement
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import io
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Any

import config
from core.repository import (
    append_audit_log,
    get_all_audit_logs as _repo_get_all_audit_logs,
    get_audit_logs_for_entity,
    get_audit_logs_for_user,
    get_audit_logs_by_action,
    get_user,
)

# ── Safe wrapper around repository get_all_audit_logs ────────────────────────

def safe_get_all_audit_logs() -> list[dict]:
    """
    Returns all audit logs, but never raises:
      - Missing/empty/malformed file → [].
      - Non-list result → [].
    """
    try:
        logs = _repo_get_all_audit_logs()
        return logs if isinstance(logs, list) else []
    except Exception:
        return []


# ── Constants ─────────────────────────────────────────────────────────────────

CHANNEL_IBTIKAR  = config.CHANNEL_IBTIKAR
CHANNEL_GENOCLAB = config.CHANNEL_GENOCLAB

# Default audit log retention period (days) — 0 = infinite
AUDIT_RETENTION_DAYS = int(getattr(config, "AUDIT_RETENTION_DAYS", 0))

# Actions that require elevated attention in compliance reports
SENSITIVE_ACTIONS = {
    "FORCED_TRANSITION",
    "TRANSITION_FORCED",
    "DELETE_REQUEST",
    "DELETE_USER",
    "DELETE_INVOICE",
    "RESET_PASSWORD",
    "ROLE_CHANGE",
    "ACCOUNT_DISABLED",
    "ACCOUNT_ENABLED",
    "RESTORE_BACKUP",
    "INVOICE_PAID",
    "BULK_ARCHIVE",
    "DATA_INTEGRITY_FIX",
    "DEDUP_FILE",
}

# Action categories for display grouping
ACTION_CATEGORIES: dict[str, list[str]] = {
    "workflow": [
        "TRANSITION", "TRANSITION_FORCED", "FORCED_TRANSITION",
        "ADVANCE", "BULK_ARCHIVE", "ARCHIVE", "UNARCHIVE",
    ],
    "assignment": ["ASSIGN", "UNASSIGN", "AUTO_ASSIGN"],
    "financial": [
        "INVOICE_GENERATED", "INVOICE_PAID", "QUOTE_SET",
        "BUDGET_APPROVED", "PAYMENT_RECORDED",
    ],
    "document": [
        "REPORT_UPLOADED", "DOCUMENT_CREATED",
        "DOCUMENT_DELETED", "PDF_GENERATED",
    ],
    "user_mgmt": [
        "USER_CREATED", "USER_UPDATED", "DELETE_USER",
        "RESET_PASSWORD", "ROLE_CHANGE",
        "ACCOUNT_DISABLED", "ACCOUNT_ENABLED",
    ],
    "auth": ["LOGIN", "LOGOUT", "LOGIN_FAILED", "SESSION_EXPIRED"],
    "system": [
        "BACKUP_CREATED", "RESTORE_BACKUP",
        "CACHE_CLEARED", "DEDUP_FILE",
        "DATA_INTEGRITY_FIX", "CONFIG_UPDATED",
    ],
    "member": [
        "MEMBER_CREATED", "MEMBER_UPDATED",
        "PRODUCTIVITY_RECALCULATED", "LOAD_INCREMENTED", "LOAD_DECREMENTED",
    ],
    "request": ["REQUEST_SUBMITTED", "REQUEST_CREATED", "REQUEST_UPDATED"],
    "notification": ["NOTIFICATION_SENT", "NOTIFICATION_READ"],
}


# ── Utility helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_dt(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _categorize_action(action: str) -> str:
    """Returns the category label for a given action string."""
    action_upper = action.upper()
    for category, keywords in ACTION_CATEGORIES.items():
        for kw in keywords:
            if kw in action_upper:
                return category
    return "other"


def _is_sensitive(action: str) -> bool:
    """Returns True if the action is in the sensitive set."""
    action_upper = action.upper()
    return any(s in action_upper for s in SENSITIVE_ACTIONS)


def _resolve_actor_display(actor: dict) -> str:
    """Returns a display string for an actor dict."""
    if not actor:
        return "system"
    username = actor.get("username", "")
    user_id  = actor.get("id",       "")
    role     = actor.get("role",     "")
    if username:
        return f"{username} [{role}]" if role else username
    if user_id:
        user = get_user(user_id)
        if user:
            return (
                f"{user.get('username','?')} "
                f"[{user.get('role','')}]"
            )
        return user_id[:8]
    return "system"


# ══════════════════════════════════════════════════════════════════════════════
# CORE LOGGING FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def log_action(
    action:      str,
    entity_type: str,
    entity_id:   str,
    actor:       dict,
    details:     str  = "",
    channel:     Optional[str] = None,
    metadata:    Optional[dict] = None,
) -> dict:
    """
    Appends a structured audit log entry.
    """
    entry: dict = {
        "id":          str(uuid.uuid4()),
        "timestamp":   _now_iso(),
        "action":      action.upper(),
        "entity_type": entity_type.upper(),
        "entity_id":   str(entity_id),
        "user_id":     actor.get("id",       "") if actor else "",
        "username":    actor.get("username", "") if actor else "system",
        "role":        actor.get("role",     "") if actor else "",
        "details":     details,
        "channel":     channel or "",
        "category":    _categorize_action(action),
        "sensitive":   _is_sensitive(action),
        "forced":      "FORCED" in action.upper(),
    }
    if metadata:
        entry["metadata"] = metadata

    append_audit_log(entry)
    return entry


# ── Convenience wrappers ──────────────────────────────────────────────────────

def log_transition(
    request_id:  str,
    from_state:  str,
    to_state:    str,
    actor:       dict,
    channel:     str  = "",
    notes:       str  = "",
    forced:      bool = False,
) -> dict:
    action = "TRANSITION_FORCED" if forced else "TRANSITION"
    return log_action(
        action      = action,
        entity_type = "REQUEST",
        entity_id   = request_id,
        actor       = actor,
        details     = (
            f"{from_state} → {to_state}"
            + (f" | Notes: {notes}" if notes else "")
            + (" | FORCÉ" if forced else "")
        ),
        channel     = channel,
        metadata    = {
            "from_state": from_state,
            "to_state":   to_state,
            "forced":     forced,
        },
    )


def log_assignment(
    request_id:  str,
    member_id:   str,
    member_name: str,
    actor:       dict,
    channel:     str = "",
    auto:        bool = False,
) -> dict:
    return log_action(
        action      = "AUTO_ASSIGN" if auto else "ASSIGN",
        entity_type = "REQUEST",
        entity_id   = request_id,
        actor       = actor,
        details     = (
            f"Assigné à: {member_name} ({member_id[:8]})"
            + (" [auto]" if auto else "")
        ),
        channel     = channel,
        metadata    = {
            "member_id":   member_id,
            "member_name": member_name,
            "auto":        auto,
        },
    )


def log_invoice_event(
    invoice_id:     str,
    event:          str,
    actor:          dict,
    invoice_number: str  = "",
    amount_ttc:     float = 0.0,
    details:        str  = "",
) -> dict:
    return log_action(
        action      = event.upper(),
        entity_type = "INVOICE",
        entity_id   = invoice_id,
        actor       = actor,
        details     = (
            (f"N°: {invoice_number} | " if invoice_number else "")
            + (f"TTC: {amount_ttc:,.0f} DZD | " if amount_ttc else "")
            + details
        ),
        metadata    = {
            "invoice_number": invoice_number,
            "amount_ttc":     amount_ttc,
        },
    )


def log_auth_event(
    event:    str,
    username: str,
    success:  bool,
    ip:       Optional[str] = None,
) -> dict:
    actor = {"id": "", "username": username, "role": ""}
    return log_action(
        action      = event.upper(),
        entity_type = "AUTH",
        entity_id   = username,
        actor       = actor,
        details     = (
            f"{'✅ Succès' if success else '❌ Échec'}"
            + (f" | IP: {ip}" if ip else "")
        ),
        metadata    = {"success": success, "ip": ip},
    )


def log_user_management(
    action:      str,
    target_user: dict,
    actor:       dict,
    details:     str = "",
) -> dict:
    return log_action(
        action      = action.upper(),
        entity_type = "USER",
        entity_id   = target_user.get("id",       ""),
        actor       = actor,
        details     = (
            f"Cible: {target_user.get('username','?')} "
            f"[{target_user.get('role','')}]"
            + (f" | {details}" if details else "")
        ),
        metadata    = {
            "target_username": target_user.get("username", ""),
            "target_role":     target_user.get("role",     ""),
        },
    )


def log_document_event(
    doc_id:     str,
    event:      str,
    actor:      dict,
    request_id: str  = "",
    filename:   str  = "",
    doc_type:   str  = "",
) -> dict:
    return log_action(
        action      = event.upper(),
        entity_type = "DOCUMENT",
        entity_id   = doc_id,
        actor       = actor,
        details     = (
            (f"Fichier: {filename} | " if filename else "")
            + (f"Type: {doc_type} | " if doc_type else "")
            + (f"Demande: {request_id[:8]}" if request_id else "")
        ),
        metadata    = {
            "request_id": request_id,
            "filename":   filename,
            "doc_type":   doc_type,
        },
    )


def log_system_event(
    event:   str,
    actor:   dict,
    details: str = "",
) -> dict:
    return log_action(
        action      = event.upper(),
        entity_type = "SYSTEM",
        entity_id   = "platform",
        actor       = actor,
        details     = details,
    )


def log_productivity_event(
    member_id:   str,
    member_name: str,
    score:       float,
    label:       str,
    actor:       dict,
) -> dict:
    return log_action(
        action      = "PRODUCTIVITY_RECALCULATED",
        entity_type = "MEMBER",
        entity_id   = member_id,
        actor       = actor,
        details     = (
            f"Membre: {member_name} | "
            f"Score: {score:.1f} | Niveau: {label}"
        ),
        metadata    = {
            "member_name": member_name,
            "score":       score,
            "label":       label,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# QUERY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_logs_filtered(
    action_filter:      Optional[str]      = None,
    entity_type_filter: Optional[str]      = None,
    entity_id_filter:   Optional[str]      = None,
    user_id_filter:     Optional[str]      = None,
    username_filter:    Optional[str]      = None,
    channel_filter:     Optional[str]      = None,
    category_filter:    Optional[str]      = None,
    sensitive_only:     bool              = False,
    forced_only:        bool              = False,
    date_from:          Optional[datetime] = None,
    date_to:            Optional[datetime] = None,
    limit:              int               = 500,
    newest_first:       bool              = True,
) -> list[dict]:
    """
    Returns filtered audit log entries.
    """
    logs = safe_get_all_audit_logs()

    if action_filter:
        sq = action_filter.upper()
        logs = [l for l in logs if sq in l.get("action", "").upper()]

    if entity_type_filter:
        sq = entity_type_filter.upper()
        logs = [l for l in logs if sq in l.get("entity_type", "").upper()]

    if entity_id_filter:
        logs = [
            l for l in logs
            if l.get("entity_id", "") == entity_id_filter
        ]

    if user_id_filter:
        logs = [
            l for l in logs
            if l.get("user_id", "") == user_id_filter
        ]

    if username_filter:
        sq = username_filter.lower()
        logs = [
            l for l in logs
            if sq in l.get("username", "").lower()
        ]

    if channel_filter:
        logs = [
            l for l in logs
            if l.get("channel", "") == channel_filter
        ]

    if category_filter:
        logs = [
            l for l in logs
            if l.get("category", "") == category_filter
        ]

    if sensitive_only:
        logs = [l for l in logs if l.get("sensitive", False)]

    if forced_only:
        logs = [l for l in logs if l.get("forced", False)]

    if date_from:
        logs = [
            l for l in logs
            if (_parse_dt(l.get("timestamp", "")) or datetime.min) >= date_from
        ]

    if date_to:
        logs = [
            l for l in logs
            if (_parse_dt(l.get("timestamp", "")) or datetime.max) <= date_to
        ]

    logs = sorted(
        logs,
        key     = lambda x: x.get("timestamp", ""),
        reverse = newest_first,
    )

    return logs[:limit]


def get_recent_logs(limit: int = 50) -> list[dict]:
    """Returns the most recent audit log entries."""
    return get_logs_filtered(limit=limit, newest_first=True)


def get_entity_history(
    entity_type: str,
    entity_id:   str,
) -> list[dict]:
    """
    Returns the full chronological history for a specific entity.
    (e.g. all events for REQUEST abc123)
    """
    logs = get_audit_logs_for_entity(entity_type.upper(), entity_id)
    return sorted(logs, key=lambda x: x.get("timestamp", ""))


def get_actor_activity(
    user_id:      str,
    limit:        int  = 100,
    newest_first: bool = True,
) -> list[dict]:
    """Returns all audit entries performed by a specific user."""
    logs = get_audit_logs_for_user(user_id)
    logs = sorted(
        logs,
        key     = lambda x: x.get("timestamp", ""),
        reverse = newest_first,
    )
    return logs[:limit]


def get_sensitive_log_count(days: int = 30) -> int:
    """Returns count of sensitive actions in the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    return len(get_logs_filtered(
        sensitive_only = True,
        date_from      = cutoff,
        limit          = 10_000,
    ))


def get_forced_transitions(days: int = 30) -> list[dict]:
    """Returns all forced transitions in the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    return get_logs_filtered(
        forced_only = True,
        date_from   = cutoff,
        limit       = 1_000,
    )


def count_actions_by_category(days: int = 30) -> dict[str, int]:
    """
    Returns a count of log entries grouped by category
    for the last N days.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs   = get_logs_filtered(date_from=cutoff, limit=50_000)
    counts: dict = {}
    for log in logs:
        cat = log.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


def count_actions_by_user(days: int = 30, top_n: int = 10) -> list[dict]:
    """
    Returns top N most active users (by audit log count)
    in the last N days.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs   = get_logs_filtered(date_from=cutoff, limit=50_000)

    user_counts: dict = {}
    for log in logs:
        uid   = log.get("user_id",  "system")
        uname = log.get("username", "system")
        key   = (uid, uname)
        user_counts[key] = user_counts.get(key, 0) + 1

    ranked = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    return [
        {"user_id": k[0], "username": k[1], "count": v}
        for k, v in ranked[:top_n]
    ]


def count_actions_by_day(days: int = 30) -> dict[str, int]:
    """
    Returns a count of log entries per calendar day
    for the last N days.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs   = get_logs_filtered(date_from=cutoff, limit=50_000)

    by_day: dict = {}
    for log in logs:
        ts = log.get("timestamp", "")[:10]
        if ts:
            by_day[ts] = by_day.get(ts, 0) + 1

    return dict(sorted(by_day.items()))


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def export_logs_csv(
    logs:     list[dict],
    columns:  Optional[list[str]] = None,
) -> str:
    """
    Exports a list of log entries to a CSV string.
    """
    default_cols = [
        "timestamp", "action", "category", "entity_type",
        "entity_id", "username", "role", "channel",
        "sensitive", "forced", "details",
    ]
    cols = columns or default_cols

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames     = cols,
        extrasaction   = "ignore",
        lineterminator = "\n",
    )
    writer.writeheader()
    for log in logs:
        row = {col: log.get(col, "") for col in cols}
        if "timestamp" in row and row["timestamp"]:
            row["timestamp"] = str(row["timestamp"])[:16]
        writer.writerow(row)

    return output.getvalue()


def export_logs_json(logs: list[dict]) -> str:
    """Exports a list of log entries to a JSON string."""
    return json.dumps(logs, ensure_ascii=False, indent=2)


def export_logs_for_request(request_id: str) -> str:
    """
    Exports all audit logs for a specific request as CSV.
    """
    logs = get_entity_history("REQUEST", request_id)
    return export_logs_csv(logs)


# ══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE REPORT
# ══════════════════════════════════════════════════════════════════════════════

def generate_compliance_report(
    year:  Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    """
    Generates a structured compliance report for a given period.
    """
    now = datetime.utcnow()

    if year and month:
        date_from    = datetime(year, month, 1)
        if month == 12:
            date_to = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            date_to = datetime(year, month + 1, 1) - timedelta(seconds=1)
        period_label = f"{year}-{month:02d}"
    elif year:
        date_from    = datetime(year, 1, 1)
        date_to      = datetime(year, 12, 31, 23, 59, 59)
        period_label = str(year)
    else:
        date_from    = now - timedelta(days=30)
        date_to      = now
        period_label = f"30 derniers jours (au {now.strftime('%d/%m/%Y')})"

    all_logs = get_logs_filtered(
        date_from    = date_from,
        date_to      = date_to,
        limit        = 100_000,
        newest_first = False,
    )

    sensitive_logs = [l for l in all_logs if l.get("sensitive",  False)]
    forced_logs    = [l for l in all_logs if l.get("forced",     False)]

    failed_logins = [
        l for l in all_logs
        if "LOGIN_FAILED" in l.get("action", "").upper()
        or (
            "LOGIN" in l.get("action", "").upper()
            and not (l.get("metadata") or {}).get("success", True)
        )
    ]

    role_changes = [
        l for l in all_logs
        if "ROLE_CHANGE" in l.get("action", "").upper()
    ]

    invoice_payments = [
        l for l in all_logs
        if "INVOICE_PAID" in l.get("action", "").upper()
        or "PAYMENT_RECORDED" in l.get("action", "").upper()
    ]

    by_cat: dict = {}
    for log in all_logs:
        cat = log.get("category", "other")
        by_cat[cat] = by_cat.get(cat, 0) + 1

    user_counts: dict = {}
    for log in all_logs:
        uname = log.get("username", "system")
        user_counts[uname] = user_counts.get(uname, 0) + 1
    by_user = [
        {"username": k, "count": v}
        for k, v in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    ][:20]

    by_day: dict = {}
    for log in all_logs:
        ts = log.get("timestamp", "")[:10]
        if ts:
            by_day[ts] = by_day.get(ts, 0) + 1

    return {
        "period_label":              period_label,
        "generated_at":              now.isoformat(),
        "date_from":                 date_from.isoformat(),
        "date_to":                   date_to.isoformat(),
        "total_entries":             len(all_logs),
        "sensitive_count":           len(sensitive_logs),
        "forced_transitions_count":  len(forced_logs),
        "failed_logins_count":       len(failed_logins),
        "role_changes_count":        len(role_changes),
        "invoice_payments_count":    len(invoice_payments),
        "by_category":               dict(
            sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        ),
        "by_user":                   by_user,
        "by_day":                    dict(sorted(by_day.items())),
        "sensitive_log":             sensitive_logs[:100],
        "forced_log":                forced_logs[:50],
    }


def export_compliance_report_csv(report: dict) -> str:
    """
    Exports the sensitive_log section of a compliance report as CSV.
    """
    header_lines = [
        "# PLAGENOR 4.0 — Rapport de conformité",
        f"# Période: {report.get('period_label','')}",
        f"# Généré le: {report.get('generated_at','')[:16]}",
        f"# Total entrées: {report.get('total_entries',0)}",
        f"# Actions sensibles: {report.get('sensitive_count',0)}",
        f"# Transitions forcées: {report.get('forced_transitions_count',0)}",
        f"# Connexions échouées: {report.get('failed_logins_count',0)}",
        "#",
    ]
    csv_section = export_logs_csv(
        report.get("sensitive_log", [])
    )
    return "\n".join(header_lines) + "\n" + csv_section


# ══════════════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_anomalies(
    window_minutes: int = 60,
    max_actions:    int = 50,
) -> list[dict]:
    """
    Detects potentially anomalous activity patterns.
    """
    cutoff  = datetime.utcnow() - timedelta(minutes=window_minutes)
    logs    = get_logs_filtered(date_from=cutoff, limit=10_000, newest_first=False)
    anomalies: list = []

    # 1. High-frequency actor
    actor_counts: dict = {}
    for log in logs:
        uid = log.get("user_id", "system")
        actor_counts[uid] = actor_counts.get(uid, 0) + 1

    for uid, count in actor_counts.items():
        if count >= max_actions:
            user = get_user(uid) or {}
            anomalies.append({
                "type":        "HIGH_FREQUENCY_ACTOR",
                "severity":    "warning" if count < max_actions * 2 else "error",
                "description": (
                    f"L'utilisateur '{user.get('username', uid[:8])}' "
                    f"a effectué {count} actions en {window_minutes} min."
                ),
                "user_id":     uid,
                "username":    user.get("username", uid[:8]),
                "count":       count,
                "window":      window_minutes,
            })

    # 2. Repeated failed logins
    failed_by_user: dict = {}
    for log in logs:
        if "LOGIN_FAILED" in log.get("action", "").upper():
            uname = log.get("username", "?")
            failed_by_user[uname] = failed_by_user.get(uname, 0) + 1

    for uname, count in failed_by_user.items():
        if count >= 3:
            anomalies.append({
                "type":        "REPEATED_LOGIN_FAILURE",
                "severity":    "warning" if count < 5 else "error",
                "description": (
                    f"{count} tentatives de connexion échouées "
                    f"pour '{uname}' en {window_minutes} min."
                ),
                "user_id":     "",
                "username":    uname,
                "count":       count,
                "window":      window_minutes,
            })

    # 3. Excessive forced transitions
    forced_count = sum(1 for l in logs if l.get("forced", False))
    if forced_count >= 3:
        anomalies.append({
            "type":        "EXCESSIVE_FORCED_TRANSITIONS",
            "severity":    "error",
            "description": (
                f"{forced_count} transitions forcées "
                f"détectées en {window_minutes} min."
            ),
            "user_id":     "",
            "username":    "multiple",
            "count":       forced_count,
            "window":      window_minutes,
        })

    return sorted(
        anomalies,
        key     = lambda x: {"error": 0, "warning": 1}.get(x["severity"], 2),
    )


# ══════════════════════════════════════════════════════════════════════════════
# RETENTION POLICY
# ══════════════════════════════════════════════════════════════════════════════

def apply_retention_policy(
    retention_days: Optional[int] = None,
    dry_run:        bool          = True,
) -> dict:
    """
    Removes audit log entries older than retention_days.
    Sensitive entries are ALWAYS kept regardless of age.
    """
    days = retention_days or AUDIT_RETENTION_DAYS
    if not days:
        return {
            "retention_days": 0,
            "total_before":   len(safe_get_all_audit_logs()),
            "to_remove":      0,
            "sensitive_kept": 0,
            "dry_run":        dry_run,
            "note":           "Rétention désactivée (0 = infini).",
        }

    cutoff    = datetime.utcnow() - timedelta(days=days)
    all_logs  = safe_get_all_audit_logs()
    total     = len(all_logs)
    to_remove = []
    to_keep   = []
    sens_kept = 0

    for log in all_logs:
        ts = _parse_dt(log.get("timestamp", ""))
        if ts and ts < cutoff:
            if log.get("sensitive", False):
                to_keep.append(log)
                sens_kept += 1
            else:
                to_remove.append(log)
        else:
            to_keep.append(log)

    result = {
        "retention_days": days,
        "total_before":   total,
        "to_remove":      len(to_remove),
        "sensitive_kept": sens_kept,
        "dry_run":        dry_run,
    }

    if not dry_run and to_remove:
        from core.repository import _write_json, AUDIT_LOGS_FILE
        _write_json(AUDIT_LOGS_FILE, to_keep)
        result["removed"] = len(to_remove)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT SUMMARY (for dashboards)
# ══════════════════════════════════════════════════════════════════════════════

def get_audit_dashboard_summary(days: int = 7) -> dict:
    """
    Returns a lightweight summary dict suitable for dashboard KPI display.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs   = get_logs_filtered(date_from=cutoff, limit=50_000, newest_first=False)

    users_in_period = {
        l.get("user_id") for l in logs
        if l.get("user_id") and l.get("user_id") != "system"
    }

    by_cat  = count_actions_by_category(days=days)
    by_day  = count_actions_by_day(days=days)
    by_user = count_actions_by_user(days=days, top_n=1)

    most_active = by_user[0]["username"] if by_user else "–"

    failed_logins = sum(
        1 for l in logs
        if "LOGIN_FAILED" in l.get("action", "").upper()
    )

    anomalies = detect_anomalies(window_minutes=60 * 24, max_actions=200)

    return {
        "period_days":        days,
        "total_actions":      len(logs),
        "sensitive_actions":  sum(1 for l in logs if l.get("sensitive",  False)),
        "forced_transitions": sum(1 for l in logs if l.get("forced",    False)),
        "failed_logins":      failed_logins,
        "active_users":       len(users_in_period),
        "most_active_user":   most_active,
        "anomalies_count":    len(anomalies),
        "category_counts":    by_cat,
        "daily_counts":       by_day,
    }


# ── Alias — used by assignment_engine and workflow_engine ────────────────────

def log_event(
    action:      str,
    entity_type: str  = "SYSTEM",
    entity_id:   str  = "",
    actor:       dict = None,
    details:     str  = "",
    **kwargs,
) -> dict:
    """Alias for log_action — non-breaking wrapper for legacy callers."""
    return log_action(
        action      = action,
        entity_type = entity_type,
        entity_id   = entity_id,
        actor       = actor or {},
        details     = details,
        channel     = kwargs.get("channel"),
        metadata    = kwargs.get("metadata"),
    )
