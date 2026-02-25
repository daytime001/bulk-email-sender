#!/usr/bin/env python3
"""批量发送邮件主程序（legacy CLI wrapper）。"""

from __future__ import annotations

import uuid

import config
from bulk_email_sender.legacy import (
    LegacyConfigError,
    build_job_from_legacy_config,
    create_engine,
    ensure_legacy_config_ready,
    load_recipients_from_legacy_config,
)
from bulk_email_sender.recipients_loader import RecipientLoadError
from bulk_email_sender.sent_store import SentStore


def analyze_sending_status(sent_store: SentStore, recipients) -> tuple[int, int]:
    already_sent_count = sum(1 for recipient in recipients if sent_store.is_sent(recipient.email))
    to_send_count = len(recipients) - already_sent_count
    return already_sent_count, to_send_count


def main():
    """主函数"""
    print("🚀 批量邮件发送工具")
    print("=" * 50)

    try:
        ensure_legacy_config_ready(config)
    except LegacyConfigError as exc:
        print(f"❌ {exc}")
        return

    try:
        recipient_result = load_recipients_from_legacy_config(config)
    except RecipientLoadError as exc:
        print(f"❌ 收件人数据加载失败: {exc}")
        return
    recipients = recipient_result.recipients

    if not recipients:
        print("❌ 收件人列表为空，程序退出")
        return

    job = build_job_from_legacy_config(
        config,
        job_id=f"cli-{uuid.uuid4().hex[:8]}",
        recipients=recipients,
    )
    sent_store = SentStore(job.sent_store_file)

    # 分析发送状态
    already_sent_count, to_send_count = analyze_sending_status(sent_store, recipients)

    # 显示配置信息
    print(f"📧 发件邮箱: {job.sender.email}")
    print(f"👤 发件人: {job.sender.name}")
    print(f"📊 收件人数: {len(recipients)}")
    print(f"✅ 已发送数量: {already_sent_count}")
    print(f"📮 本次将发送: {to_send_count}")
    print(f"📎 附件数量: {len(job.attachments)}")
    print(f"⏱️  发送间隔: {job.options.min_delay_sec}-{job.options.max_delay_sec}秒")
    print(f"📄 邮件主题: {job.template.subject}")
    print(f"📁 收件人文件: {config.TEACHER_DATA_FILE}")
    print(f"🗂️  去重记录文件: {job.sent_store_file}")

    # 确认发送
    print("\n" + "=" * 50)
    confirm = input("确认开始发送？(输入 yes 确认): ").strip()
    if confirm.lower() != "yes":
        print("❌ 用户取消发送")
        return

    engine = create_engine(job)
    for event in engine.send(job):
        event_type = event.get("type")
        if event_type == "recipient_started":
            print(f"[{event['index']}/{len(recipients)}] 正在发送给 {event['name']}({event['email']}) ...")
        elif event_type == "recipient_sent":
            print(f"✅ 发送成功: {event['name']}({event['email']})")
        elif event_type == "recipient_failed":
            print(f"❌ 发送失败: {event['name']}({event['email']}): {event['error']}")
        elif event_type == "recipient_skipped":
            print(f"⏭️  跳过: {event['name']}({event['email']}) - 已发送过")
        elif event_type == "job_finished":
            print("\n" + "=" * 50)
            print("📊 发送完成统计")
            print("=" * 50)
            print(f"✅ 成功发送: {event['success']} 封")
            print(f"❌ 发送失败: {event['failed']} 封")
            print(f"⏭️  跳过已发送: {event['skipped']} 封")
            print(f"📧 总处理量: {event['total']} 封")
            print("=" * 50)


if __name__ == "__main__":
    main()
