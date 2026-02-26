import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  App,
  Card,
  Space,
  Tabs,
  Typography,
} from 'antd';
import { open } from '@tauri-apps/plugin-dialog';

import {
  autoDetectRuntime,
  cancelSend,
  clearRuntimePython,
  clearSentRecords,
  getAppPaths,
  getRuntimeStatus,
  loadRecipients,
  loadAppDraft,
  openPath,
  saveAppDraft,
  setDataDir,
  setRuntimePython,
  startSend,
  testSmtp,
} from './services/backend';
import { EmailContentWorkspace } from './features/email-content/EmailContentWorkspace';
import { RecipientsWorkspace } from './features/recipients/RecipientsWorkspace';
import { SettingsWorkspace } from './features/settings/SettingsWorkspace';
import { SenderSettingsWorkspace } from './features/sender-settings/SenderSettingsWorkspace';
import type { AppPaths, Recipient, RecipientStats, RuntimeStatus, SendPayload, WorkerEvent } from './types';
import './App.css';

const { Title, Text } = Typography;
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
const DEFAULT_BODY_TEXT = `尊敬的{teacher_name}老师：

\u3000\u3000您好！我是来自XXX大学XXX专业的XXX，预计能够以专业第X的成绩获得推免资格。冒昧致信，请问您是否还有空余的招生名额？下面是我的一些基本情况介绍，随信附上个人简历与成绩单。

\u3000\u3000【请在此处填写您的个人介绍内容】

\u3000\u3000感谢拨冗垂阅，如有不妥望您海涵，诚盼老师的回复！

{sender_name}
{send_date}`;

interface SendSummary {
  total: number;
  success: number;
  failed: number;
  skipped: number;
}

interface WaitInfo {
  remainingSec: number;
  delaySec: number;
  nextIndex: number;
}

type SmtpTestState = 'idle' | 'testing' | 'success' | 'error';

