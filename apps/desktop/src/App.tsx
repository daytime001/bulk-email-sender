import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LoadingOutlined } from '@ant-design/icons';
import { flushSync } from 'react-dom';
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Form,
  Input,
  InputNumber,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import { open } from '@tauri-apps/plugin-dialog';

import {
  autoDetectRuntime,
  cancelSend,
  clearRuntimePython,
  clearSentRecords,
  getRuntimeStatus,
  loadRecipients,
  setRuntimePython,
  startSend,
  testSmtp,
} from './services/backend';
import type { Recipient, RuntimeStatus, SendPayload, WorkerEvent } from './types';
import './App.css';

const { Title, Text } = Typography;
const APP_DRAFT_STORAGE_KEY = 'bulk-email-sender:draft:v1';
const DEFAULT_SMTP_HOST = 'smtp.163.com';
const DEFAULT_SMTP_PORT = 465;
const SMTP_PROVIDER_CUSTOM_KEY = 'custom';
const SMTP_TEST_TIMEOUT_SEC = 10;
const SMTP_TEST_MESSAGE_KEY = 'smtp-test-connection';

type SmtpSecurity = 'ssl' | 'starttls' | 'plain';

interface SmtpProviderPreset {
  key: string;
  label: string;
  host: string;
  port: number;
  security: SmtpSecurity;
  authHint: string;
}

const SMTP_PROVIDER_PRESETS: SmtpProviderPreset[] = [
  {
    key: '163',
    label: '163 邮箱',
    host: 'smtp.163.com',
    port: 465,
    security: 'ssl',
    authHint: '需在邮箱设置中开启 SMTP 服务并使用授权码登录',
  },
  {
    key: '126',
    label: '126 邮箱',
    host: 'smtp.126.com',
    port: 465,
    security: 'ssl',
    authHint: '需在邮箱设置中开启 SMTP 服务并使用授权码登录',
  },
  {
    key: 'qq',
    label: 'QQ 邮箱',
    host: 'smtp.qq.com',
    port: 465,
    security: 'ssl',
    authHint: '需在邮箱设置中开启 SMTP 服务并使用授权码登录',
  },
  {
    key: 'gmail',
    label: 'Gmail 邮箱',
    host: 'smtp.gmail.com',
    port: 587,
    security: 'starttls',
    authHint: '使用应用专用密码；普通账户密码通常不可用。',
  },
  {
    key: 'outlook',
    label: 'Outlook 邮箱',
    host: 'smtp.office365.com',
    port: 587,
    security: 'starttls',
    authHint: '通常使用 STARTTLS(587)；企业租户策略可能限制 SMTP。',
  },
];

const SMTP_PROVIDER_PRESET_MAP = SMTP_PROVIDER_PRESETS.reduce<Record<string, SmtpProviderPreset>>((map, item) => {
  map[item.key] = item;
  return map;
}, {});

const SMTP_PROVIDER_OPTIONS = [
  ...SMTP_PROVIDER_PRESETS.map((item) => ({ value: item.key, label: item.label })),
  { value: SMTP_PROVIDER_CUSTOM_KEY, label: '自定义 SMTP（教育邮箱等其它邮箱）' },
];

const DEFAULT_SMTP_PROVIDER = '163';

const toErrMsg = (error: unknown, fallback = '操作失败'): string => {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string' && error.trim()) return error;
  return fallback;
};

const DEFAULT_SUBJECT = '推免自荐+学校名称+您的姓名';
const DEFAULT_BODY_TEXT = '尊敬的{teacher_name}：\\n\\n您好，冒昧致信。';

interface SendSummary {
  total: number;
  success: number;
  failed: number;
  skipped: number;
}

type SmtpTestState = 'idle' | 'testing' | 'success' | 'error';

const DEFAULT_RECIPIENT_PATH = 'data/teachers.json';

interface AppDraft {
  senderEmail: string;
  senderName: string;
  smtpProvider: string;
  smtpHost: string;
  smtpPort: number;
  subject: string;
  bodyText: string;
  recipientsPath: string;
  attachmentsText: string;
}

