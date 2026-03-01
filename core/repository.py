# core/repository.py
# ── PLAGENOR 4.0 — Data Repository Layer ─────────────────────────────────────
# All JSON file I/O for the platform.
# Single source of truth for reads and writes.
# Thread-safe via threading.Lock per file.
# No business logic — pure CRUD + query helpers.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import threading
import uuid
import shutil
from datetime import datetime
from typing import Optional, Any

import config


# ── File path constants ───────────────────────────────────────────────────────
USERS_FILE             = getattr(config, "USERS_FILE",             "data/users.json")
MEMBERS_FILE           = getattr(config, "MEMBERS_FILE",           "data/members.json")
SERVICES_FILE          = getattr(config, "SERVICES_FILE",          "data/services.json")
ACTIVE_REQUESTS_FILE   = getattr(config, "ACTIVE_REQUESTS_FILE",   "data/active_requests.json")
ARCHIVED_REQUESTS_FILE = getattr(config, "ARCHIVED_REQUESTS_FILE", "data/archived_requests.json")
INVOICES_FILE          = getattr(config, "INVOICES_FILE",          "data/invoices.json")
INVOICE_SEQUENCE_FILE  = getattr(config, "INVOICE_SEQUENCE_FILE",  "data/invoice_sequence.json")
AUDIT_LOGS_FILE        = getattr(config, "AUDIT_LOGS_FILE",        "data/audit_logs.json")
DOCUMENTS_FILE         = getattr(config, "DOCUMENTS_FILE",         "data/documents.json")
NOTIFICATIONS_FILE     = getattr(config, "NOTIFICATIONS_FILE",     "data/notifications.json")

ALL_DATA_FILES = [
    USERS_FILE,
    MEMBERS_FILE,
    SERVICES_FILE,
    ACTIVE_REQUESTS_FILE,
    ARCHIVED_REQUESTS_FILE,
    INVOICES_FILE,
    INVOICE_SEQUENCE_FILE,
    AUDIT_LOGS_FILE,
    DOCUMENTS_FILE,
    NOTIFICATIONS_FILE,
]


# ── Per-file threading locks ──────────────────────────────────────────────────
_LOCKS: dict[str, threading.Lock] = {
    path: threading.Lock() for path in ALL_DATA_FILES
}


def _lock_for(path: str) -> threading.Lock:
    if path not in _LOCKS:
        _LOCKS[path] = threading.Lock()
    return _LOCKS[path]


# ── Data directory bootstrap ──────────────────────────────────────────────────
def _write_json_bare(path: str, data) -> None:
    """Minimal writer used only during bootstrap (no lock, no backup)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def ensure_data_directory() -> None:
    """Creates the data/ directory and all empty JSON files if missing."""
    data_dir = getattr(config, "DATA_DIR", "data")
    os.makedirs(data_dir, exist_ok=True)

    list_files = [
        USERS_FILE, MEMBERS_FILE, SERVICES_FILE,
        ACTIVE_REQUESTS_FILE, ARCHIVED_REQUESTS_FILE,
        INVOICES_FILE, AUDIT_LOGS_FILE,
        DOCUMENTS_FILE, NOTIFICATIONS_FILE,
    ]
    dict_files = [INVOICE_SEQUENCE_FILE]

    for path in list_files:
        if not os.path.exists(path):
            _write_json_bare(path, [])
    for path in dict_files:
        if not os.path.exists(path):
            _write_json_bare(path, {"next": 1, "prefix": "PLGN"})


ensure_data_directory()


# ── Low-level JSON I/O ────────────────────────────────────────────────────────
def _read_json(path: str) -> Any:
    lock = _lock_for(path)
    with lock:
        try:
            if not os.path.exists(path):
                default = {} if path == INVOICE_SEQUENCE_FILE else []
                _write_json_unsafe(path, default)
                return default
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {} if path == INVOICE_SEQUENCE_FILE else []
                return json.loads(content)
        except (json.JSONDecodeError, OSError):
            backup = path + ".bak"
            if os.path.exists(backup):
                try:
                    with open(backup, "r", encoding="utf-8") as bf:
                        return json.loads(bf.read())
                except Exception:
                    pass
            return {} if path == INVOICE_SEQUENCE_FILE else []


def _write_json_unsafe(path: str, data: Any) -> None:
    """Writes JSON without acquiring lock (caller must hold lock)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _write_json(path: str, data: Any) -> None:
    lock = _lock_for(path)
    with lock:
        _write_json_unsafe(path, data)


