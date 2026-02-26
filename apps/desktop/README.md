# Desktop 客户端开发说明

本目录是 `Bulk-Email-Sender` 的桌面端（Tauri + React + TypeScript）工程。

## 技术栈

- Tauri v2（Rust 命令层）
- React 19 + TypeScript + Vite
- Ant Design + shadcn/ui（当前为混合组件方案）
- Tailwind CSS v4（样式变量与基础 UI 组件）

## 环境要求

- Node.js 20+
- Rust stable（含 `cargo`）
- Python 3.9+（用于 worker）
- `uv`（推荐，用于统一 Python 环境）

## 本地启动

在仓库根目录准备 Python 依赖：

```bash
uv sync --dev
```

进入桌面端目录安装前端依赖：

```bash
cd apps/desktop
npm install
```

启动桌面开发环境（会拉起 Vite + Tauri）：

```bash
npm run tauri dev
```

仅调试前端页面（浏览器模式，使用 mock backend）：

```bash
npm run dev
```

## 构建与检查

```bash
npm run lint
npm run build
cd src-tauri && cargo check && cd ..
npm run tauri:build:app -- --debug
```

## 关键能力

- 发件人设置、收件人导入、邮件内容编辑、系统设置四个工作区拆分。
- 运行时管理支持：
  - 自动检测 Python
  - 手动选择 Python 可执行文件
  - 清理运行时配置
- 数据目录可配置，并暴露一键打开能力：
  - `records/sent_records.jsonl`
  - `records/sent_records.txt`
  - `logs/email_log.txt`
  - `config/app_draft.json`
- 首次初始化会自动写入示例收件人文件：
  - `recipients_sample.json`
  - `recipients_sample.xlsx`
- SMTP 测试连接支持实时状态与耗时显示。

## 与 Python worker 的协议约定

- 入口脚本：仓库根目录 `worker.py`（包装 `bulk_email_sender.worker`）
- 常用命令：`load_recipients` / `test_smtp` / `start_send` / `cancel_send`
- 事件通道：`worker-event`
- 发送 payload 的 `paths` 字段需同时传：
  - `sent_store_file`（JSONL 去重记录）
  - `sent_store_text_file`（可读 TXT 记录）

## 目录结构（简化）

```text
apps/desktop/
  src/
    features/
      sender-settings/
      recipients/
      email-content/
      settings/
    components/ui/
    services/backend.ts
    types.ts
  src-tauri/
    src/lib.rs
    tauri.conf.json
```
