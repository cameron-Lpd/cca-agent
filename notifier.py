"""
Gate 1 notification — alerts the user that a new webinar was detected
and provides approve / reject links.

Sends: desktop toast (Windows) + email failsafe.
"""

import smtplib
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from scraper import WebinarListing


def notify_gate1(listing: WebinarListing, approve_url: str, reject_url: str) -> None:
    """Fire both desktop and email notifications for Gate 1."""
    _desktop_toast(listing)
    _email_notification(listing, approve_url, reject_url)


# ── Desktop toast (Windows) ───────────────────────────────────────────────────

def _desktop_toast(listing: WebinarListing) -> None:
    msg = f"New webinar detected: {listing.title} ({listing.date}). Check your email to approve the scrape."
    try:
        script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        $n = New-Object System.Windows.Forms.NotifyIcon
        $n.Icon = [System.Drawing.SystemIcons]::Information
        $n.Visible = $true
        $n.ShowBalloonTip(8000, 'CCA Agent — New Webinar', '{msg[:100]}', [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Seconds 9
        $n.Dispose()
        """
        subprocess.Popen(
            ["powershell", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[Notifier] Desktop toast failed (non-fatal): {e}")


# ── Email notification ────────────────────────────────────────────────────────

def _email_notification(
    listing: WebinarListing, approve_url: str, reject_url: str
) -> None:
    if not all([config.EMAIL_SENDER, config.SMTP_HOST, config.SMTP_USER, config.SMTP_PASS]):
        print("[Notifier] Email not configured — skipping email notification.")
        return

    subject = f"[CCA Agent] New Webinar Detected: {listing.title}"
    html = _gate1_html(listing, approve_url, reject_url)
    plain = _gate1_plain(listing, approve_url, reject_url)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = ", ".join(config.NOTIFY_RECIPIENTS)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.sendmail(config.EMAIL_SENDER, config.NOTIFY_RECIPIENTS, msg.as_string())
        print(f"[Notifier] Gate 1 email sent to {config.NOTIFY_RECIPIENTS}")
    except Exception as e:
        print(f"[Notifier] Email send failed: {e}")


def _gate1_html(listing: WebinarListing, approve_url: str, reject_url: str) -> str:
    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:24px;">
      <h2 style="color:#1a1a2e;">CCA Agent — New Webinar Detected</h2>
      <table style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;width:100%;border-spacing:0;">
        <tr><td style="padding:6px;color:#666;width:140px;">Title</td>
            <td style="padding:6px;font-weight:bold;">{listing.title}</td></tr>
        <tr><td style="padding:6px;color:#666;">Date</td>
            <td style="padding:6px;">{listing.date}</td></tr>
        <tr><td style="padding:6px;color:#666;">Client</td>
            <td style="padding:6px;">{listing.primary_client}</td></tr>
        <tr><td style="padding:6px;color:#666;">URL</td>
            <td style="padding:6px;"><a href="{listing.url}">{listing.url}</a></td></tr>
      </table>
      <p style="margin-top:24px;">Do you want to proceed with a full scrape of this webinar?</p>
      <div style="margin-top:16px;">
        <a href="{approve_url}"
           style="background:#1a6498;color:white;padding:12px 24px;text-decoration:none;
                  border-radius:6px;font-weight:bold;display:inline-block;margin-right:12px;">
          ✓ Approve Scrape
        </a>
        <a href="{reject_url}"
           style="background:#c0392b;color:white;padding:12px 24px;text-decoration:none;
                  border-radius:6px;font-weight:bold;display:inline-block;">
          ✗ Reject
        </a>
      </div>
      <p style="margin-top:24px;color:#999;font-size:12px;">
        These links are single-use and expire after 24 hours.
      </p>
    </body></html>"""


def _gate1_plain(listing: WebinarListing, approve_url: str, reject_url: str) -> str:
    return f"""CCA Agent — New Webinar Detected
{'=' * 50}

Title:  {listing.title}
Date:   {listing.date}
Client: {listing.primary_client}
URL:    {listing.url}

Approve scrape: {approve_url}
Reject:         {reject_url}

These links are single-use and expire after 24 hours.
"""