# ── Generic list-file helpers ─────────────────────────────────────────────────
def _get_all(path: str) -> list:
    data = _read_json(path)
    return data if isinstance(data, list) else []


def _get_by_id(path: str, record_id: str) -> Optional[dict]:
    for record in _get_all(path):
        if record.get("id") == record_id:
            return record
    return None


def _save_record(path: str, record: dict) -> None:
    if "id" not in record:
        record["id"] = str(uuid.uuid4())
    record.setdefault("updated_at", datetime.utcnow().isoformat())

    lock = _lock_for(path)
    with lock:
        data = _read_json(path)
        if not isinstance(data, list):
            data = []
        found = False
        for i, existing in enumerate(data):
            if existing.get("id") == record["id"]:
                data[i] = record
                found   = True
                break
        if not found:
            data.append(record)
        _write_json_unsafe(path, data)


def _delete_record(path: str, record_id: str) -> bool:
    lock = _lock_for(path)
    with lock:
        data = _read_json(path)
        if not isinstance(data, list):
            return False
        original_len = len(data)
        data = [r for r in data if r.get("id") != record_id]
        if len(data) == original_len:
            return False
        _write_json_unsafe(path, data)
        return True


# ══════════════════════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════════════════════

def get_all_users() -> list:
    return _get_all(USERS_FILE)


def get_user(user_id: str) -> Optional[dict]:
    return _get_by_id(USERS_FILE, user_id)


def get_user_by_username(username: str) -> Optional[dict]:
    for u in get_all_users():
        if u.get("username") == username:
            return u
    return None


def get_user_by_email(email: str) -> Optional[dict]:
    email_lower = email.lower().strip()
    for u in get_all_users():
        if (u.get("email") or "").lower().strip() == email_lower:
            return u
    return None


def save_user(user: dict) -> None:
    _save_record(USERS_FILE, user)


def delete_user(user_id: str) -> bool:
    return _delete_record(USERS_FILE, user_id)


def get_active_users() -> list:
    return [u for u in get_all_users() if u.get("active", True)]


def get_users_by_role(role: str) -> list:
    return [u for u in get_all_users() if u.get("role") == role]


def update_user_password(user_id: str, new_password_hash: str) -> bool:
    """
    Updates the password_hash for a given user_id.
    Also stamps password_changed_at for audit trail.
    Returns True on success, False if user not found.
    """
    user = get_user(user_id)
    if not user:
        return False
    user["password_hash"]       = new_password_hash
    user["password_changed_at"] = datetime.utcnow().isoformat()
    user["updated_at"]          = datetime.utcnow().isoformat()
    save_user(user)
    return True


def update_user_last_login(user_id: str) -> bool:
    """
    Stamps last_login_at for a given user_id.
    Returns True on success, False if user not found.
    """
    user = get_user(user_id)
    if not user:
        return False
    user["last_login_at"] = datetime.utcnow().isoformat()
    user["updated_at"]    = datetime.utcnow().isoformat()
    save_user(user)
    return True


def toggle_user_active(user_id: str) -> Optional[bool]:
    """
    Toggles the active flag for a user.
    Returns the new active state, or None if user not found.
    """
    user = get_user(user_id)
    if not user:
        return None
    user["active"]     = not user.get("active", True)
    user["updated_at"] = datetime.utcnow().isoformat()
    save_user(user)
    return user["active"]


# ══════════════════════════════════════════════════════════════════════════════
# MEMBERS (analystes)
# ══════════════════════════════════════════════════════════════════════════════

def get_all_members() -> list:
    return _get_all(MEMBERS_FILE)


def get_member(member_id: str) -> Optional[dict]:
    return _get_by_id(MEMBERS_FILE, member_id)


def get_member_by_user_id(user_id: str) -> Optional[dict]:
    for m in get_all_members():
        if m.get("user_id") == user_id:
            return m
    return None


def save_member(member: dict) -> None:
    _save_record(MEMBERS_FILE, member)


def delete_member(member_id: str) -> bool:
    return _delete_record(MEMBERS_FILE, member_id)