const DEFAULT_RECIPIENT_PATH = 'examples/recipients/recipients_sample.json';
const REQUIRED_BODY_TOKENS = ['{teacher_name}', '{sender_name}', '{send_date}'] as const;

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
  const [recipientsStats, setRecipientsStats] = useState<RecipientStats | null>(null);

  const [attachmentsText, setAttachmentsText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isTestingSmtp, setIsTestingSmtp] = useState(false);
  const [smtpTestState, setSmtpTestState] = useState<SmtpTestState>('idle');
  const [smtpTestMessage, setSmtpTestMessage] = useState('');
  const [smtpTestElapsedSec, setSmtpTestElapsedSec] = useState(0);
  const [currentStatus, setCurrentStatus] = useState('等待开始发送');
  const [summary, setSummary] = useState<SendSummary>({ total: 0, success: 0, failed: 0, skipped: 0 });
  const [waitInfo, setWaitInfo] = useState<WaitInfo | null>(null);
  const [failures, setFailures] = useState<Array<{ email: string; name: string; error: string }>>([]);
  const [skipSent, setSkipSent] = useState(true);
  const [minDelaySec, setMinDelaySec] = useState(5);
  const [maxDelaySec, setMaxDelaySec] = useState(10);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const smtpTestTickerRef = useRef<number | null>(null);
  const [runtimePath, setRuntimePath] = useState('');
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [dataPaths, setDataPaths] = useState<AppPaths | null>(null);
  const [dataDirInput, setDataDirInput] = useState('');
  const [dataPathBusy, setDataPathBusy] = useState(false);
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

  const doneCount = useMemo(
    () => summary.success + summary.failed + summary.skipped,
    [summary.failed, summary.skipped, summary.success],
  );

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

  const refreshAppPaths = useCallback(async () => {
    try {
      const paths = await getAppPaths();
      setDataPaths(paths);
      setDataDirInput(paths.data_dir);
    } catch (error) {
      message.error(toErrMsg(error, '读取数据目录失败'));
    }
  }, [message]);

  useEffect(() => {
    void refreshRuntimeStatus();
  }, [refreshRuntimeStatus]);

  useEffect(() => {
    void refreshAppPaths();
  }, [refreshAppPaths]);

  useEffect(() => {
    const hydrateDraft = async () => {
      try {
        const draft = await loadAppDraft();
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
        if (typeof draft.smtpPassword === 'string') {
          setSmtpPassword(draft.smtpPassword);
        }
      } catch (error) {
        message.error(toErrMsg(error, '读取草稿配置失败'));
      } finally {
        setDraftHydrated(true);
      }
    };

    void hydrateDraft();
  }, [message]);

  useEffect(() => {
    if (!draftHydrated) {
      return;
    }
    void saveAppDraft({
      senderEmail,
      senderName,
      smtpProvider,
      smtpHost,
      smtpPort,
      smtpPassword,
      subject,
      bodyText,
      recipientsPath,
      attachmentsText,
    }).catch((error: unknown) => {
      message.error(toErrMsg(error, '保存草稿配置失败'));
    });
  }, [
    attachmentsText,
    bodyText,
    draftHydrated,
    message,
    recipientsPath,
    senderEmail,
    senderName,
    smtpProvider,
    smtpHost,
    smtpPort,
    smtpPassword,
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

  const handlePickDataDir = async () => {
    if (!isTauriRuntime) {
      message.info('浏览器模式下请手动输入路径');
      return;
    }
    const selected = await open({
      multiple: false,
      directory: true,
      title: '选择记录与配置保存目录',
    });
    const paths = normalizeDialogSelection(selected);
    if (paths.length > 0) {
      setDataDirInput(paths[0]);
    }
  };

  const handleApplyDataDir = async () => {
    setDataPathBusy(true);
    try {
      const paths = await setDataDir(dataDirInput.trim());
      setDataPaths(paths);
      setDataDirInput(paths.data_dir);
      message.success('数据目录已保存');
    } catch (error) {
      message.error(toErrMsg(error, '保存数据目录失败'));
    } finally {
      setDataPathBusy(false);
    }
  };

  const handleResetDataDir = async () => {
    setDataPathBusy(true);
    try {
      const paths = await setDataDir('');
      setDataPaths(paths);
      setDataDirInput(paths.data_dir);
      message.success('已恢复默认数据目录');
    } catch (error) {
      message.error(toErrMsg(error, '恢复默认目录失败'));
    } finally {
      setDataPathBusy(false);
    }
  };

  const handleOpenDataDir = async () => {
    if (!dataPaths) {
      return;
    }
    try {
      await openPath(dataPaths.data_dir);
    } catch (error) {
      message.error(toErrMsg(error, '打开数据目录失败'));
    }
  };

  const handleOpenReadableRecord = async () => {
    if (!dataPaths) {
      return;
    }
    try {
      await openPath(dataPaths.sent_store_text_file);
    } catch (error) {
      message.error(toErrMsg(error, '打开可读记录失败'));
    }
  };

  const handleOpenDraftConfig = async () => {
    if (!dataPaths) {
      return;
    }
    try {
      await openPath(dataPaths.app_draft_file);
    } catch (error) {
      message.error(toErrMsg(error, '打开配置文件失败'));
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
      setRecipientsStats(result.stats);
      message.success(
        `导入成功：总数 ${result.stats.total_rows} 条，可发送 ${result.stats.sendable_rows} 条，无效邮箱 ${result.stats.invalid_email_rows} 条，缺姓名 ${result.stats.missing_name_rows} 条`,
      );
    } catch (error) {
      setRecipientsStats(null);
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
      setWaitInfo(null);
      setFailures([]);
      setCurrentStatus(`任务已启动，总计 ${event.total} 封`);
      return;
    }

    if (event.type === 'recipient_started') {
      setWaitInfo(null);
      setCurrentStatus(`正在发送：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'recipient_sent') {
      setWaitInfo(null);
      setSummary((prev) => ({ ...prev, success: prev.success + 1 }));
      setCurrentStatus(`发送成功：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'recipient_failed') {
      setWaitInfo(null);
      setSummary((prev) => ({ ...prev, failed: prev.failed + 1 }));
      setFailures((prev) => [...prev, { email: event.email, name: event.name, error: event.error }]);
      setCurrentStatus(`发送失败：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'recipient_skipped') {
      setWaitInfo(null);
      setSummary((prev) => ({ ...prev, skipped: prev.skipped + 1 }));
      setCurrentStatus(`已跳过：${event.name} (${event.email})`);
      return;
    }

    if (event.type === 'inter_send_wait') {
      setWaitInfo({
        remainingSec: event.remaining_sec,
        delaySec: event.delay_sec,
        nextIndex: event.next_index,
      });
      setCurrentStatus(`间隔等待中：${event.remaining_sec}s 后发送第 ${event.next_index} 封（本轮 ${event.delay_sec}s）`);
      return;
    }

    if (event.type === 'job_finished') {
      setWaitInfo(null);
      setSummary({ total: event.total, success: event.success, failed: event.failed, skipped: event.skipped });
      setFailures(event.failures);
      setCurrentStatus('发送任务完成');
      setIsSending(false);
      return;
    }

    if (event.type === 'job_cancelled') {
      setWaitInfo(null);
      setSummary({ total: event.total, success: event.success, failed: event.failed, skipped: event.skipped });
      setCurrentStatus('任务已取消');
      setIsSending(false);
      return;
    }

    if (event.type === 'error') {
      setWaitInfo(null);
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
      skip_sent: skipSent,
    },
    paths: {
      log_file: dataPaths?.log_file ?? 'email_log.txt',
      sent_store_file: dataPaths?.sent_store_file ?? 'sent_records.jsonl',
      sent_store_text_file: dataPaths?.sent_store_text_file ?? 'sent_records.txt',
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
    if (!senderName.trim()) {
      message.error('请先填写发件人姓名');
      return;
    }
    if (!ensureSmtpReady()) {
      return;
    }
    if (!ensureRuntimeReady()) {
      return;
    }
    const missingBodyTokens = REQUIRED_BODY_TOKENS.filter((token) => !bodyText.includes(token));
    if (missingBodyTokens.length > 0) {
      message.error(`邮件正文缺少固定占位符：${missingBodyTokens.join('、')}`);
      return;
    }
    if (recipients.length === 0) {
      message.error('请先导入收件人数据');
      return;
    }
    if (isTauriRuntime && !dataPaths) {
      message.error('正在初始化数据目录，请稍后重试');
      return;
    }

    setIsSending(true);
    setWaitInfo(null);
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
      message.success('已清除发送记录（jsonl + txt）');
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
    setRecipientsStats(null);
    setAttachmentsText('');
    message.success('已重置本地草稿配置');
  };

  return (
    <div className="page-shell">
      <div className="page-glow" />
      <Card className="main-card" bordered={false}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div className="header-block">
            <Title level={3} style={{ margin: 0 }}>
              Bulk-Email-Sender
            </Title>
            <Text type="secondary">版权所属：极客昼语</Text>
          </div>

          <Tabs
            defaultActiveKey="settings"
            items={[
              {
                key: 'settings',
                label: '设置',
                children: (
                  <SettingsWorkspace
                    runtimeStatus={runtimeStatus}
                    runtimePath={runtimePath}
                    runtimeBusy={runtimeBusy}
                    dataDirInput={dataDirInput}
                    dataPathBusy={dataPathBusy}
                    dataPaths={dataPaths}
                    onResetDraft={handleResetDraft}
                    onPickPythonBinary={() => void handlePickPythonBinary()}
                    onAutoDetectRuntime={() => void handleAutoDetectRuntime()}
                    onRefreshRuntimeStatus={() => void refreshRuntimeStatus()}
                    onClearRuntime={() => void handleClearRuntime()}
                    onDataDirInputChange={setDataDirInput}
                    onPickDataDir={() => void handlePickDataDir()}
                    onApplyDataDir={() => void handleApplyDataDir()}
                    onResetDataDir={() => void handleResetDataDir()}
                    onOpenDataDir={() => void handleOpenDataDir()}
                    onOpenReadableRecord={() => void handleOpenReadableRecord()}
                    onOpenDraftConfig={() => void handleOpenDraftConfig()}
                  />
                ),
              },
              {
                key: 'sender',
                label: '发件人设置',
                children: (
                  <SenderSettingsWorkspace
                    smtpProvider={smtpProvider}
                    smtpProviderOptions={SMTP_PROVIDER_OPTIONS}
                    senderEmail={senderEmail}
                    senderName={senderName}
                    smtpPassword={smtpPassword}
                    smtpHost={smtpHost}
                    smtpPort={smtpPort}
                    effectiveSmtpSecurity={effectiveSmtpSecurity}
                    selectedSmtpPreset={selectedSmtpPreset ? {
                      label: selectedSmtpPreset.label,
                      authHint: selectedSmtpPreset.authHint,
                    } : null}
                    isTestingSmtp={isTestingSmtp}
                    smtpTestState={smtpTestState}
                    smtpTestElapsedSec={smtpTestElapsedSec}
                    smtpTestMessage={smtpTestMessage}
                    onSmtpProviderChange={handleSmtpProviderChange}
                    onSenderEmailChange={setSenderEmail}
                    onSenderNameChange={setSenderName}
                    onSmtpPasswordChange={setSmtpPassword}
                    onSmtpHostChange={setSmtpHost}
                    onSmtpPortChange={setSmtpPort}
                    onTestSmtp={() => void handleTestSmtp()}
                  />
                ),
              },
              {
                key: 'recipients',
                label: '收件人列表',
                children: (
                  <RecipientsWorkspace
                    recipientsPath={recipientsPath}
                    recipients={recipients}
                    recipientsStats={recipientsStats}
                    onRecipientsPathChange={setRecipientsPath}
                    onPickRecipientsFile={() => void handlePickRecipientsFile()}
                    onLoadRecipients={() => void handleLoadRecipients()}
                  />
                ),
              },
              {
                key: 'content',
                label: '邮件内容',
                children: (
                  <EmailContentWorkspace
                    subject={subject}
                    bodyText={bodyText}
                    attachmentsText={attachmentsText}
                    isSending={isSending}
                    skipSent={skipSent}
                    minDelaySec={minDelaySec}
                    maxDelaySec={maxDelaySec}
                    progressPercent={progressPercent}
                    currentStatus={currentStatus}
                    doneCount={doneCount}
                    summary={summary}
                    waitInfo={waitInfo}
                    failures={failures}
                    onSubjectChange={setSubject}
                    onBodyTextChange={setBodyText}
                    onAttachmentsTextChange={setAttachmentsText}
                    onPickAttachments={() => void handlePickAttachments()}
                    onClearAttachments={() => setAttachmentsText('')}
                    onStartSend={() => void handleStartSend()}
                    onCancelSend={() => void handleCancelSend()}
                    onSkipSentChange={setSkipSent}
                    onClearSentRecords={() => void handleClearSentRecords()}
                    onMinDelaySecChange={setMinDelaySec}
                    onMaxDelaySecChange={setMaxDelaySec}
                  />
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
