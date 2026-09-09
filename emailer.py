"""Sends the generated LinkedIn content report by email."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


RECIPIENT = "cameron@pharmad-mand.com"


def send_report(results: list[dict]) -> None:
    if not results:
        return

    sender = os.environ["EMAIL_SENDER"]
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    count = len(results)
    subject = f"[Pharma D-mand] {count} New Webinar{'s' if count > 1 else ''} — LinkedIn Content Ready"

    html = _build_html(results)
    plain = _build_plain(results)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(sender, RECIPIENT, msg.as_string())

    print(f"Email sent to {RECIPIENT} with {count} webinar(s).")


def _build_html(results: list[dict]) -> str:
    today = datetime.now().strftime("%d %B %Y")
    sections = ""
    for r in results:
        # Render markdown content as preformatted text — clean and reliable
        safe_content = (
            r["content"]
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        sections += f"""
        <div style="margin-bottom:40px;padding:20px;border:1px solid #e0e0e0;border-radius:8px;">
          <h2 style="color:#1a1a2e;">{r['webinar_title']}</h2>
          <p><strong>Date:</strong> {r['webinar_date']} &nbsp;|&nbsp; <strong>Sponsor:</strong> {r['sponsor']}</p>
          <p><a href="{r['webinar_url']}">{r['webinar_url']}</a></p>
          <hr>
          <pre style="white-space:pre-wrap;font-family:Arial,sans-serif;font-size:13px;line-height:1.6;">{safe_content}</pre>
        </div>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;padding:20px;">
      <h1 style="color:#1a1a2e;">Pharma D-mand — LinkedIn Content Report</h1>
      <p style="color:#666;">Generated {today} &nbsp;|&nbsp; {len(results)} new webinar(s) detected</p>
      {sections}
      <p style="color:#999;font-size:12px;">This report was generated automatically by the pharmad-webinar-agent.</p>
    </body></html>"""


def _build_plain(results: list[dict]) -> str:
    today = datetime.now().strftime("%d %B %Y")
    lines = [f"Pharma D-mand LinkedIn Content Report — {today}", "=" * 60, ""]
    for r in results:
        lines += [
            f"WEBINAR: {r['webinar_title']}",
            f"Date: {r['webinar_date']}  |  Sponsor: {r['sponsor']}",
            f"URL: {r['webinar_url']}",
            "-" * 60,
            r["content"],
            "",
            "=" * 60,
            "",
        ]
    return "\n".join(lines)