def get_available_members() -> list:
    return [
        m for m in get_all_members()
        if m.get("available", True)
        and int(m.get("current_load", 0)) < int(m.get("max_load", 5))
    ]


def get_available_members_for_service(service_id: str) -> list:
    available = get_available_members()
    skilled   = [
        m for m in available
        if float(m.get("skills", {}).get(service_id, 0)) > 0
    ]
    return skilled if skilled else available


def increment_member_load(member_id: str) -> None:
    m = get_member(member_id)
    if m:
        m["current_load"] = int(m.get("current_load", 0)) + 1
        save_member(m)


def decrement_member_load(member_id: str) -> None:
    m = get_member(member_id)
    if m:
        m["current_load"] = max(0, int(m.get("current_load", 0)) - 1)
        save_member(m)


# ══════════════════════════════════════════════════════════════════════════════
# SERVICES
# ══════════════════════════════════════════════════════════════════════════════

def get_all_services() -> list:
    return _get_all(SERVICES_FILE)


def get_service(service_id: str) -> Optional[dict]:
    return _get_by_id(SERVICES_FILE, service_id)


def get_active_services() -> list:
    return [s for s in get_all_services() if s.get("active", True)]


def get_services_by_channel(channel: str) -> list:
    return [
        s for s in get_all_services()
        if s.get("channel") == channel and s.get("active", True)
    ]


def save_service(service: dict) -> None:
    _save_record(SERVICES_FILE, service)


def delete_service(service_id: str) -> bool:
    return _delete_record(SERVICES_FILE, service_id)


# ══════════════════════════════════════════════════════════════════════════════
# REQUESTS — Active
# ══════════════════════════════════════════════════════════════════════════════

def get_all_active_requests() -> list:
    return _get_all(ACTIVE_REQUESTS_FILE)


def get_request(request_id: str) -> Optional[dict]:
    req = _get_by_id(ACTIVE_REQUESTS_FILE, request_id)
    if req is None:
        req = _get_by_id(ARCHIVED_REQUESTS_FILE, request_id)
    return req


def get_request_active(request_id: str) -> Optional[dict]:
    return _get_by_id(ACTIVE_REQUESTS_FILE, request_id)


def save_request(request: dict) -> None:
    rid     = request.get("id")
    in_arch = rid and (_get_by_id(ARCHIVED_REQUESTS_FILE, rid) is not None)
    if in_arch:
        _save_record(ARCHIVED_REQUESTS_FILE, request)
    else:
        _save_record(ACTIVE_REQUESTS_FILE, request)


def create_request(request: dict) -> dict:
    request.setdefault("id",             str(uuid.uuid4()))
    request.setdefault("created_at",     datetime.utcnow().isoformat())
    request.setdefault("updated_at",     datetime.utcnow().isoformat())
    request.setdefault("status_history", [])
    _save_record(ACTIVE_REQUESTS_FILE, request)
    return request


def delete_active_request(request_id: str) -> bool:
    return _delete_record(ACTIVE_REQUESTS_FILE, request_id)


def get_requests_by_status(status: str) -> list:
    return [r for r in get_all_active_requests() if r.get("status") == status]


def get_requests_by_channel(channel: str) -> list:
    return [r for r in get_all_active_requests() if r.get("channel") == channel]


def get_requests_by_member(member_id: str) -> list:
    return [
        r for r in get_all_active_requests()
        if r.get("assigned_member_id") == member_id
    ]


def get_requests_by_user(user_id: str) -> list:
    return [
        r for r in get_all_active_requests()
        if r.get("submitted_by_user_id") == user_id
    ]


def get_requests_by_organization(org_id: str) -> list:
    return [
        r for r in get_all_active_requests()
        if r.get("organization_id") == org_id
        or r.get("form_data", {}).get("requester", {}).get("organization_id") == org_id
    ]


# ══════════════════════════════════════════════════════════════════════════════
# REQUESTS — Archived
# ══════════════════════════════════════════════════════════════════════════════

def get_all_archived_requests() -> list:
    return _get_all(ARCHIVED_REQUESTS_FILE)


def archive_request(request_id: str) -> bool:
    req = get_request_active(request_id)
    if not req:
        return False
    req["archived_at"] = datetime.utcnow().isoformat()
    req["updated_at"]  = datetime.utcnow().isoformat()
    _save_record(ARCHIVED_REQUESTS_FILE, req)
    _delete_record(ACTIVE_REQUESTS_FILE, request_id)
    return True


