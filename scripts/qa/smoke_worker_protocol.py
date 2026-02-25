#!/usr/bin/env python3
"""Worker 协议 CLI 冒烟测试 (communicate 版).

用法:
  uv run scripts/qa/smoke_worker_protocol.py

原理:
  一次性把所有命令写入 stdin, 关闭 stdin 后等进程退出再读取全部 stdout.
  避免异步 pipe 读写的竞态问题.

  worker.py main() 在 stdin 关闭后会 join 后台 job 线程, 确保所有事件
  全部 flush 后进程才退出.
"""

from __future__ import annotations

import json
import socketserver
import subprocess
import sys
import threading
import time
from contextlib import suppress
from email import message_from_bytes
from email.policy import default as email_policy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RECIPIENTS_FILE = DATA_DIR / "teachers.json"

SAMPLE_RECIPIENTS = [
    {"name": "张教授", "email": "zhang@example.test"},
    {"name": "测试人", "email": "test@example.test"},
]

# ---------------------------------------------------------------------------
# 最简内嵌 SMTP 服务器
# ---------------------------------------------------------------------------


class _SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 smoke ready\r\n")
        self.wfile.flush()
        in_data = False
        body_lines: list[bytes] = []
        for raw in self.rfile:
            line = raw.rstrip(b"\r\n")
            if in_data:
                if line == b".":
                    self.server.received.append(b"\r\n".join(body_lines))
                    body_lines = []
                    in_data = False
                    self.wfile.write(b"250 OK\r\n")
                else:
                    body_lines.append(line)
            else:
                upper = line.upper()
                if upper.startswith(b"EHLO") or upper.startswith(b"HELO"):
                    self.wfile.write(b"250 smoke\r\n")
                elif upper.startswith(b"AUTH"):
                    self.wfile.write(b"235 OK\r\n")
                elif upper.startswith(b"MAIL FROM") or upper.startswith(b"RCPT TO"):
                    self.wfile.write(b"250 OK\r\n")
                elif upper == b"DATA":
                    self.wfile.write(b"354 go ahead\r\n")
                    in_data = True
                elif upper.startswith(b"QUIT"):
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 OK\r\n")
            self.wfile.flush()


class _SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received: list[bytes] = []


