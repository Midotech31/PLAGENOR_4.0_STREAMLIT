import sys
import os
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.repository import get_active_request_by_id, save_active_request
from core.audit_engine import log_event
from core.exceptions import EntityNotFoundError


def add_sample(
    request_id: str,
    label: str,
    sample_type: str,
    user: dict,
) -> dict:
    request = get_active_request_by_id(request_id)
    sample = {
        "id":          str(uuid.uuid4()),
        "request_id":  request_id,
        "label":       label,
        "type":        sample_type,
        "status":      "PENDING",
        "received_at": None,
        "notes":       "",
    }
    request.setdefault("samples", []).append(sample)
    save_active_request(request)
    log_event("SAMPLE", sample["id"], "SAMPLE_ADDED", user["id"],
              {"label": label, "type": sample_type})
    return sample


def mark_sample_received(
    request_id: str,
    sample_id: str,
    user: dict,
) -> dict:
    request = get_active_request_by_id(request_id)
    for s in request.get("samples", []):
        if s["id"] == sample_id:
            s["status"]      = "RECEIVED"
            s["received_at"] = datetime.utcnow().isoformat()
            save_active_request(request)
            log_event("SAMPLE", sample_id, "SAMPLE_RECEIVED", user["id"], {})
            return s
    raise EntityNotFoundError(
        f"Sample {sample_id} not found in request {request_id}."
    )


def get_samples(request_id: str) -> list:
    return get_active_request_by_id(request_id).get("samples", [])