def unarchive_request(request_id: str) -> bool:
    req = _get_by_id(ARCHIVED_REQUESTS_FILE, request_id)
    if not req:
        return False
    req.pop("archived_at", None)
    req["updated_at"] = datetime.utcnow().isoformat()
    _save_record(ACTIVE_REQUESTS_FILE, req)
    _delete_record(ARCHIVED_REQUESTS_FILE, request_id)
    return True


# ══════════════════════════════════════════════════════════════════════════════
# INVOICES
# ══════════════════════════════════════════════════════════════════════════════

def get_all_invoices() -> list:
    return _get_all(INVOICES_FILE)


def get_invoice(invoice_id: str) -> Optional[dict]:
    return _get_by_id(INVOICES_FILE, invoice_id)


def get_invoice_by_request_id(request_id: str) -> Optional[dict]:
    for inv in get_all_invoices():
        if inv.get("request_id") == request_id:
            return inv
    return None


def get_invoices_by_status(paid: bool) -> list:
    return [i for i in get_all_invoices() if bool(i.get("paid", False)) == paid]


def save_invoice(invoice: dict) -> None:
    _save_record(INVOICES_FILE, invoice)


def delete_invoice(invoice_id: str) -> bool:
    return _delete_record(INVOICES_FILE, invoice_id)


def next_invoice_number() -> str:
    lock = _lock_for(INVOICE_SEQUENCE_FILE)
    with lock:
        seq_data = _read_json(INVOICE_SEQUENCE_FILE)
        if not isinstance(seq_data, dict):
            seq_data = {"next": 1, "prefix": "PLGN"}
        prefix  = seq_data.get("prefix", "PLGN")
        year    = datetime.utcnow().year
        counter = int(seq_data.get("next", 1))
        number  = f"{prefix}-{year}-{counter:05d}"
        seq_data["next"]              = counter + 1
        seq_data["last"]              = number
        seq_data["last_generated_at"] = datetime.utcnow().isoformat()
        _write_json_unsafe(INVOICE_SEQUENCE_FILE, seq_data)
        return number


def peek_next_invoice_number() -> str:
    seq_data = _read_json(INVOICE_SEQUENCE_FILE)
    if not isinstance(seq_data, dict):
        seq_data = {"next": 1, "prefix": "PLGN"}
    prefix  = seq_data.get("prefix", "PLGN")
    year    = datetime.utcnow().year
    counter = int(seq_data.get("next", 1))
    return f"{prefix}-{year}-{counter:05d}"


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTS
# ══════════════════════════════════════════════════════════════════════════════

def get_all_documents() -> list:
    return _get_all(DOCUMENTS_FILE)


def get_document(doc_id: str) -> Optional[dict]:
    return _get_by_id(DOCUMENTS_FILE, doc_id)


def get_documents_for_request(request_id: str) -> list:
    return [d for d in get_all_documents() if d.get("request_id") == request_id]


def get_documents_by_type(doc_type: str) -> list:
    return [d for d in get_all_documents() if d.get("type") == doc_type]


def save_document(document: dict) -> None:
    _save_record(DOCUMENTS_FILE, document)


def delete_document(doc_id: str) -> bool:
    return _delete_record(DOCUMENTS_FILE, doc_id)


def create_document_record(
    request_id: str,
    filename:   str,
    path:       str,
    doc_type:   str = "REPORT",
    created_by: str = "system",
    size_kb:    Optional[float] = None,
) -> dict:
    size = size_kb
    if size is None and os.path.exists(path):
        size = round(os.path.getsize(path) / 1024, 1)
    doc = {
        "id":         str(uuid.uuid4()),
        "request_id": request_id,
        "filename":   filename,
        "path":       path,
        "type":       doc_type,
        "size_kb":    size,
        "created_at": datetime.utcnow().isoformat(),
        "created_by": created_by,
    }
    save_document(doc)
    return doc


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_all_notifications() -> list:
    return _get_all(NOTIFICATIONS_FILE)


def get_notification(notif_id: str) -> Optional[dict]:
    return _get_by_id(NOTIFICATIONS_FILE, notif_id)


