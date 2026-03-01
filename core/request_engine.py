import sys
import os
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from core.repository import (
    save_active_request,
    get_active_request_by_id,
    get_all_active_requests,
)
from core.audit_engine import log_event


def create_request(
    channel: str,
    service_id: str,
    requester_id: str,
    organization_id: str,
    estimated_budget: float,
    user: dict,
) -> dict:
    if channel not in (config.CHANNEL_IBTIKAR, config.CHANNEL_GENOCLAB):
        raise ValueError(f"Invalid channel: {channel}")
    request = {
        "id":                    str(uuid.uuid4()),
        "channel":               channel,
        "service_id":            service_id,
        "requester_id":          requester_id,
        "organization_id":       organization_id or user.get("organization_id", "UNKNOWN"),
        "status":                "SUBMITTED",
        "estimated_budget":      float(estimated_budget),
        "approved_budget":       float(estimated_budget),
        "override_justification": None,
        "samples":               [],
        "tasks":                 [],
        "archived":              False,
        "created_at":            datetime.utcnow().isoformat(),
        "updated_at":            datetime.utcnow().isoformat(),
    }
    save_active_request(request)
    log_event("REQUEST", request["id"], "REQUEST_CREATED", user["id"], {
        "channel":          channel,
        "service_id":       service_id,
        "estimated_budget": estimated_budget,
    })
    return request


def update_request_budget(
    request_id: str,
    new_budget: float,
    user: dict,
) -> dict:
    request = get_active_request_by_id(request_id)
    old_budget = request.get("approved_budget", 0.0)
    request["approved_budget"] = float(new_budget)
    request["updated_at"]      = datetime.utcnow().isoformat()
    save_active_request(request)
    log_event("REQUEST", request_id, "BUDGET_UPDATED", user["id"],
              {"old_budget": old_budget, "new_budget": new_budget})
    return request


def get_requests_by_requester(requester_id: str) -> list:
    return [r for r in get_all_active_requests()
            if r.get("requester_id") == requester_id]


def get_requests_by_channel(channel: str) -> list:
    return [r for r in get_all_active_requests()
            if r.get("channel") == channel]
