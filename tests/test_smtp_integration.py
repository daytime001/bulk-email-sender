from __future__ import annotations

import socketserver
import threading
from email.message import EmailMessage
from pathlib import Path
from socket import socket

from bulk_email_sender.models import SMTPConfig
from bulk_email_sender.smtp_client import SMTPClient


class MiniSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address, handler_class):
        super().__init__(server_address, handler_class)
        self.payloads: list[str] = []


class MiniSMTPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"220 mini-smtp ESMTP ready\r\n")
        self.wfile.flush()

        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode("utf-8", errors="ignore").strip()
            upper = command.upper()

            if upper.startswith("EHLO") or upper.startswith("HELO"):
                self.wfile.write(b"250-mini-smtp\r\n250 SIZE 10485760\r\n")
            elif upper.startswith("MAIL FROM") or upper.startswith("RCPT TO"):
                self.wfile.write(b"250 OK\r\n")
            elif upper == "DATA":
                self.wfile.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                data_lines: list[bytes] = []
                while True:
                    chunk = self.rfile.readline()
                    if chunk == b".\r\n" or chunk == b".\n":
                        break
                    data_lines.append(chunk)
                payload = b"".join(data_lines).decode("utf-8", errors="ignore")
                self.server.payloads.append(payload)  # type: ignore[attr-defined]
                self.wfile.write(b"250 queued\r\n")
            elif upper == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                self.wfile.flush()
                return
            else:
                self.wfile.write(b"250 OK\r\n")

            self.wfile.flush()


def _pick_free_port() -> int:
    with socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_smtp_client_can_send_to_local_debug_server(tmp_path: Path) -> None:
    port = _pick_free_port()
    server = MiniSMTPServer(("127.0.0.1", port), MiniSMTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "teacher@example.com"
    message["Subject"] = "integration-test"
    message.set_content("hello smtp")

    client = SMTPClient(
        SMTPConfig(
            host="127.0.0.1",
            port=port,
            username="",
            password="",
            use_ssl=False,
            use_starttls=False,
            timeout_sec=3,
        )
    )
    client.send("teacher@example.com", message)

    server.shutdown()
    server.server_close()
    thread.join(timeout=1)

    assert len(server.payloads) == 1
    payload = server.payloads[0]
    assert "integration-test" in payload
    assert "hello smtp" in payload
