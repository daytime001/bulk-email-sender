#!/usr/bin/env python3
"""配置测试工具（legacy CLI wrapper）。"""

from __future__ import annotations

import os
import uuid

import config
from bulk_email_sender.legacy import (
    LegacyConfigError,
    build_job_from_legacy_config,
    create_engine,
    ensure_legacy_config_ready,
    load_recipients_from_legacy_config,
)
from bulk_email_sender.models import Recipient
from bulk_email_sender.recipients_loader import RecipientLoadError
from bulk_email_sender.smtp_client import SMTPClient
from bulk_email_sender.template import TemplateRenderError, render_template_text


def test_email_config():
    """测试邮箱配置"""
    print("📧 测试邮箱配置...")

    try:
        ensure_legacy_config_ready(config)
    except LegacyConfigError as exc:
        print(f"❌ {exc}")
        return False

    print(f"✅ 发件邮箱: {config.SENDER_EMAIL}")
    print(f"✅ 发件人: {config.SENDER_NAME}")
    print(f"✅ 邮件主题: {config.EMAIL_SUBJECT}")

    smtp_client = SMTPClient(
        build_job_from_legacy_config(
            config,
            job_id=f"test-{uuid.uuid4().hex[:8]}",
            recipients=[Recipient(email="healthcheck@example.com", name="Health Check")],
        ).smtp
    )
    try:
        smtp_client.test_connection()
        print("✅ SMTP连接测试成功")
        return True
    except Exception as exc:
        print(f"❌ SMTP连接测试失败: {exc}")
        return False


def test_data_file():
    """测试数据文件"""
    print(f"\n📊 测试数据文件: {config.TEACHER_DATA_FILE}")
    try:
        result = load_recipients_from_legacy_config(config)
    except RecipientLoadError as exc:
        print(f"❌ 收件人数据加载失败: {exc}")
        return False

    print(f"✅ 成功加载 {len(result.recipients)} 位收件人")
    print(
        f"✅ 数据统计: total={result.stats.total_rows}, valid={result.stats.valid_rows}, "
        f"duplicate={result.stats.duplicate_rows}, empty={result.stats.empty_rows}"
    )
    return True


def test_attachments():
    """测试附件文件"""
    print("\n📎 测试附件文件...")

    if not config.ATTACHMENTS:
        print("ℹ️  未配置附件文件")
        return True

    all_exist = True
    for attachment in config.ATTACHMENTS:
        if os.path.exists(attachment):
            size = os.path.getsize(attachment) / (1024 * 1024)  # MB
            print(f"✅ {attachment} (大小: {size:.2f}MB)")
            if size > 10:
                print(f"⚠️  警告: {attachment} 文件过大，可能发送失败")
        else:
            print(f"❌ {attachment} 文件不存在")
            all_exist = False

    return all_exist


def test_email_content():
    """测试邮件内容模板"""
    print("\n📝 测试邮件内容模板...")

    try:
        test_content = render_template_text(
            config.EMAIL_CONTENT,
            {
                "teacher_name": "张教授",
                "teacher_email": "teacher@example.com",
                "sender_name": config.SENDER_NAME,
            },
        )
        print("✅ 邮件模板格式正确")

        # 显示模板预览
        print("\n📄 邮件内容预览（前200字符）:")
        print("-" * 40)
        print(test_content[:200] + "...")
        print("-" * 40)

        return True
    except TemplateRenderError as e:
        print(f"❌ 邮件模板格式错误: {e}")
        return False


def send_test_email():
    """发送测试邮件"""
    print("\n🧪 发送测试邮件...")

    test_email = input("请输入测试邮件接收地址（建议使用您自己的邮箱）: ").strip()
    if not test_email:
        print("❌ 未输入测试邮件地址")
        return False

    recipient = Recipient(email=test_email, name="测试教授")
    job = build_job_from_legacy_config(
        config,
        job_id=f"manual-test-{uuid.uuid4().hex[:8]}",
        recipients=[recipient],
    )
    engine = create_engine(job)
    events = list(engine.send(job))
    finished = events[-1]
    if finished["type"] == "job_finished" and finished["success"] == 1:
        print("✅ 测试邮件发送成功")
        return True
    print("❌ 测试邮件发送失败")
    return False


def main():
    """主函数"""
    print("🧪 配置测试工具")
    print("=" * 50)

    # 测试各项配置
    tests = [
        ("邮箱配置", test_email_config),
        ("数据文件", test_data_file),
        ("附件文件", test_attachments),
        ("邮件模板", test_email_content),
    ]

    results = {}
    for test_name, test_func in tests:
        print(f"\n{'=' * 20} {test_name} {'=' * 20}")
        results[test_name] = test_func()

    # 输出测试结果汇总
    print("\n" + "=" * 50)
    print("📋 测试结果汇总")
    print("=" * 50)

    all_passed = True
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False

    if all_passed:
        print("\n🎉 所有测试通过！")

        # 询问是否发送测试邮件
        send_test = input("\n是否发送测试邮件？(y/N): ").strip().lower()
        if send_test == "y":
            send_test_email()

        print("\n💡 您可以运行以下命令开始批量发送:")
        print("python main.py")
    else:
        print("\n⚠️  存在配置问题，请根据上述提示进行修复")

    print("=" * 50)


if __name__ == "__main__":
    main()