function renderPreviewTemplate(templateText: string, variables: Record<string, string>): string {
  let output = templateText;
  for (const [key, value] of Object.entries(variables)) {
    const doublePattern = new RegExp(`\\{\\{\\s*${key}\\s*\\}\\}`, 'g');
    const singlePattern = new RegExp(`\\{\\s*${key}\\s*\\}`, 'g');
    output = output.replace(doublePattern, value).replace(singlePattern, value);
  }
  return output;
}

function toSmtpTestAlertType(state: SmtpTestState): 'info' | 'success' | 'error' {
  if (state === 'success') {
    return 'success';
  }
  if (state === 'error') {
    return 'error';
  }
  return 'info';
}

function loadDraft(): Partial<AppDraft> | null {
  try {
    const raw = window.localStorage.getItem(APP_DRAFT_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<AppDraft>;
    return parsed;
  } catch {
    return null;
  }
}

function saveDraft(draft: AppDraft): void {
  try {
    window.localStorage.setItem(APP_DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    return;
  }
}

function AppContent() {
  const { message } = App.useApp();

  const [senderEmail, setSenderEmail] = useState('');
  const [senderName, setSenderName] = useState('');
  const [smtpProvider, setSmtpProvider] = useState(DEFAULT_SMTP_PROVIDER);
  const [smtpHost, setSmtpHost] = useState(DEFAULT_SMTP_HOST);
  const [smtpPort, setSmtpPort] = useState(DEFAULT_SMTP_PORT);
  const [smtpPassword, setSmtpPassword] = useState('');

  const [subject, setSubject] = useState(DEFAULT_SUBJECT);
  const [bodyText, setBodyText] = useState(DEFAULT_BODY_TEXT);

  const [recipientsPath, setRecipientsPath] = useState(DEFAULT_RECIPIENT_PATH);
  const [recipients, setRecipients] = useState<Recipient[]>([]);

  const [attachmentsText, setAttachmentsText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isTestingSmtp, setIsTestingSmtp] = useState(false);
  const [smtpTestState, setSmtpTestState] = useState<SmtpTestState>('idle');
  const [smtpTestMessage, setSmtpTestMessage] = useState('');
  const [smtpTestElapsedSec, setSmtpTestElapsedSec] = useState(0);
  const [currentStatus, setCurrentStatus] = useState('等待开始发送');
  const [summary, setSummary] = useState<SendSummary>({ total: 0, success: 0, failed: 0, skipped: 0 });
  const [failures, setFailures] = useState<Array<{ email: string; name: string; error: string }>>([]);
  const [skipSent, setSkipSent] = useState(true);
  const [minDelaySec, setMinDelaySec] = useState(5);
  const [maxDelaySec, setMaxDelaySec] = useState(10);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [runtimePanelOpen, setRuntimePanelOpen] = useState(true);
  const hasAutoCollapsed = useRef(false);
  const smtpTestTickerRef = useRef<number | null>(null);
  const [runtimePath, setRuntimePath] = useState('');
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [draftHydrated, setDraftHydrated] = useState(false);
  const isTauriRuntime = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  const attachmentList = useMemo(
    () => attachmentsText.split(/\r?\n/).map((item) => item.trim()).filter((item) => item.length > 0),
    [attachmentsText],
  );

  const progressPercent = useMemo(() => {
    if (summary.total <= 0) {
      return 0;
    }
    const done = summary.success + summary.failed + summary.skipped;
    return Math.round((done / summary.total) * 100);
  }, [summary]);

  const recipientsColumns = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '姓名', dataIndex: 'name', key: 'name' },
  ];

  const failureColumns = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '姓名', dataIndex: 'name', key: 'name' },
    { title: '错误信息', dataIndex: 'error', key: 'error' },
  ];

  const previewRecipient = recipients[0] ?? { email: 'teacher@example.com', name: '张教授' };
  const previewVariables = {
    teacher_name: previewRecipient.name,
    teacher_email: previewRecipient.email,
    sender_name: senderName || '你的姓名',
  };
  const previewBody = renderPreviewTemplate(bodyText, previewVariables);
  const selectedSmtpPreset = smtpProvider === SMTP_PROVIDER_CUSTOM_KEY ? null : SMTP_PROVIDER_PRESET_MAP[smtpProvider] ?? null;
  const effectiveSmtpSecurity: SmtpSecurity = selectedSmtpPreset?.security ?? 'ssl';
  const effectiveSmtpUsername = senderEmail.trim();

  const normalizeDialogSelection = (selection: string | string[] | null): string[] => {
    if (!selection) {
      return [];
    }
    return Array.isArray(selection) ? selection : [selection];
  };

  useEffect(() => {
    if (runtimeStatus?.ready && !hasAutoCollapsed.current) {
      hasAutoCollapsed.current = true;
      setRuntimePanelOpen(false);
    }
  }, [runtimeStatus?.ready]);

  useEffect(() => {
    return () => {
      if (smtpTestTickerRef.current !== null) {
        window.clearInterval(smtpTestTickerRef.current);
      }
    };
  }, []);

  const refreshRuntimeStatus = useCallback(async () => {
    try {
      const status = await getRuntimeStatus();
      setRuntimeStatus(status);
      setRuntimePath(status.executable_path ?? '');
    } catch (error) {
      message.error(toErrMsg(error, '检测 Python 运行时失败'));
    }
  }, [message]);

  useEffect(() => {
    void refreshRuntimeStatus();
  }, [refreshRuntimeStatus]);

  useEffect(() => {
    const draft = loadDraft();
    if (draft) {
      if (typeof draft.senderEmail === 'string') {
        setSenderEmail(draft.senderEmail);
      }
      if (typeof draft.senderName === 'string') {
        setSenderName(draft.senderName);
      }
      if (typeof draft.smtpProvider === 'string') {
        setSmtpProvider(draft.smtpProvider);
      }
      if (typeof draft.smtpHost === 'string') {
        setSmtpHost(draft.smtpHost);
      }
      if (typeof draft.smtpPort === 'number') {
        setSmtpPort(draft.smtpPort);
      }
      if (typeof draft.subject === 'string') {
        setSubject(draft.subject);
      }
      if (typeof draft.bodyText === 'string') {
        setBodyText(draft.bodyText);
      }
      if (typeof draft.recipientsPath === 'string') {
        setRecipientsPath(draft.recipientsPath);
      }
      if (typeof draft.attachmentsText === 'string') {
        setAttachmentsText(draft.attachmentsText);
      }
    }
    setDraftHydrated(true);
  }, []);

  useEffect(() => {
    if (!draftHydrated) {
      return;
    }
    saveDraft({
      senderEmail,
      senderName,
      smtpProvider,
      smtpHost,
      smtpPort,
      subject,
      bodyText,
      recipientsPath,
      attachmentsText,
    });
  }, [
    attachmentsText,
    bodyText,
    draftHydrated,
    recipientsPath,
    senderEmail,
    senderName,
    smtpProvider,
    smtpHost,
    smtpPort,
    subject,
  ]);

  const ensureRuntimeReady = () => {
    if (!runtimeStatus?.ready) {
      message.error('请先完成 Python 运行时设置');
      return false;
    }
    return true;
  };

  const ensureSmtpReady = () => {
    if (!smtpHost.trim()) {
      message.error('请先填写 SMTP Host');
      return false;
    }
    if (!smtpPort || smtpPort <= 0) {
      message.error('请先填写 SMTP 端口');
      return false;
    }
    if (!effectiveSmtpUsername) {
      message.error('请先填写发件邮箱');
      return false;
    }
    return true;
  };

  const validateSmtpForTest = (): string | null => {
    if (!smtpHost.trim()) {
      return '请先填写 SMTP Host';
    }
    if (!smtpPort || smtpPort <= 0) {
      return '请先填写 SMTP 端口';
    }
    if (!effectiveSmtpUsername) {
      return '请先填写发件邮箱';
    }
    if (!smtpPassword) {
      return '请先填写 SMTP 密码 / 授权码';
    }
    return null;
  };

  const handlePickPythonBinary = async () => {
    if (!isTauriRuntime) {
      message.info('浏览器模式下请手动输入路径');
      return;
    }
    const selected = await open({
      multiple: false,
      directory: false,
      title: '选择 Python 可执行文件',
    });
    if (typeof selected === 'string' && selected.trim()) {
      setRuntimeBusy(true);
      try {
        const status = await setRuntimePython(selected.trim());
        setRuntimeStatus(status);
        setRuntimePath(status.executable_path ?? selected.trim());
        message.success('Python 路径已保存');
      } catch (error) {
        message.error(toErrMsg(error, '保存运行时路径失败'));
      } finally {
        setRuntimeBusy(false);
      }
    }
  };

  const handlePickRecipientsFile = async () => {
    if (!isTauriRuntime) {
      message.info('浏览器模式下请手动输入路径');
      return;
    }
    const selected = await open({
      multiple: false,
      directory: false,
      title: '选择收件人文件（json / xlsx）',
      filters: [{ name: 'Recipients', extensions: ['json', 'xlsx', 'xls'] }],
    });
    const paths = normalizeDialogSelection(selected);
    if (paths.length > 0) {
      setRecipientsPath(paths[0]);
    }
  };

  const appendAttachmentPaths = (paths: string[]) => {
    const existing = attachmentsText
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
    const merged = Array.from(new Set([...existing, ...paths]));
    setAttachmentsText(merged.join('\n'));
  };

  const handlePickAttachments = async () => {
    if (!isTauriRuntime) {
      message.info('浏览器模式下请手动输入路径');
      return;
    }
    const selected = await open({
      multiple: true,
      directory: false,
      title: '选择附件（可多选）',
    });
    const paths = normalizeDialogSelection(selected);
    if (paths.length > 0) {
      appendAttachmentPaths(paths);
    }
  };

  const handleAutoDetectRuntime = async () => {
    setRuntimeBusy(true);
    try {
      const status = await autoDetectRuntime();
      setRuntimeStatus(status);
      setRuntimePath(status.executable_path ?? '');
      message.success('Python 运行时配置成功');
    } catch (error) {
      message.error(toErrMsg(error, '自动检测 Python 失败'));
    } finally {
      setRuntimeBusy(false);
    }
  };

  const handleClearRuntime = async () => {
    setRuntimeBusy(true);
    try {
      const status = await clearRuntimePython();
      setRuntimeStatus(status);
      setRuntimePath(status.executable_path ?? '');
      message.success('已清除运行时配置');
    } catch (error) {
      message.error(toErrMsg(error, '清除运行时配置失败'));
    } finally {
      setRuntimeBusy(false);
    }
  };

  const handleLoadRecipients = async () => {
    if (!ensureRuntimeReady()) {
      return;
    }
    try {
      const result = await loadRecipients(recipientsPath);
      setRecipients(result.recipientsPreview);
      message.success(
        `导入成功：有效 ${result.stats.valid_rows} 条，重复 ${result.stats.duplicate_rows} 条，空行 ${result.stats.empty_rows} 条`,
      );
    } catch (error) {
      message.error(toErrMsg(error, '导入失败'));
    }
  };

  const handleTestSmtp = async () => {
    if (isTestingSmtp) {
      return;
    }
    const validationError = validateSmtpForTest();
    if (validationError) {
      setSmtpTestState('error');
      setSmtpTestElapsedSec(0);
      setSmtpTestMessage(validationError);
      message.error(validationError);
      return;
    }
    const startedAt = performance.now();
    try {
      flushSync(() => {
        setIsTestingSmtp(true);
        setSmtpTestState('testing');
        setSmtpTestElapsedSec(0);
        setSmtpTestMessage('正在测试 SMTP 连接...');
      });
      message.open({
        key: SMTP_TEST_MESSAGE_KEY,
        type: 'loading',
        content: '正在测试 SMTP 连接...',
        duration: 0,
      });
      if (smtpTestTickerRef.current !== null) {
        window.clearInterval(smtpTestTickerRef.current);
        smtpTestTickerRef.current = null;
      }
      smtpTestTickerRef.current = window.setInterval(() => {
        setSmtpTestElapsedSec((performance.now() - startedAt) / 1000);
      }, 120);
      await testSmtp({
        host: smtpHost,
        port: smtpPort,
        username: effectiveSmtpUsername,
        password: smtpPassword,
        use_ssl: effectiveSmtpSecurity === 'ssl',
        use_starttls: effectiveSmtpSecurity === 'starttls',
        timeout_sec: SMTP_TEST_TIMEOUT_SEC,
      });
      const elapsedSec = (performance.now() - startedAt) / 1000;
      const successMsg = `SMTP 连接测试成功（${elapsedSec.toFixed(1)}s）`;
      message.success({
        key: SMTP_TEST_MESSAGE_KEY,
        content: successMsg,
      });
      setSmtpTestState('success');
      setSmtpTestElapsedSec(elapsedSec);
      setSmtpTestMessage(successMsg);
    } catch (error) {
      const elapsedSec = (performance.now() - startedAt) / 1000;
      const errMsg = toErrMsg(error, 'SMTP 连接测试失败');
      const finalErrorMsg = `${errMsg}（${elapsedSec.toFixed(1)}s）`;
      message.error({
        key: SMTP_TEST_MESSAGE_KEY,
        content: finalErrorMsg,
      });
      setSmtpTestState('error');
      setSmtpTestElapsedSec(elapsedSec);
      setSmtpTestMessage(finalErrorMsg);
      console.error('[SMTP Test]', error);
    } finally {
      if (smtpTestTickerRef.current !== null) {
        window.clearInterval(smtpTestTickerRef.current);
        smtpTestTickerRef.current = null;
      }
      setIsTestingSmtp(false);
    }
  };

  const handleEvent = (event: WorkerEvent) => {
    if (event.type === 'job_started') {
      setSummary({ total: event.total, success: 0, failed: 0, skipped: 0 });
      setFailures([]);
      setCurrentStatus(`任务已启动，总计 ${event.total} 封`);
      return;
    }

    if (event.type === 'recipient_started') {
      setCurrentStatus(`正在发送：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'recipient_sent') {
      setSummary((prev) => ({ ...prev, success: prev.success + 1 }));
      setCurrentStatus(`发送成功：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'recipient_failed') {
      setSummary((prev) => ({ ...prev, failed: prev.failed + 1 }));
      setFailures((prev) => [...prev, { email: event.email, name: event.name, error: event.error }]);
      setCurrentStatus(`发送失败：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'recipient_skipped') {
      setSummary((prev) => ({ ...prev, skipped: prev.skipped + 1 }));
      setCurrentStatus(`已跳过：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'job_finished') {
      setSummary({ total: event.total, success: event.success, failed: event.failed, skipped: event.skipped });
      setFailures(event.failures);
      setCurrentStatus('发送任务完成');
      setIsSending(false);
      return;
    }

    if (event.type === 'job_cancelled') {
      setSummary({ total: event.total, success: event.success, failed: event.failed, skipped: event.skipped });
      setCurrentStatus('任务已取消');
      setIsSending(false);
      return;
    }

    if (event.type === 'error') {
      setCurrentStatus(`任务错误：${event.error}`);
      setIsSending(false);
      return;
    }
  };

  const buildSendPayload = (): SendPayload => ({
    sender: {
      email: senderEmail,
      name: senderName,
    },
    smtp: {
      host: smtpHost,
      port: smtpPort,
      username: effectiveSmtpUsername,
      password: smtpPassword,
      use_ssl: effectiveSmtpSecurity === 'ssl',
      use_starttls: effectiveSmtpSecurity === 'starttls',
      timeout_sec: 30,
    },
    template: {
      subject,
      body_text: bodyText,
    },
    recipients,
    attachments: attachmentList,
    options: {
      min_delay_sec: minDelaySec,
      max_delay_sec: maxDelaySec,
      randomize_order: true,
      retry_count: 3,
      add_teacher_suffix: true,
      skip_sent: skipSent,
    },
    paths: {
      log_file: 'email_log.txt',
      sent_store_file: 'sent_records.jsonl',
    },
  });

  const handleStartSend = async () => {
    if (isSending) {
      return;
    }
    if (!senderEmail) {
      message.error('请先填写发件邮箱');
      return;
    }
    if (!ensureSmtpReady()) {
      return;
    }
    if (!ensureRuntimeReady()) {
      return;
    }
    if (recipients.length === 0) {
      message.error('请先导入收件人数据');
      return;
    }

    setIsSending(true);
    setCurrentStatus('正在启动发送任务...');
    setFailures([]);
    try {
      await startSend(buildSendPayload(), handleEvent);
    } catch (error) {
      setIsSending(false);
      message.error(toErrMsg(error, '启动任务失败'));
    }
  };

  const handleCancelSend = async () => {
    if (!isSending) {
      return;
    }
    try {
      await cancelSend();
    } catch {
      // Worker may have already exited
    }
  };

  const handleClearSentRecords = async () => {
    try {
      await clearSentRecords();
      message.success('已清除发送记录');
    } catch (error) {
      message.error(toErrMsg(error, '清除发送记录失败'));
    }
  };

  const handleSmtpProviderChange = (providerKey: string) => {
    setSmtpProvider(providerKey);
    if (providerKey === SMTP_PROVIDER_CUSTOM_KEY) {
      setSmtpHost('');
      setSmtpPort(0);
      return;
    }
    const preset = SMTP_PROVIDER_PRESET_MAP[providerKey];
    if (!preset) {
      return;
    }
    setSmtpHost(preset.host);
    setSmtpPort(preset.port);
  };

  const handleResetDraft = () => {
    const confirmed = window.confirm('确定重置当前本地草稿配置吗？该操作不会删除 runtime 安装。');
    if (!confirmed) {
      return;
    }
    setSenderEmail('');
    setSenderName('');
    setSmtpProvider(DEFAULT_SMTP_PROVIDER);
    setSmtpHost(DEFAULT_SMTP_HOST);
    setSmtpPort(DEFAULT_SMTP_PORT);
    setSmtpPassword('');
    setSubject(DEFAULT_SUBJECT);
    setBodyText(DEFAULT_BODY_TEXT);
    setRecipientsPath(DEFAULT_RECIPIENT_PATH);
    setRecipients([]);
    setAttachmentsText('');
    window.localStorage.removeItem(APP_DRAFT_STORAGE_KEY);
    message.success('已重置本地草稿配置');
  };

  return (
    <div className="page-shell">
      <div className="page-glow" />
      <Card className="main-card" bordered={false}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div className="header-block">
            <Title level={3} style={{ margin: 0 }}>
              批量邮件发送客户端
            </Title>
            <Text type="secondary">M3 进行中：首启 Python runtime 引导 + Worker 协议联调</Text>
            <Space>
              <Button onClick={handleResetDraft}>重置本地草稿</Button>
            </Space>
          </div>

          <Collapse
            activeKey={runtimePanelOpen ? ['runtime'] : []}
            onChange={(keys) => setRuntimePanelOpen((keys as string[]).includes('runtime'))}
            items={[{
              key: 'runtime',
              label: (
                <Space size={8}>
                  <span style={{ fontWeight: 500 }}>Python 运行时</span>
                  {runtimeStatus ? (
                    <Tag color={runtimeStatus.ready ? (runtimeStatus.source === 'system' ? 'blue' : 'success') : 'warning'} style={{ margin: 0 }}>
                      {runtimeStatus.ready
                        ? `就绪 · ${runtimeStatus.version ?? runtimeStatus.source}`
                        : '未配置'}
                    </Tag>
                  ) : (
                    <Tag style={{ margin: 0 }}>检测中…</Tag>
                  )}
                </Space>
              ),
              children: (
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  {runtimeStatus && (
                    <Alert
                      type={runtimeStatus.ready ? (runtimeStatus.source === 'system' ? 'info' : 'success') : 'warning'}
                      showIcon
                      message={runtimeStatus.ready ? 'Python 运行时已就绪' : '需要先配置 Python 运行时'}
                      description={`来源：${runtimeStatus.source}${runtimeStatus.version ? ` ｜ ${runtimeStatus.version}` : ''} ｜ ${runtimeStatus.message}`}
                    />
                  )}
                  <Row gutter={12} align="middle">
                    <Col xs={24} md={18}>
                      <Input
                        value={runtimePath}
                        readOnly
                        placeholder="尚未配置，请选择文件或点击自动安装"
                      />
                    </Col>
                    <Col xs={24} md={6}>
                      <Button block loading={runtimeBusy} onClick={() => void handlePickPythonBinary()}>
                        选择 Python 文件
                      </Button>
                    </Col>
                  </Row>

                  <Button type="primary" block loading={runtimeBusy} onClick={() => void handleAutoDetectRuntime()}>
                    自动安装 Python（推荐）
                  </Button>

                  <Space>
                    <Button onClick={refreshRuntimeStatus}>刷新检测</Button>
                    <Button danger onClick={handleClearRuntime}>清除配置</Button>
                  </Space>
                </Space>
              ),
            }]}
          />

          <Tabs
            defaultActiveKey="sender"
            items={[
              {
                key: 'sender',
                label: '发件人设置',
                children: (
                  <Form
                    layout="horizontal"
                    labelCol={{ flex: '6.5em' }}
                    wrapperCol={{ flex: 1 }}
                    labelAlign="left"
                    colon={false}
                    style={{ width: '100%' }}
                  >
                    <Form.Item label="邮箱类型" required style={{ marginBottom: 10 }}>
                      <Select
                        value={smtpProvider}
                        options={SMTP_PROVIDER_OPTIONS}
                        onChange={(value) => handleSmtpProviderChange(String(value))}
                      />
                    </Form.Item>

                    <Form.Item label="发件邮箱" required style={{ marginBottom: 10 }}>
                      <Input
                        placeholder="example@163.com"
                        value={senderEmail}
                        onChange={(event) => setSenderEmail(event.target.value)}
                      />
                    </Form.Item>

                    <Form.Item label="授权码" required style={{ marginBottom: 10 }}>
                      <Input.Password
                        placeholder={selectedSmtpPreset ? `${selectedSmtpPreset.label}需要授权码登录 SMTP` : '授权码（无密码可留空）'}
                        value={smtpPassword}
                        onChange={(event) => setSmtpPassword(event.target.value)}
                      />
                    </Form.Item>

                    <Form.Item label="发件人姓名" required style={{ marginBottom: 10 }}>
                      <Input
                        placeholder="收件方显示的发送人名称"
                        value={senderName}
                        onChange={(event) => setSenderName(event.target.value)}
                      />
                    </Form.Item>

                    <Form.Item label=" " style={{ marginBottom: 10 }}>
                      {selectedSmtpPreset ? (
                        <Alert type="info" showIcon message={selectedSmtpPreset.authHint} />
                      ) : (
                        // 自定义模式：显示自定义 SMTP 设置
                        <Card size="small" title="自定义 SMTP">
                          <Form
                            layout="horizontal"
                            labelCol={{ flex: '6.5em' }}
                            wrapperCol={{ flex: 1 }}
                            colon={false}
                          >
                            <Form.Item label="SMTP Host" required style={{ marginBottom: 8 }}>
                              <Input
                                value={smtpHost}
                                onChange={(event) => setSmtpHost(event.target.value)}
                                placeholder="例如 smtp.example.com"
                              />
                            </Form.Item>
                            <Form.Item label="端口" required style={{ marginBottom: 8 }}>
                              <InputNumber
                                value={smtpPort > 0 ? smtpPort : null}
                                onChange={(value) => setSmtpPort(value ?? 0)}
                                min={1}
                                max={65535}
                                placeholder="例如 465"
                                style={{ width: '100%' }}
                              />
                            </Form.Item>
                            <Form.Item label=" " style={{ marginBottom: 0 }}>
                              <Alert type="info" showIcon message="SSL：端口 465；STARTTLS：端口 587" />
                            </Form.Item>
                          </Form>
                        </Card>
                      )}
                    </Form.Item>

                    <Form.Item label=" " style={{ marginBottom: 0 }}>
                      <Space>
                        <Button
                          loading={isTestingSmtp}
                          onClick={handleTestSmtp}
                        >
                          测试连接
                        </Button>
                        {selectedSmtpPreset && (
                          <Tag color="blue">{effectiveSmtpSecurity.toUpperCase()} · 端口 {smtpPort}</Tag>
                        )}
                      </Space>
                      {smtpTestState !== 'idle' && (
                        <Alert
                          style={{ marginTop: 10 }}
                          showIcon
                          icon={smtpTestState === 'testing' ? <LoadingOutlined spin /> : undefined}
                          type={toSmtpTestAlertType(smtpTestState)}
                          message={
                            smtpTestState === 'testing'
                              ? `正在测试 SMTP 连接（${smtpTestElapsedSec.toFixed(1)}s）`
                              : smtpTestMessage
                          }
                          description={
                            smtpTestState === 'testing'
                              ? '已发起连接测试，请等待服务商握手返回...'
                              : undefined
                          }
                        />
                      )}
                    </Form.Item>
                  </Form>
                ),
              },
              {
                key: 'recipients',
                label: '收件人列表',
                children: (
                  <Space direction="vertical" size={18} style={{ width: '100%' }}>
                    <Row gutter={16}>
                      <Col xs={24} md={18}>
                        <Form.Item label="收件人文件路径（json / xlsx）" required>
                          <Input value={recipientsPath} onChange={(event) => setRecipientsPath(event.target.value)} />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={6}>
                        <Form.Item label="操作">
                          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                            <Button onClick={handlePickRecipientsFile}>选择文件</Button>
                            <Button type="default" onClick={handleLoadRecipients}>
                              解析文件
                            </Button>
                          </Space>
                        </Form.Item>
                      </Col>
                    </Row>

                    <Table<Recipient>
                      size="small"
                      rowKey={(row) => row.email}
                      columns={recipientsColumns}
                      dataSource={recipients}
                      pagination={{ pageSize: 6 }}
                    />
                  </Space>
                ),
              },
              {
                key: 'content',
                label: '邮件内容',
                children: (
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Form layout="vertical" colon={false} style={{ width: '100%' }}>
                      <Form.Item label="邮件主题" required style={{ marginBottom: 10 }}>
                        <Input value={subject} onChange={(event) => setSubject(event.target.value)} />
                      </Form.Item>
                      <Form.Item
                        label="正文模板"
                        required
                        style={{ marginBottom: 0 }}
                      >
                        <Input.TextArea rows={8} value={bodyText} onChange={(event) => setBodyText(event.target.value)} />
                      </Form.Item>
                    </Form>

                    <Card size="small" title="正文预览（基于第一位收件人）">
                      <Input.TextArea value={previewBody} autoSize={{ minRows: 3, maxRows: 8 }} readOnly />
                    </Card>

                    <Card
                      size="small"
                      title="附件"
                      extra={
                        <Space size={6}>
                          <Button size="small" onClick={handlePickAttachments}>选择</Button>
                          <Button size="small" onClick={() => setAttachmentsText('')}>清空</Button>
                        </Space>
                      }
                    >
                      <Input.TextArea
                        rows={2}
                        value={attachmentsText}
                        onChange={(event) => setAttachmentsText(event.target.value)}
                        placeholder={'attachments/resume.pdf\nattachments/transcript.pdf'}
                      />
                    </Card>

                    <div style={{ paddingTop: 4 }}>
                      <Space direction="vertical" size={8} style={{ width: '100%' }}>
                        <Space wrap>
                          <Button type="primary" size="large" loading={isSending} onClick={handleStartSend}>
                            开始发送
                          </Button>
                          <Button danger disabled={!isSending} onClick={handleCancelSend}>
                            取消任务
                          </Button>
                          <Checkbox checked={skipSent} onChange={(e) => setSkipSent(e.target.checked)} disabled={isSending}>跳过已发送</Checkbox>
                          <Button size="small" disabled={isSending} onClick={handleClearSentRecords}>
                            清除发送记录
                          </Button>
                        </Space>

                        <Space wrap align="center">
                          <Text type="secondary" style={{ fontSize: 12 }}>发送间隔（秒）：</Text>
                          <InputNumber
                            size="small"
                            min={0}
                            max={maxDelaySec}
                            value={minDelaySec}
                            onChange={(v) => setMinDelaySec(v ?? 0)}
                            disabled={isSending}
                            style={{ width: 70 }}
                          />
                          <Text type="secondary" style={{ fontSize: 12 }}>~</Text>
                          <InputNumber
                            size="small"
                            min={minDelaySec}
                            max={600}
                            value={maxDelaySec}
                            onChange={(v) => setMaxDelaySec(v ?? 0)}
                            disabled={isSending}
                            style={{ width: 70 }}
                          />
                        </Space>

                        <Progress percent={progressPercent} status={isSending ? 'active' : 'normal'} style={{ marginBottom: 0 }} />

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>{currentStatus}</Text>
                          <Space size={4}>
                            <Tag color="green">成功 {summary.success}</Tag>
                            <Tag color="red">失败 {summary.failed}</Tag>
                            <Tag color="gold">跳过 {summary.skipped}</Tag>
                            <Tag color="blue">总计 {summary.total}</Tag>
                          </Space>
                        </div>
                      </Space>
                    </div>

                    {failures.length > 0 && (
                      <Card size="small" title="失败明细">
                        <Table
                          size="small"
                          rowKey={(row) => `${row.email}-${row.error}`}
                          columns={failureColumns}
                          dataSource={failures}
                          pagination={{ pageSize: 5 }}
                        />
                      </Card>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      </Card>
    </div>
  );
}

export default function RootApp() {
  return (
    <App>
      <AppContent />
    </App>
  );
}
