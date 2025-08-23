#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置测试工具
用于测试邮箱配置和数据文件是否正确
"""

import os
from config import *
from email_sender import EmailSender
from data_loader import DataLoader

def test_email_config():
    """测试邮箱配置"""
    print("📧 测试邮箱配置...")

    print(f"✅ 发件邮箱: {SENDER_EMAIL}")
    print(f"✅ 发件人: {SENDER_NAME}")
    print(f"✅ 邮件主题: {EMAIL_SUBJECT}")

    # 测试SMTP连接
    email_sender = EmailSender()
    return email_sender.test_connection()

def test_data_file():
    """测试数据文件"""
    print(f"\n📊 测试数据文件: {TEACHER_DATA_FILE}")

    data_loader = DataLoader()
    teacher_data = data_loader.load_teacher_data(TEACHER_DATA_FILE)

    if not teacher_data:
        return False

    # 简单验证数据格式
    print(f"✅ 成功加载 {len(teacher_data)} 位导师数据")

    # 检查数据格式
    invalid_count = 0
    for email, name in list(teacher_data.items())[:5]:  # 只检查前5个
        if '@' not in email:
            invalid_count += 1
        if not name or not isinstance(name, str):
            invalid_count += 1

    if invalid_count > 0:
        print(f"⚠️  发现格式问题，请检查数据文件")
        return False

    print("✅ 数据格式验证通过")
    return True

def test_attachments():
    """测试附件文件"""
    print(f"\n📎 测试附件文件...")
    
    if not ATTACHMENTS:
        print("ℹ️  未配置附件文件")
        return True
    
    all_exist = True
    for attachment in ATTACHMENTS:
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
    print(f"\n📝 测试邮件内容模板...")
    
    try:
        # 测试模板格式化
        test_content = EMAIL_CONTENT.format(teacher_name="张教授")
        print("✅ 邮件模板格式正确")
        
        # 显示模板预览
        print("\n📄 邮件内容预览（前200字符）:")
        print("-" * 40)
        print(test_content[:200] + "...")
        print("-" * 40)
        
        return True
    except Exception as e:
        print(f"❌ 邮件模板格式错误: {e}")
        return False

def send_test_email():
    """发送测试邮件"""
    print(f"\n🧪 发送测试邮件...")
    
    test_email = input("请输入测试邮件接收地址（建议使用您自己的邮箱）: ").strip()
    if not test_email:
        print("❌ 未输入测试邮件地址")
        return False
    
    email_sender = EmailSender()
    return email_sender.send_single_email(test_email, "测试教授")

def main():
    """主函数"""
    print("🧪 配置测试工具")
    print("="*50)
    
    # 测试各项配置
    tests = [
        ("邮箱配置", test_email_config),
        ("数据文件", test_data_file),
        ("附件文件", test_attachments),
        ("邮件模板", test_email_content)
    ]
    
    results = {}
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        results[test_name] = test_func()
    
    # 输出测试结果汇总
    print("\n" + "="*50)
    print("📋 测试结果汇总")
    print("="*50)
    
    all_passed = True
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        print(f"\n🎉 所有测试通过！")
        
        # 询问是否发送测试邮件
        send_test = input("\n是否发送测试邮件？(y/N): ").strip().lower()
        if send_test == 'y':
            send_test_email()
        
        print(f"\n💡 您可以运行以下命令开始批量发送:")
        print(f"python main.py")
    else:
        print(f"\n⚠️  存在配置问题，请根据上述提示进行修复")
    
    print("="*50)

if __name__ == "__main__":
    main()