def start_smtp_server() -> tuple[_SMTPServer, int]:
    server = _SMTPServer(("127.0.0.1", 0), _SMTPHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


# ---------------------------------------------------------------------------
# 测试工具
# ---------------------------------------------------------------------------
_PASS = "\033[32m✓\033[0m"
_FAIL = "\033[31m✗\033[0m"
_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  {_PASS} {name}")
    else:
        msg = f"{name}" + (f": {detail}" if detail else "")
        print(f"  {_FAIL} {msg}")
        _failures.append(msg)


def find(events: list[dict], type_: str) -> dict | None:
    return next((e for e in events if e.get("type") == type_), None)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run() -> None:
    # 准备收件人文件
    DATA_DIR.mkdir(exist_ok=True)
    RECIPIENTS_FILE.write_text(
        json.dumps(SAMPLE_RECIPIENTS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 启动本地 SMTP 服务器
    smtp_server, smtp_port = start_smtp_server()
    time.sleep(0.05)

    smtp_payload = {
        "host": "127.0.0.1",
        "port": smtp_port,
        "username": "",
        "password": "",
        "use_ssl": False,
        "use_starttls": False,
    }
    template_payload = {
        "subject": "冒烟测试主题",
        "body_text": "你好 {{ teacher_name }}, 这是测试邮件.",
    }
    sender_valid = {"email": "smoker@test", "name": "冒烟测试"}

    # 命令顺序:
    # 1. load_recipients
    # 2. test_smtp
    # 3. bogus_cmd → error
    # 4. start_send 空发件邮箱 → validation error (在 job 线程启动前就报错)
    # 5. start_send 正常发送 → job thread; 进程退出前 main() 会 join 线程
    commands: list[dict] = [
        {
            "type": "load_recipients",
            "payload": {"path": str(RECIPIENTS_FILE)},
        },
        {
            "type": "test_smtp",
            "payload": smtp_payload,
        },
        {
            "type": "bogus_cmd",
        },
        {
            "type": "start_send",
            "payload": {
                "sender": {"email": "", "name": ""},
                "smtp": smtp_payload,
                "template": template_payload,
                "recipients": SAMPLE_RECIPIENTS,
                "options": {"min_delay_sec": 0, "max_delay_sec": 0},
            },
        },
        {
            "type": "start_send",
            "payload": {
                "sender": sender_valid,
                "smtp": smtp_payload,
                "template": template_payload,
                "recipients": SAMPLE_RECIPIENTS,
                "options": {"min_delay_sec": 0, "max_delay_sec": 0},
            },
        },
    ]
    stdin_data = "\n".join(json.dumps(c, ensure_ascii=False) for c in commands) + "\n"

    # 启动 worker 子进程
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "bulk_email_sender.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    try:
        stdout_data, stderr_data = proc.communicate(input=stdin_data, timeout=45)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_data, stderr_data = proc.communicate()
        print(f"  {_FAIL} worker 超时 (45s)")
        _failures.append("worker subprocess timed out")
        return

    events: list[dict] = []
    for line in stdout_data.splitlines():
        line = line.strip()
        if not line:
            continue
        with suppress(json.JSONDecodeError):
            events.append(json.loads(line))

    if stderr_data.strip():
        print(f"  [stderr] {stderr_data[:400]}")

    # -----------------------------------------------------------------------
    print("\n[1] load_recipients")
    ev = find(events, "recipients_loaded")
    check("收到 recipients_loaded", ev is not None, str(events[:3]))
    if ev:
        stats = ev.get("stats", {})
        check("stats.valid_rows == 2", stats.get("valid_rows") == 2, str(stats))
        check("stats.invalid_rows == 0", stats.get("invalid_rows") == 0, str(stats))

    print("\n[2] test_smtp")
    ev = find(events, "smtp_test_succeeded")
    check(
        "收到 smtp_test_succeeded",
        ev is not None,
        f"实际事件类型: {[e.get('type') for e in events]}",
    )

    print("\n[3] bogus_cmd → error")
    bogus_err = next(
        (e for e in events if e.get("type") == "error" and "bogus_cmd" in e.get("error", "")),
        None,
    )
    check("收到含 bogus_cmd 的 error", bogus_err is not None, str([e for e in events if e.get("type") == "error"]))

    print("\n[4] start_send 空发件邮箱 → validation error")
    validation_err = next(
        (e for e in events if e.get("type") == "error" and "发件邮箱" in e.get("error", "")),
        None,
    )
    check(
        "收到含 '发件邮箱' 的 error", validation_err is not None, str([e for e in events if e.get("type") == "error"])
    )

    print("\n[5] start_send 正常发送")
    finished = find(events, "job_finished")
    check("收到 job_finished", finished is not None, str(events[-6:]))
    if finished:
        check("success == 2", finished.get("success") == 2, str(finished))
        check("failed == 0", finished.get("failed") == 0, str(finished))

    # 等待邮件到达 SMTP 服务器（最多 3 秒）
    deadline = time.time() + 3
    while len(smtp_server.received) < 2 and time.time() < deadline:
        time.sleep(0.05)

    check(
        "SMTP 服务器收到 2 封邮件",
        len(smtp_server.received) == 2,
        f"实际收到: {len(smtp_server.received)}",
    )
    if len(smtp_server.received) >= 1:
        msg = message_from_bytes(smtp_server.received[0], policy=email_policy)
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""
        check("第1封正文含 '张教授'", "张教授" in text, repr(text[:120]))
    if len(smtp_server.received) >= 2:
        msg = message_from_bytes(smtp_server.received[1], policy=email_policy)
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""
        check("第2封正文含 '测试人'", "测试人" in text, repr(text[:120]))

    # -----------------------------------------------------------------------
    smtp_server.shutdown()

    print()
    if _failures:
        print(f"\033[31mFAILED ({len(_failures)}): {_failures}\033[0m")
        sys.exit(1)
    else:
        print("\033[32m所有 Worker 协议冒烟测试通过!\033[0m")


if __name__ == "__main__":
    run()
