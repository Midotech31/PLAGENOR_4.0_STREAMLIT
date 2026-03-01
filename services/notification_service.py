import sys, os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.audit_engine import log_event

# ── Configure your SMTP here ─────────────────────────────────────────────────
SMTP_HOST     = os.environ.get("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER",     "")   # your Gmail/Outlook
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")   # app password
FROM_NAME     = "PLAGENOR 4.0 — ESSBO"
FROM_EMAIL    = SMTP_USER
EMAIL_ENABLED = bool(SMTP_USER and SMTP_PASSWORD)


def _send_email(to_email: str, subject: str, body: str) -> bool:
    if not EMAIL_ENABLED or not to_email:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"]      = to_email

        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
        <div style="background:linear-gradient(135deg,#1B4F72,#1ABC9C);
                    padding:25px;border-radius:12px 12px 0 0;text-align:center;">
            <h2 style="color:white;margin:0;">🔬 PLAGENOR 4.0</h2>
            <p style="color:rgba(255,255,255,0.85);margin:4px 0 0 0;">
                Genomics Platform — ESSBO Oran</p>
        </div>
        <div style="background:white;padding:30px;border:1px solid #e0e8f0;
                    border-radius:0 0 12px 12px;">
            <h3 style="color:#1B4F72;">{subject}</h3>
            <p style="color:#555;line-height:1.7;">{body.replace(chr(10),'<br>')}</p>
            <hr style="border-color:#e0e8f0;">
            <p style="color:#aaa;font-size:0.8rem;">
                © 2026 PLAGENOR — ESSBO, Oran, Algeria<br>
                This is an automated notification. Do not reply.
            </p>
        </div>
        </body></html>
        """
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        log_event("NOTIFICATION", "system", "EMAIL_SEND_FAILED", "system",
                  {"error": str(e), "to": to_email, "subject": subject})
        return False


def notify(user_id: str, subject: str, body: str,
           email: str = None) -> None:
    """
    Send notification via:
    1. Email (if SMTP configured + email known)
    2. Audit log (always)
    """
    # Try to resolve email from user record
    if not email and user_id:
        try:
            from core.repository import get_user_by_id
            u = get_user_by_id(user_id)
            email = u.get("email", "")
        except Exception:
            email = ""

    email_sent = _send_email(email, subject, body) if email else False

    log_event("NOTIFICATION", user_id or "system", "NOTIFICATION_SENT",
              user_id or "system", {
                  "subject":    subject,
                  "body":       body,
                  "email":      email or "none",
                  "email_sent": email_sent,
                  "sent_at":    datetime.utcnow().isoformat(),
              })