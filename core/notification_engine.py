"""
PLAGENOR 4.0 — Notification Engine
Handles in-app and email notification dispatch triggered by workflow transitions.

RESPONSIBILITIES:
- Route notifications to correct roles/users
- Store in-app notifications in repository
- Send email notifications (SMTP or fallback to log)
- Never block workflow transitions on failure

NON-NEGOTIABLE:
- Notification failures must NEVER raise exceptions to the caller.
- All notification events are logged via audit_engine.
- No business logic here — only routing and delivery.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from typing import List
import uuid
import config
from core.audit_engine import log_event


# ── Status → human-readable French label ─────────────────────────────────────
_STATE_LABELS = {
    # IBTIKAR
    "SUBMITTED":              "Demande soumise",
    "VALIDATED":              "Demande validée",
    "REJECTED":               "Demande rejetée",
    "APPROVED":               "Demande approuvée",
    "APPOINTMENT_SCHEDULED":  "Rendez-vous planifié",
    "SAMPLE_RECEIVED":        "Échantillons reçus",
    "SAMPLE_VERIFIED":        "Échantillons vérifiés",
    "ASSIGNED":               "Analyste assigné",
    "PENDING_ACCEPTANCE":     "En attente d'acceptation",
    "IN_PROGRESS":            "Analyse en cours",
    "ANALYSIS_FINISHED":      "Analyse terminée",
    "REPORT_UPLOADED":        "Rapport généré",
    "ADMIN_REVIEW":           "En révision administrative",
    "REPORT_VALIDATED":       "Rapport validé",
    "SENT_TO_REQUESTER":      "Rapport transmis au demandeur",
    "COMPLETED":              "Demande clôturée",
    # GENOCLAB
    "QUOTE_DRAFT":                   "Devis en cours de préparation",
    "QUOTE_SENT":                    "Devis envoyé",
    "QUOTE_VALIDATED_BY_CLIENT":     "Devis accepté par le client",
    "QUOTE_REJECTED_BY_CLIENT":      "Devis refusé par le client",
    "INVOICE_GENERATED":             "Facture générée",
    "SENT_TO_CLIENT":                "Rapport transmis au client",
}

# ── Role → notification message templates ─────────────────────────────────────
_ROLE_MESSAGES = {
    config.ROLE_REQUESTER: {
        "VALIDATED":          "✅ Votre demande a été validée par l'équipe PLAGENOR.",
        "REJECTED":           "❌ Votre demande a été rejetée. Consultez le motif dans votre espace.",
        "APPROVED":           "🏦 Votre demande a été approuvée. Un rendez-vous sera planifié.",
        "REPORT_VALIDATED":   "📄 Votre rapport d'analyse est validé et prêt.",
        "SENT_TO_REQUESTER":  "📬 Votre rapport vous a été transmis. Consultez votre espace.",
        "COMPLETED":          "🎉 Votre demande est clôturée. Merci d'avoir utilisé PLAGENOR.",
    },
    config.ROLE_CLIENT: {
        "VALIDATED":                 "✅ Votre demande GENOCLAB a été validée.",
        "REJECTED":                  "❌ Votre demande a été rejetée. Consultez votre espace.",
        "QUOTE_SENT":                "💵 Un devis vous a été envoyé. Votre accord est requis.",
        "INVOICE_GENERATED":         "🧾 Votre facture a été générée. Consultez l'onglet Factures.",
        "SENT_TO_CLIENT":            "📬 Votre rapport d'analyse vous a été transmis.",
        "COMPLETED":                 "🎉 Votre dossier GENOCLAB est clôturé.",
        "QUOTE_REJECTED_BY_CLIENT":  "📋 Votre refus de devis a été enregistré.",
    },
    config.ROLE_MEMBER: {
        "ASSIGNED":           "🔔 Une nouvelle demande vous a été assignée.",
        "PENDING_ACCEPTANCE": "⚡ Vous devez accepter ou refuser l'assignation dans votre tableau de bord.",
    },
    config.ROLE_FINANCE: {
        "INVOICE_GENERATED": "🧾 Une nouvelle facture GENOCLAB a été émise. Vérifiez l'intégrité.",
    },
    config.ROLE_PLATFORM_ADMIN: {
        "SUBMITTED":    "📨 Nouvelle demande soumise en attente de validation.",
        "REPORT_UPLOADED": "📄 Un rapport est prêt pour révision administrative.",
    },
}


# ── In-app notification builder ───────────────────────────────────────────────

def _build_notification(
    recipient_role: str,
    to_state:       str,
    request:        dict,
    triggered_by:   str,
) -> dict:
    """Builds a notification record for in-app storage."""
    label   = _STATE_LABELS.get(to_state, to_state)
    message = (
        _ROLE_MESSAGES
        .get(recipient_role, {})
        .get(to_state,
             f"Mise à jour: demande {request['id'][:8].upper()} → {label}")
    )
    return {
        "id":            str(uuid.uuid4()),
        "recipient_role": recipient_role,
        "request_id":    request["id"],
        "channel":       request.get("channel", ""),
        "to_state":      to_state,
        "state_label":   label,
        "message":       message,
        "triggered_by":  triggered_by,
        "created_at":    datetime.utcnow().isoformat(),
        "read":          False,
    }


# ── Email dispatch (SMTP with graceful fallback) ──────────────────────────────

def _send_email_notification(
    to_address:  str,
    subject:     str,
    body:        str,
) -> bool:
    """
    Attempts to send an email notification via SMTP.
    Reads SMTP config from environment variables:
      PLAGENOR_SMTP_HOST, PLAGENOR_SMTP_PORT,
      PLAGENOR_SMTP_USER, PLAGENOR_SMTP_PASS
    Returns True on success, False on failure (never raises).
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.environ.get("PLAGENOR_SMTP_HOST", "")
    smtp_port = int(os.environ.get("PLAGENOR_SMTP_PORT", 587))
    smtp_user = os.environ.get("PLAGENOR_SMTP_USER", "")
    smtp_pass = os.environ.get("PLAGENOR_SMTP_PASS", "")

    if not smtp_host or not smtp_user:
        return False   # SMTP not configured — silently skip

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_address
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_address, msg.as_string())
        return True
    except Exception:
        return False


