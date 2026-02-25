#!/usr/bin/env python3
"""真实邮件小规模冒烟测试.

功能:
  1. 连接真实 SMTP 服务器 (test_smtp)
  2. 向你指定的 1-3 个收件人发送测试邮件 (start_send)
  3. 验证 Worker 事件流完整性

前置步骤:
  1. 复制配置模板:
       cp scripts/qa/real_email_config.example.env scripts/qa/.real_email.env
  2. 编辑 .real_email.env, 填写你的 SMTP / 收件人信息
  3. 运行:
       uv run python scripts/qa/smoke_real_email.py

注意: .real_email.env 已加入 .gitignore, 邮件密码不会泄露.
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = Path(__file__).parent / ".real_email.env"
EXAMPLE_FILE = Path(__file__).parent / "real_email_config.example.env"

# ---------------------------------------------------------------------------
# 工具
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
# 读取 .env 配置
# ---------------------------------------------------------------------------


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def require(env: dict[str, str], key: str) -> str:
    val = env.get(key, "").strip()
    if not val:
        print(f"\033[31m[ERROR]\033[0m 配置缺少或为空: {key}")
        print(f"        请编辑 {CONFIG_FILE} 并填写该字段.")
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run() -> None:
    # 检查配置文件
    if not CONFIG_FILE.exists():
        print(f"\033[33m[提示]\033[0m 配置文件不存在: {CONFIG_FILE.relative_to(PROJECT_ROOT)}")
        print("       请先复制模板并填写你的 SMTP 信息:")
        print(f"         cp {EXAMPLE_FILE.relative_to(PROJECT_ROOT)} \\")
        print(f"            {CONFIG_FILE.relative_to(PROJECT_ROOT)}")
        sys.exit(0)

    env = load_env(CONFIG_FILE)

    smtp_host = require(env, "SMTP_HOST")
    smtp_port = int(require(env, "SMTP_PORT"))
    smtp_user = require(env, "SMTP_USER")
    smtp_password = require(env, "SMTP_PASSWORD")
    use_ssl = env.get("SMTP_USE_SSL", "true").lower() == "true"
    use_starttls = env.get("SMTP_USE_STARTTLS", "false").lower() == "true"

    sender_email = require(env, "SENDER_EMAIL")
    sender_name = env.get("SENDER_NAME", sender_email)

    recipient_emails = [e.strip() for e in require(env, "RECIPIENT_EMAILS").split(",") if e.strip()]
    recipient_names_raw = env.get("RECIPIENT_NAMES", "")
    recipient_names = [n.strip() for n in recipient_names_raw.split(",") if n.strip()]
    # 如果名字不够用, 用邮箱地址代替
    recipients = [
        {"name": recipient_names[i] if i < len(recipient_names) else email, "email": email}
        for i, email in enumerate(recipient_emails)
    ]

    if not recipients:
        print("\033[31m[ERROR]\033[0m RECIPIENT_EMAILS 为空, 请至少填一个收件地址.")
        sys.exit(1)

    print(
        f"SMTP: {smtp_user} → {smtp_host}:{smtp_port} ({'SSL' if use_ssl else 'STARTTLS' if use_starttls else '明文'})"
    )
    print(f"收件人: {', '.join(r['name'] + '<' + r['email'] + '>' for r in recipients)}")
    print()

    smtp_payload = {
        "host": smtp_host,
        "port": smtp_port,
        "username": smtp_user,
        "password": smtp_password,
        "use_ssl": use_ssl,
        "use_starttls": use_starttls,
        "timeout_sec": 30,
    }

    commands: list[dict] = [
        {
            "type": "test_smtp",
            "payload": smtp_payload,
        },
        {
            "type": "start_send",
            "payload": {
                "sender": {"email": sender_email, "name": sender_name},
                "smtp": smtp_payload,
                "template": {
                    "subject": "【冒烟测试】Bulk Email Sender 测试邮件",
                    "body_text": (
                        "你好 {{ teacher_name }},\n\n"
                        "这是 bulk-email-sender 项目的功能冒烟测试邮件。\n"
                        "如果你收到此邮件, 说明发送链路工作正常。\n\n"
                        "-- 由 smoke_real_email.py 自动发送"
                    ),
                },
                "recipients": recipients,
                "options": {
                    "min_delay_sec": 1,
                    "max_delay_sec": 2,
                    "skip_sent": False,
                },
            },
        },
    ]
    stdin_data = "\n".join(json.dumps(c, ensure_ascii=False) for c in commands) + "\n"

    print(f"[1] SMTP 连通测试 ({smtp_host}:{smtp_port})")
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "bulk_email_sender.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    timeout_sec = 60 + len(recipients) * 5
    try:
        stdout_data, stderr_data = proc.communicate(input=stdin_data, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_data, stderr_data = proc.communicate()
        print(f"  {_FAIL} Worker 超时 ({timeout_sec}s)")
        _failures.append("timeout")

    events: list[dict] = []
    for line in stdout_data.splitlines():
        line = line.strip()
        if not line:
            continue
        with suppress(json.JSONDecodeError):
            events.append(json.loads(line))

    if stderr_data.strip():
        print(f"  [stderr] {stderr_data[:500]}")

    # test_smtp
    ev = find(events, "smtp_test_succeeded")
    check("SMTP 连通成功", ev is not None, str([e for e in events if e.get("type") == "error"]))

    if not ev:
        smtp_errors = [e.get("error", "") for e in events if e.get("type") == "error"]
        print("\n\033[31m连通失败, 请检查:\033[0m")
        for err in smtp_errors:
            print(f"  · {err}")
        print("\n常见原因:")
        print("  · 未开启 SMTP 服务 (QQ/163 需去邮箱设置开启)")
        print("  · 密码应为 [授权码], 非登录密码")
        print("  · 端口或 SSL/STARTTLS 设置与服务商要求不符")
        sys.exit(1)

    print()
    print(f"[2] 发送测试邮件 → {len(recipients)} 位收件人")
    finished = find(events, "job_finished")
    check("收到 job_finished", finished is not None)
    if finished:
        check(
            f"成功发送 {len(recipients)} 封",
            finished.get("success") == len(recipients),
            str(finished),
        )
        check("failed == 0", finished.get("failed") == 0, str(finished))
        if finished.get("failed", 0) > 0:
            for f in finished.get("failures", []):
                print(f"    ✗ {f['name']} <{f['email']}> : {f['error']}")

    # 逐条事件打印
    for ev in events:
        t = ev.get("type", "")
        if t == "recipient_sent":
            print(f"    → 已发送: {ev.get('name')} <{ev.get('email')}>")
        elif t == "recipient_failed":
            print(f"    ✗ 发送失败: {ev.get('name')} <{ev.get('email')}> — {ev.get('error')}")

    print()
    if _failures:
        print(f"\033[31mFAILED: {_failures}\033[0m")
        sys.exit(1)
    else:
        print("\033[32m所有真实邮件冒烟测试通过!\033[0m")
        print(f"\033[36m请检查 {', '.join(r['email'] for r in recipients)} 的收件箱确认收到邮件.\033[0m")


if __name__ == "__main__":
    run()
