import sys
import os
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.repository import (
    get_active_request_by_id,
    save_active_request,
    get_all_active_requests,
    get_member_by_id,
    save_member,
)
from core.audit_engine import log_event
from core.exceptions import EntityNotFoundError


def add_task(
    request_id: str,
    title: str,
    assigned_to: str,
    user: dict,
) -> dict:
    request = get_active_request_by_id(request_id)
    task = {
        "id":           str(uuid.uuid4()),
        "request_id":   request_id,
        "title":        title,
        "assigned_to":  assigned_to,
        "status":       "OPEN",
        "created_at":   datetime.utcnow().isoformat(),
        "completed_at": None,
        "notes":        "",
    }
    request.setdefault("tasks", []).append(task)
    save_active_request(request)
    log_event("TASK", task["id"], "TASK_CREATED", user["id"],
              {"title": title, "assigned_to": assigned_to})
    return task


def complete_task(
    request_id: str,
    task_id: str,
    user: dict,
) -> dict:
    request = get_active_request_by_id(request_id)
    for t in request.get("tasks", []):
        if t["id"] == task_id:
            t["status"]       = "COMPLETED"
            t["completed_at"] = datetime.utcnow().isoformat()
            save_active_request(request)
            # ERR-03 FIX: decrement member load on task completion
            mid = t.get("assigned_to")
            if mid:
                try:
                    m = get_member_by_id(mid)
                    m["current_load"] = max(0, int(m.get("current_load", 0)) - 1)
                    save_member(m)
                except Exception:
                    pass
            log_event("TASK", task_id, "TASK_COMPLETED", user["id"], {})
            return t
    raise EntityNotFoundError(
        f"Task {task_id} not found in request {request_id}."
    )


def get_tasks(request_id: str) -> list:
    return get_active_request_by_id(request_id).get("tasks", [])


def get_tasks_by_member(member_id: str) -> list:
    tasks = []
    for req in get_all_active_requests():
        for t in req.get("tasks", []):
            if t.get("assigned_to") == member_id:
                tasks.append(t)
    return tasks
