"""
Servizio email — invio email transazionali via Gmail SMTP.
Usa smtplib, zero dipendenze esterne.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
MAIL_FROM_NAME = "Huntly"


def _send(to: str, subject: str, html: str):
    """Invia un'email. Fallisce silenziosamente se SMTP non configurato."""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP non configurato — email non inviata a %s", to)
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{MAIL_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Email inviata a %s: %s", to, subject)
        return True
    except Exception as e:
        logger.error("Errore invio email a %s: %s", to, e)
        return False


def send_welcome_email(to: str, nome: str):
    """Email di benvenuto dopo la registrazione."""
    subject = "Benvenuto su Huntly!"
    html = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:'Inter',system-ui,-apple-system,sans-serif;background:#f4f4f7;">
<div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.06);">

  <!-- Header -->
  <div style="background:#4F6EF7;padding:32px 40px;text-align:center;">
    <div style="display:inline-block;width:44px;height:44px;background:rgba(255,255,255,.2);border-radius:10px;line-height:44px;color:#fff;font-weight:800;font-size:1.3rem;">H</div>
    <div style="color:#fff;font-size:1.3rem;font-weight:700;margin-top:8px;">Huntly</div>
  </div>

  <!-- Body -->
  <div style="padding:40px;">
    <h1 style="margin:0 0 8px;font-size:1.4rem;color:#0f0e17;">Ciao {nome}!</h1>
    <p style="color:#3a3a4a;font-size:.95rem;line-height:1.7;margin:0 0 24px;">
      Il tuo account è pronto. Da adesso puoi cercare candidati su LinkedIn, Indeed e InfoJobs in parallelo, analizzarli con l'AI e gestire tutta la pipeline in un unico posto.
    </p>

    <h2 style="font-size:1rem;color:#0f0e17;margin:0 0 12px;">Cosa puoi fare subito:</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
      <tr>
        <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:.9rem;color:#3a3a4a;">
          <strong style="color:#4F6EF7;">1.</strong> Lancia la tua prima esplorazione
        </td>
      </tr>
      <tr>
        <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:.9rem;color:#3a3a4a;">
          <strong style="color:#4F6EF7;">2.</strong> Leggi l'analisi AI di ogni profilo
        </td>
      </tr>
      <tr>
        <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:.9rem;color:#3a3a4a;">
          <strong style="color:#4F6EF7;">3.</strong> Usa i messaggi suggeriti per contattare i migliori
        </td>
      </tr>
      <tr>
        <td style="padding:10px 12px;font-size:.9rem;color:#3a3a4a;">
          <strong style="color:#4F6EF7;">4.</strong> Genera post LinkedIn per attrarre candidati passivi
        </td>
      </tr>
    </table>

    <div style="text-align:center;margin:32px 0;">
      <a href="https://huntlyrecruiting.io/dashboard" style="display:inline-block;padding:14px 36px;background:#4F6EF7;color:#fff;font-weight:600;font-size:.95rem;border-radius:8px;text-decoration:none;">Vai alla dashboard</a>
    </div>

    <p style="color:#71717a;font-size:.85rem;line-height:1.6;margin:0;">
      Hai domande? Rispondi a questa email — ti rispondo personalmente.<br>
      Buon recruiting!
    </p>
    <p style="color:#0f0e17;font-weight:600;font-size:.85rem;margin:12px 0 0;">
      Stefano Demartis<br>
      <span style="color:#71717a;font-weight:400;">Fondatore, Huntly</span>
    </p>
  </div>

  <!-- Footer -->
  <div style="background:#f9f9fb;padding:20px 40px;text-align:center;border-top:1px solid #eee;">
    <p style="margin:0;font-size:.75rem;color:#9ca3af;">
      &copy; 2026 Huntly &mdash; Stefano Demartis &middot;
      <a href="https://huntlyrecruiting.io/privacy" style="color:#4F6EF7;text-decoration:none;">Privacy</a> &middot;
      <a href="https://huntlyrecruiting.io/terms" style="color:#4F6EF7;text-decoration:none;">Termini</a>
    </p>
  </div>
</div>
</body>
</html>"""
    return _send(to, subject, html)
