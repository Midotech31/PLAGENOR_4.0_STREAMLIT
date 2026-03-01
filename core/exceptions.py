# core/exceptions.py
# ── PLAGENOR 4.0 — Custom Exceptions ─────────────────────────────────────────
# All platform-specific exceptions in one place.
# Catch PlagenorError as the base for any expected platform error.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations


# ── Base ──────────────────────────────────────────────────────────────────────
class PlagenorError(Exception):
    """Base class for all PLAGENOR platform errors."""
    def __init__(self, message: str, code: str = "PLAGENOR_ERROR"):
        super().__init__(message)
        self.message = message
        self.code    = code

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# ── Auth ──────────────────────────────────────────────────────────────────────
class AuthenticationError(PlagenorError):
    """Invalid credentials or session expired."""
    def __init__(self, message: str = "Authentification échouée."):
        super().__init__(message, "AUTH_ERROR")


class AuthorizationError(PlagenorError):
    """User does not have permission for the requested action."""
    def __init__(self, message: str = "Accès refusé — droits insuffisants."):
        super().__init__(message, "AUTHZ_ERROR")


class AccountDisabledError(PlagenorError):
    """User account is inactive / disabled."""
    def __init__(self, message: str = "Compte désactivé."):
        super().__init__(message, "ACCOUNT_DISABLED")


# ── Workflow ──────────────────────────────────────────────────────────────────
class WorkflowError(PlagenorError):
    """Generic workflow engine error."""
    def __init__(self, message: str, code: str = "WORKFLOW_ERROR"):
        super().__init__(message, code)


class InvalidTransitionError(WorkflowError):
    """Attempted state transition is not allowed."""
    def __init__(
        self,
        from_state: str,
        to_state:   str,
        reason:     str = "",
    ):
        msg = (
            f"Transition interdite: `{from_state}` → `{to_state}`"
            + (f" — {reason}" if reason else "")
        )
        super().__init__(msg, "INVALID_TRANSITION")
        self.from_state = from_state
        self.to_state   = to_state


class RequestNotFoundError(WorkflowError):
    """Request ID not found in active or archived pools."""
    def __init__(self, request_id: str):
        super().__init__(
            f"Demande introuvable: `{request_id}`",
            "REQUEST_NOT_FOUND",
        )
        self.request_id = request_id


class RequestAlreadyArchivedError(WorkflowError):
    """Action attempted on an already archived request."""
    def __init__(self, request_id: str):
        super().__init__(
            f"La demande `{request_id}` est déjà archivée.",
            "REQUEST_ARCHIVED",
        )


class MissingTransitionDataError(WorkflowError):
    """A required field is missing for this transition."""
    def __init__(self, field: str, transition: str):
        super().__init__(
            f"Champ obligatoire manquant `{field}` pour la transition `{transition}`.",
            "MISSING_TRANSITION_DATA",
        )
        self.field      = field
        self.transition = transition


# ── Assignment ────────────────────────────────────────────────────────────────
class AssignmentError(PlagenorError):
    """Error during member assignment."""
    def __init__(self, message: str, code: str = "ASSIGNMENT_ERROR"):
        super().__init__(message, code)


class NoAvailableMemberError(AssignmentError):
    """No member available for the requested service."""
    def __init__(self, service_name: str = ""):
        msg = (
            f"Aucun analyste disponible"
            + (f" pour le service '{service_name}'" if service_name else "")
            + "."
        )
        super().__init__(msg, "NO_AVAILABLE_MEMBER")


class MemberOverloadedError(AssignmentError):
    """Member cannot accept more requests (at max_load)."""
    def __init__(self, member_name: str):
        super().__init__(
            f"L'analyste '{member_name}' a atteint sa charge maximale.",
            "MEMBER_OVERLOADED",
        )


class MemberUnavailableError(AssignmentError):
    """Member is explicitly set to unavailable."""
    def __init__(self, member_name: str):
        super().__init__(
            f"L'analyste '{member_name}' est indisponible.",
            "MEMBER_UNAVAILABLE",
        )


