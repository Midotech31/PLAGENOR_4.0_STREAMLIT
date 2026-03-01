from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


def _now() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    role: str
    organization_id: Optional[str] = None
    active: bool = True


@dataclass
class Member:
    id: str
    user_id: str
    name: str
    skills: Dict[str, float] = field(default_factory=dict)
    current_load: int = 0
    max_load: int = 5
    available: bool = True
    productivity_score: float = 50.0


@dataclass
class Service:
    id: str
    name: str
    channel: str
    description: str
    base_price: float = 0.0
    active: bool = True


@dataclass
class Sample:
    id: str
    request_id: str
    label: str
    type: str
    status: str = "PENDING"
    received_at: Optional[str] = None
    notes: str = ""


@dataclass
class Task:
    id: str
    request_id: str
    title: str
    assigned_to: Optional[str] = None
    status: str = "OPEN"
    created_at: str = field(default_factory=_now)
    completed_at: Optional[str] = None
    notes: str = ""


@dataclass
class Request:
    id: str
    channel: str
    service_id: str
    requester_id: str
    organization_id: str
    status: str
    estimated_budget: float = 0.0
    approved_budget: float = 0.0
    override_justification: Optional[str] = None
    samples: List[Dict[str, Any]] = field(default_factory=list)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    archived: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class Invoice:
    invoice_number: int
    request_id: str
    amount: float
    locked: bool = True
    generated_at: str = field(default_factory=_now)


@dataclass
class AuditLog:
    timestamp: str
    entity_type: str
    entity_id: str
    action: str
    user_id: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentRecord:
    id: str
    request_id: str
    doc_type: str
    channel: str
    filename: str
    filepath: str
    sha256: str
    locked: bool = False
    generated_at: str = field(default_factory=_now)