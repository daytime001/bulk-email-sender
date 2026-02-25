# Bulk Email Sender

面向研究申请场景的批量邮件发送工具，提供两种形态：
- `Desktop`：Tauri + React 图形客户端（推荐给非开发用户）
- `Core Engine`：Python 发送引擎（支持脚本化与自动化）

## 功能概览

- 批量发送个性化邮件（支持 `{teacher_name}` 占位符）
- 收件人文件校验（JSON / XLSX）
- SMTP 连接测试与发送前校验
- 已发送记录去重（避免重复触达）
- 运行时自检与基础打包工具链

## 快速安装（Desktop）

请在 [Releases](https://github.com/daytime001/bulk-email-sender/releases) 下载对应系统安装包。

| 平台 | 推荐安装包 | 说明 |
|---|---|---|
| Windows | `bulk-email-sender_v*_windows_*.msi` | 标准安装器 |
| macOS | `bulk-email-sender_v*_darwin_*.dmg` | 磁盘镜像安装 |
| Linux | `bulk-email-sender_v*_linux_*.AppImage` | 单文件可执行包 |

> 发布资产已做精简：仅保留每个平台 1 种主安装格式，避免同平台多包型干扰。

## 使用流程（Desktop）

1. 配置 SMTP（邮箱、授权码、主机、端口）
2. 导入收件人文件（`data/teachers.json` 或 `.xlsx`）
3. 填写主题与正文模板
4. 发送前执行 SMTP 测试
5. 启动批量发送并查看进度与失败项

## 使用流程（Python Engine）

### 环境准备

```bash
uv sync --group dev
```

### 运行测试

```bash
uv run ruff check .
uv run pytest -q
```

### 入口脚本

```bash
uv run python main.py
uv run python test_config.py
```

## 收件人数据格式

### JSON（对象）

```json
{
  "teacher1@university.edu.cn": "张教授",
  "teacher2@university.edu.cn": "李教授"
}
```

### JSON（数组）

```json
[
  { "email": "teacher1@university.edu.cn", "name": "张教授" },
  { "email": "teacher2@university.edu.cn", "name": "李教授" }
]
```

## 发布与 CI/CD

- `push main`：执行 QA 与三平台构建验证（不发布 Release）
- `push v* tag`：执行 QA，自动发布三平台正式安装包

工作流文件：`.github/workflows/desktop-release.yml`

## 项目结构

```text
apps/desktop/                 # Tauri + React 桌面应用
bulk_email_sender/            # Python 核心发送引擎
scripts/                      # QA / runtime 辅助脚本
tests/                        # Python 单元与集成测试
config.py                     # 传统 CLI 配置入口
main.py                       # 传统 CLI 主程序
worker.py                     # Desktop 调用的 Python Worker 入口
```

## 合规与安全

- 仅用于合法、合规的邮件沟通场景
- 请使用邮箱授权码，不要使用网页登录密码
- 发送前请确认目标人群与频率策略，避免骚扰与滥发

## License

MIT