def get_notifications_for_user_id(user_id: str) -> list:
    if not user_id:
        return []
    return [n for n in get_all_notifications() if n.get("user_id") == user_id]


def get_notifications_for_role(role: str) -> list:
    if not role:
        return []
    return [n for n in get_all_notifications() if n.get("role") == role]


def get_unread_notifications_for_user(user_id: str) -> list:
    user  = get_user(user_id) or {}
    role  = user.get("role", "")
    all_n = get_notifications_for_user_id(user_id) + get_notifications_for_role(role)
    seen:   set  = set()
    unique: list = []
    for n in all_n:
        nid = n.get("id", "")
        if nid and nid not in seen:
            seen.add(nid)
            unique.append(n)
    return [n for n in unique if not n.get("read", False)]


def save_notification(notification: dict) -> None:
    _save_record(NOTIFICATIONS_FILE, notification)


def create_notification(
    title:   str,
    message: str,
    level:   str = "info",
    user_id: Optional[str] = None,
    role:    Optional[str] = None,
) -> dict:
    notif = {
        "id":         str(uuid.uuid4()),
        "title":      title,
        "message":    message,
        "level":      level,
        "user_id":    user_id,
        "role":       role,
        "read":       False,
        "created_at": datetime.utcnow().isoformat(),
    }
    save_notification(notif)
    return notif


def mark_notification_read(notif_id: str) -> bool:
    notif = get_notification(notif_id)
    if not notif:
        return False
    notif["read"]    = True
    notif["read_at"] = datetime.utcnow().isoformat()
    save_notification(notif)
    return True


def mark_all_notifications_read_for_user(user_id: str) -> int:
    user  = get_user(user_id) or {}
    role  = user.get("role", "")
    notifs = (
        get_notifications_for_user_id(user_id) +
        get_notifications_for_role(role)
    )
    count = 0
    for n in notifs:
        if not n.get("read", False):
            mark_notification_read(n["id"])
            count += 1
    return count


def delete_notification(notif_id: str) -> bool:
    return _delete_record(NOTIFICATIONS_FILE, notif_id)

# ── Alias — used by requester/member dashboards ───────────────────────────────
def get_all_notifications_for_user(user_id: str) -> list:
    """
    Returns ALL notifications for a user (direct + role-based), deduplicated.
    Alias combining get_notifications_for_user_id + get_notifications_for_role.
    """
    user  = get_user(user_id) or {}
    role  = user.get("role", "")
    all_n = get_notifications_for_user_id(user_id) + get_notifications_for_role(role)
    seen:   set  = set()
    unique: list = []
    for n in all_n:
        nid = n.get("id", "")
        if nid and nid not in seen:
            seen.add(nid)
            unique.append(n)
    return unique

# ══════════════════════════════════════════════════════════════════════════════
# AUDIT LOGS
# ══════════════════════════════════════════════════════════════════════════════

def get_all_audit_logs() -> list:
    return _get_all(AUDIT_LOGS_FILE)


def get_audit_logs_for_entity(entity_type: str, entity_id: str) -> list:
    return [
        l for l in get_all_audit_logs()
        if l.get("entity_type") == entity_type
        and str(l.get("entity_id", "")) == entity_id
    ]


def get_audit_logs_for_user(user_id: str) -> list:
    return [l for l in get_all_audit_logs() if l.get("user_id") == user_id]


def get_audit_logs_by_action(action: str) -> list:
    action_upper = action.upper()
    return [
        l for l in get_all_audit_logs()
        if action_upper in l.get("action", "").upper()
    ]


def append_audit_log(entry: dict) -> None:
    entry.setdefault("id",        str(uuid.uuid4()))
    entry.setdefault("timestamp", datetime.utcnow().isoformat())
    lock = _lock_for(AUDIT_LOGS_FILE)
    with lock:
        data = _read_json(AUDIT_LOGS_FILE)
        if not isinstance(data, list):
            data = []
        data.append(entry)
        _write_json_unsafe(AUDIT_LOGS_FILE, data)


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-ENTITY QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def get_full_request_context(request_id: str) -> dict:
    req = get_request(request_id)
    if not req:
        return {}
    return {
        "request":       req,
        "invoice":       get_invoice_by_request_id(request_id),
        "documents":     get_documents_for_request(request_id),
        "member":        get_member(req.get("assigned_member_id", "")),
        "service":       get_service(req.get("service_id", "")),
        "notifications": [
            n for n in get_all_notifications()
            if n.get("request_id") == request_id
        ],
        "audit_logs":    get_audit_logs_for_entity("REQUEST", request_id),
    }

