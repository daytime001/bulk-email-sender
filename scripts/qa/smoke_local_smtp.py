#!/usr/bin/env python3
"""本地 SMTP 端到端冒烟测试.(

启动一个轻量级 debug SMTP 服务器，通过 SendEngine 全链路验证:
  - 模板渲染（变量替换）
  - SMTP 连接复用
  - SentStore 去重
  - 发送事件流完整性

用法:
  uv run scripts/qa/smoke_local_smtp.py
"""

from __future__ import annotations

import json
import socketserver
import tempfile
import threading
from pathlib import Path
from socket import socket

# ── Mini SMTP Server ────────────────────────────────────────────────────────


class MiniSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address, handler_class):
        super().__init__(server_address, handler_class)
        self.payloads: list[str] = []


class MiniSMTPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"220 smoke-smtp ready\r\n")
        self.wfile.flush()
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode("utf-8", errors="ignore").strip().upper()
            if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                self.wfile.write(b"250-smoke-smtp\r\n250 SIZE 10485760\r\n")
            elif cmd.startswith("MAIL FROM") or cmd.startswith("RCPT TO"):
                self.wfile.write(b"250 OK\r\n")
            elif cmd == "DATA":
                self.wfile.write(b"354 End data\r\n")
                data: list[bytes] = []
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b".\r\n", b".\n"):
                        break
                    data.append(chunk)
                self.server.payloads.append(b"".join(data).decode("utf-8", errors="ignore"))  # type: ignore[attr-defined]
                self.wfile.write(b"250 queued\r\n")
            elif cmd == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                self.wfile.flush()
                return
            else:
                self.wfile.write(b"250 OK\r\n")
            self.wfile.flush()


def _pick_free_port() -> int:
    with socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    from bulk_email_sender.engine import SendEngine
    from bulk_email_sender.models import (
        JobConfig,
        Recipient,
        Sender,
        SendOptions,
        SMTPConfig,
        Template,
    )
    from bulk_email_sender.sent_store import SentStore
    from bulk_email_sender.smtp_client import SMTPClient

    port = _pick_free_port()
    server = MiniSMTPServer(("127.0.0.1", port), MiniSMTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[启动] 本地 SMTP 服务器运行在 127.0.0.1:{port}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sent_store_file = tmp_path / "sent_records.jsonl"

        smtp_config = SMTPConfig(
            host="127.0.0.1",
            port=port,
            username="",
            password="",
            use_ssl=False,
            use_starttls=False,
            timeout_sec=5,
        )

        recipients = [
            Recipient(email="zhangsan@example.com", name="张三"),
            Recipient(email="lisi@example.com", name="李四"),
            Recipient(email="wangwu@example.com", name="王五"),
        ]

        job = JobConfig(
            job_id="smoke-local-001",
            sender=Sender(email="me@example.com", name="测试同学"),
            smtp=smtp_config,
            template=Template(
                subject="推免自荐 - 致{teacher_name}",
                body_text="尊敬的{teacher_name}：\n\n您好，我是{sender_name}，冒昧致信...",
                body_html=None,
            ),
            recipients=recipients,
            attachments=[],
            options=SendOptions(
                min_delay_sec=0,
                max_delay_sec=0,
                randomize_order=False,
                retry_count=1,
                add_teacher_suffix=True,
                skip_sent=True,
            ),
            log_file=tmp_path / "email.log",
            sent_store_file=sent_store_file,
        )

        # ── 第一轮：全部发送 ──
        print("\n[第一轮] 发送 3 封邮件...")
        smtp_client = SMTPClient(smtp_config)
        with SentStore(sent_store_file) as sent_store:
            engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)
            events = list(engine.send(job))

        event_types = [e["type"] for e in events]
        sent_count = sum(1 for e in events if e["type"] == "recipient_sent")
        finished = [e for e in events if e["type"] == "job_finished"]

        print(f"  事件序列: {event_types}")
        print(f"  成功发送: {sent_count} 封")
        assert sent_count == 3, f"期望 3 封，实际 {sent_count}"
        assert len(finished) == 1
        assert finished[0]["success"] == 3
        print("  ✓ 第一轮验证通过")

        # ── 验证 SMTP 服务器收到的邮件内容 ──
        print("\n[内容校验] 检查 SMTP 服务器收到的邮件...")
        assert len(server.payloads) == 3, f"期望 3 封，服务器收到 {len(server.payloads)}"
        assert "张三老师" in server.payloads[0], "第一封应包含「张三老师」"
        assert "测试同学" in server.payloads[0], "第一封应包含发件人名"
        print("  ✓ 模板变量替换正确")

        # ── 验证 SentStore 记录 ──
        print("\n[去重校验] 检查 sent_records.jsonl...")
        records = [json.loads(line) for line in sent_store_file.read_text().splitlines() if line.strip()]
        assert len(records) == 3, f"期望 3 条记录，实际 {len(records)}"
        emails_recorded = {r["email"] for r in records}
        assert emails_recorded == {"zhangsan@example.com", "lisi@example.com", "wangwu@example.com"}
        print("  ✓ 发送记录完整")

        # ── 第二轮：全部跳过 ──
        print("\n[第二轮] 重复发送（验证 skip_sent）...")
        with SentStore(sent_store_file) as sent_store2:
            engine2 = SendEngine(smtp_client=smtp_client, sent_store=sent_store2)
            events2 = list(engine2.send(job))

        skipped_count = sum(1 for e in events2 if e["type"] == "recipient_skipped")
        finished2 = [e for e in events2 if e["type"] == "job_finished"]
        print(f"  跳过: {skipped_count} 封")
        assert skipped_count == 3, f"期望全部跳过，实际跳过 {skipped_count}"
        assert finished2[0]["skipped"] == 3
        print("  ✓ 去重机制生效")

    server.shutdown()
    server.server_close()
    thread.join(timeout=1)

    print("\n" + "=" * 50)
    print("✅ 本地 SMTP 端到端冒烟测试全部通过!")
    print("=" * 50)


if __name__ == "__main__":
    main()