def _get_user_email_for_role(role: str, request: dict) -> str:
    """
    Resolves the email address for a role notification.
    For REQUESTER/CLIENT: reads from request form_data.
    For MEMBER/ADMIN/FINANCE: reads from user record.
    Returns empty string if not found.
    """
    try:
        if role in (config.ROLE_REQUESTER, config.ROLE_CLIENT):
            return (
                request
                .get("form_data", {})
                .get("requester", {})
                .get("email", "")
            )

        if role == config.ROLE_MEMBER:
            from core.repository import get_member, get_user
            member_id = request.get("assigned_member_id", "")
            if not member_id:
                return ""
            member  = get_member(member_id)
            if not member:
                return ""
            user_id = member.get("user_id", "")
            user    = get_user(user_id)
            return user.get("email", "") if user else ""

        # FINANCE / PLATFORM_ADMIN / SUPER_ADMIN
        from core.repository import get_all_users
        users = [
            u for u in get_all_users()
            if u.get("role") == role and u.get("active")
        ]
        # Notify first active user of that role (expand later for multi-user)
        return users[0].get("email", "") if users else ""

    except Exception:
        return ""


# ── Main dispatcher ───────────────────────────────────────────────────────────

def notify_roles(
    roles:        List[str],
    request:      dict,
    to_state:     str,
    triggered_by: str = "system",
) -> None:
    """
    Main notification dispatcher called by workflow_engine.
    For each role:
      1. Builds in-app notification record
      2. Persists to repository
      3. Attempts email dispatch
      4. Logs notification event

    All failures are silenced — notifications NEVER block transitions.
    """
    for role in roles:
        try:
            # Build and persist in-app notification
            notif = _build_notification(
                recipient_role = role,
                to_state       = to_state,
                request        = request,
                triggered_by   = triggered_by,
            )

            try:
                from core.repository import save_notification
                save_notification(notif)
            except Exception:
                pass   # repository failure — silenced

            # Attempt email
            email_addr = _get_user_email_for_role(role, request)
            if email_addr:
                label   = _STATE_LABELS.get(to_state, to_state)
                subject = (
                    f"PLAGENOR 4.0 — "
                    f"{request.get('channel', '')} | "
                    f"Réf: {request['id'][:8].upper()} | "
                    f"{label}"
                )
                body = (
                    f"{notif['message']}\n\n"
                    f"Référence: {request['id'][:8].upper()}\n"
                    f"Canal: {request.get('channel', '')}\n"
                    f"Statut: {label}\n"
                    f"Déclenché par: {triggered_by}\n"
                    f"Date: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC\n\n"
                    f"Connectez-vous à PLAGENOR 4.0 pour consulter les détails.\n"
                    f"Contact: mohamed.merzoug.essbo@gmail.com"
                )
                _send_email_notification(email_addr, subject, body)

            # Log the notification event
            log_event(
                entity_type = "NOTIFICATION",
                entity_id   = request["id"],
                action      = f"NOTIF_{to_state}_{role}",
                user_id     = "system",
                details     = {
                    "role":         role,
                    "to_state":     to_state,
                    "message":      notif["message"],
                    "email_target": email_addr or "none",
                    "triggered_by": triggered_by,
                },
            )

        except Exception:
            pass   # total silence — notifications never block governance


# ── In-app notification reader (for dashboards) ───────────────────────────────

def get_unread_notifications(user_id: str, role: str) -> list:
    """
    Returns unread in-app notifications for a given user/role.
    Used by dashboard sidebars to show notification badges.
    Returns empty list on any failure.
    """
    try:
        from core.repository import get_notifications_for_role
        notifs = get_notifications_for_role(role)
        return [n for n in notifs if not n.get("read", False)]
    except Exception:
        return []


def mark_notification_read(notification_id: str) -> None:
    """
    Marks a single notification as read.
    Silenced on failure.
    """
    try:
        from core.repository import get_notification, save_notification
        notif = get_notification(notification_id)
        if notif:
            notif["read"]    = True
            notif["read_at"] = datetime.utcnow().isoformat()
            save_notification(notif)
    except Exception:
        pass