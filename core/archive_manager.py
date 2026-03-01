import sys
import os
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from core.repository import (
    get_active_request_by_id,
    delete_active_request,
    save_archived_request,
    get_documents_by_request_id,
    save_document,
)
from core.audit_engine import log_event
from core.exceptions import InvalidTransitionError


def archive(request_id: str, user: dict) -> dict:
    request = get_active_request_by_id(request_id)
    if request["status"] != "COMPLETED":
        raise InvalidTransitionError(
            f"Request must be COMPLETED before archiving. "
            f"Current status: {request['status']}."
        )

    request["archived"]    = True
    request["status"]      = "ARCHIVED"
    request["updated_at"]  = datetime.utcnow().isoformat()

    # ERR-07 FIX: move documents (not copy) to archived/
    docs = get_documents_by_request_id(request_id)
    dest_dir = os.path.join(config.DOCUMENTS_DIR, "archived")
    os.makedirs(dest_dir, exist_ok=True)

    for doc in docs:
        src = doc.get("filepath", "")
        if os.path.isfile(src):
            dest = os.path.join(dest_dir, os.path.basename(src))
            shutil.move(src, dest)
            doc["filepath"] = dest
            save_document(doc)

    save_archived_request(request)
    delete_active_request(request_id)

    log_event("REQUEST", request_id, "REQUEST_ARCHIVED", user["id"],
              {"documents_moved": len(docs)})
    return request