# ── Financial ─────────────────────────────────────────────────────────────────
class FinancialError(PlagenorError):
    """Generic financial engine error."""
    def __init__(self, message: str, code: str = "FINANCIAL_ERROR"):
        super().__init__(message, code)


class InvoiceAlreadyExistsError(FinancialError):
    """An invoice already exists for this request."""
    def __init__(self, request_id: str):
        super().__init__(
            f"Une facture existe déjà pour la demande `{request_id}`.",
            "INVOICE_EXISTS",
        )


class InvoiceNotFoundError(FinancialError):
    """Invoice not found."""
    def __init__(self, invoice_id: str):
        super().__init__(
            f"Facture introuvable: `{invoice_id}`.",
            "INVOICE_NOT_FOUND",
        )


class InvalidQuoteAmountError(FinancialError):
    """Quote amount is invalid (zero, negative, or non-numeric)."""
    def __init__(self, amount: float):
        super().__init__(
            f"Montant de devis invalide: {amount}.",
            "INVALID_QUOTE_AMOUNT",
        )


class BudgetExceededError(FinancialError):
    """Requested budget exceeds the platform cap."""
    def __init__(self, requested: float, cap: float):
        super().__init__(
            f"Budget demandé ({requested:,.0f} DZD) "
            f"dépasse le plafond autorisé ({cap:,.0f} DZD).",
            "BUDGET_EXCEEDED",
        )
        self.requested = requested
        self.cap       = cap


# ── Data / Repository ─────────────────────────────────────────────────────────
class RepositoryError(PlagenorError):
    """Generic data layer error."""
    def __init__(self, message: str, code: str = "REPOSITORY_ERROR"):
        super().__init__(message, code)


class RecordNotFoundError(RepositoryError):
    """Generic record not found."""
    def __init__(self, record_type: str, record_id: str):
        super().__init__(
            f"{record_type} introuvable: `{record_id}`.",
            "RECORD_NOT_FOUND",
        )


class DuplicateRecordError(RepositoryError):
    """A record with the same unique key already exists."""
    def __init__(self, record_type: str, key: str):
        super().__init__(
            f"{record_type} en doublon: `{key}`.",
            "DUPLICATE_RECORD",
        )


class DataIntegrityError(RepositoryError):
    """Data file is corrupted or in an inconsistent state."""
    def __init__(self, path: str, detail: str = ""):
        super().__init__(
            f"Intégrité des données compromise: `{path}`"
            + (f" — {detail}" if detail else ""),
            "DATA_INTEGRITY_ERROR",
        )


# ── Document / File ───────────────────────────────────────────────────────────
class DocumentError(PlagenorError):
    """Generic document / file error."""
    def __init__(self, message: str, code: str = "DOCUMENT_ERROR"):
        super().__init__(message, code)


class DocumentNotFoundError(DocumentError):
    """Document file not found on disk."""
    def __init__(self, path: str):
        super().__init__(
            f"Fichier document introuvable: `{path}`.",
            "DOCUMENT_NOT_FOUND",
        )


class DocumentGenerationError(DocumentError):
    """Error during document (report/invoice) generation."""
    def __init__(self, detail: str = ""):
        super().__init__(
            "Erreur lors de la génération du document"
            + (f": {detail}" if detail else "."),
            "DOCUMENT_GENERATION_ERROR",
        )


# ── Notification ──────────────────────────────────────────────────────────────
class NotificationError(PlagenorError):
    """Generic notification error."""
    def __init__(self, message: str):
        super().__init__(message, "NOTIFICATION_ERROR")


# ── Productivity ──────────────────────────────────────────────────────────────
class ProductivityError(PlagenorError):
    """Error in the productivity scoring engine."""
    def __init__(self, message: str):
        super().__init__(message, "PRODUCTIVITY_ERROR")


# ── Config ────────────────────────────────────────────────────────────────────
class ConfigurationError(PlagenorError):
    """Missing or invalid platform configuration."""
    def __init__(self, key: str):
        super().__init__(
            f"Paramètre de configuration manquant ou invalide: `{key}`.",
            "CONFIG_ERROR",
        )