# ── Alias — used by requester/member dashboards ───────────────────────────────
def get_all_documents_for_request(request_id: str) -> list:
    """Alias for get_documents_for_request — used by dashboards."""
    return get_documents_for_request(request_id)


def get_platform_stats() -> dict:
    active_reqs   = get_all_active_requests()
    archived      = get_all_archived_requests()
    invoices      = get_all_invoices()
    members       = get_all_members()
    users         = get_all_users()
    notifications = get_all_notifications()

    paid_invoices = [i for i in invoices if i.get("paid")]
    total_revenue = sum(float(i.get("total_ttc", 0)) for i in paid_invoices)

    return {
        "users_total":          len(users),
        "users_active":         sum(1 for u in users if u.get("active", True)),
        "members_total":        len(members),
        "members_available":    sum(1 for m in members if m.get("available", True)),
        "requests_active":      len(active_reqs),
        "requests_archived":    len(archived),
        "invoices_total":       len(invoices),
        "invoices_paid":        len(paid_invoices),
        "invoices_unpaid":      len(invoices) - len(paid_invoices),
        "revenue_encaisse":     total_revenue,
        "notifications_unread": sum(1 for n in notifications if not n.get("read", False)),
    }


def get_member_workload_summary() -> list[dict]:
    summary = []
    for m in get_all_members():
        cur  = int(m.get("current_load", 0))
        maxi = int(m.get("max_load", 5))
        pct  = (cur / maxi * 100) if maxi > 0 else 0.0
        summary.append({
            "id":                 m.get("id", ""),
            "name":               m.get("name", "–"),
            "current_load":       cur,
            "max_load":           maxi,
            "load_pct":           round(pct, 1),
            "available":          m.get("available", True),
            "productivity_score": float(m.get("productivity_score", 50)),
            "productivity_label": m.get("productivity_label", "NORMAL"),
        })
    return sorted(summary, key=lambda x: x["load_pct"])


# ══════════════════════════════════════════════════════════════════════════════
# DATA INTEGRITY UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def verify_data_integrity() -> dict[str, Any]:
    checks  = {}
    file_map = {
        "users":             USERS_FILE,
        "members":           MEMBERS_FILE,
        "services":          SERVICES_FILE,
        "active_requests":   ACTIVE_REQUESTS_FILE,
        "archived_requests": ARCHIVED_REQUESTS_FILE,
        "invoices":          INVOICES_FILE,
        "documents":         DOCUMENTS_FILE,
        "notifications":     NOTIFICATIONS_FILE,
        "audit_logs":        AUDIT_LOGS_FILE,
    }
    for label, path in file_map.items():
        try:
            data  = _get_all(path)
            ids   = [r.get("id") for r in data]
            dupes = len(ids) - len(set(ids))
            checks[label] = {"ok": True,  "count": len(data), "dupes": dupes, "path": path, "error": None}
        except Exception as e:
            checks[label] = {"ok": False, "count": 0,         "dupes": 0,     "path": path, "error": str(e)}
    return checks


def deduplicate_file(path: str) -> int:
    lock = _lock_for(path)
    with lock:
        data = _read_json(path)
        if not isinstance(data, list):
            return 0
        seen:   set  = set()
        unique: list = []
        for r in data:
            rid = r.get("id", "")
            if rid not in seen:
                seen.add(rid)
                unique.append(r)
        removed = len(data) - len(unique)
        if removed > 0:
            _write_json_unsafe(path, unique)
        return removed


def create_full_backup(backup_dir: str = "data/backups") -> str:
    ts         = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(backup_dir, ts)
    os.makedirs(target_dir, exist_ok=True)
    for path in ALL_DATA_FILES:
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(target_dir, os.path.basename(path)))
    return target_dir


def restore_from_backup(backup_dir: str) -> list[str]:
    restored = []
    for path in ALL_DATA_FILES:
        src = os.path.join(backup_dir, os.path.basename(path))
        if os.path.exists(src):
            shutil.copy2(src, path)
            restored.append(os.path.basename(path))
    return restored
