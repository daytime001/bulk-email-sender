from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from bulk_email_sender.models import Sender


def build_email_message(
    *,
    sender: Sender,
    recipient_email: str,
    subject: str,
    body_text: str,
    body_html: str | None,
    attachments: list[str],
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((sender.name or "", sender.email))
    message["To"] = recipient_email
    message["Subject"] = subject
    message["Message-ID"] = make_msgid()

    message.set_content(body_text, subtype="plain", charset="utf-8")
    if body_html:
        message.add_alternative(body_html, subtype="html", charset="utf-8")

    for attachment in attachments:
        path = Path(attachment)
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type is None:
            maintype, subtype = "application", "octet-stream"
        else:
            maintype, subtype = mime_type.split("/", 1)

        with path.open("rb") as handle:
            message.add_attachment(
                handle.read(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )

    return message
