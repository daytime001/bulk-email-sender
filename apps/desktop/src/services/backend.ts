import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

import type {
  AppDraft,
  AppPaths,
  LoadRecipientsResult,
  Recipient,
  RuntimeStatus,
  SendPayload,
  SmtpPayload,
  WorkerEvent,
} from '../types';

const WORKER_EVENT_CHANNEL = 'worker-event';

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

function randomJobId(): string {
  return `job-${Math.random().toString(36).slice(2, 10)}`;
}

export async function loadRecipients(path: string): Promise<LoadRecipientsResult> {
  if (!isTauriRuntime()) {
    const preview: Recipient[] = [
      { email: 'teacher1@example.com', name: '张教授' },
      { email: 'teacher2@example.com', name: '李教授' },
      { email: 'teacher3@example.com', name: '王教授' },
    ];
    return {
      stats: {
        total_rows: preview.length,
        valid_rows: preview.length,
        sendable_rows: preview.length,
        invalid_rows: 0,
        invalid_email_rows: 0,
        missing_name_rows: 0,
        duplicate_rows: 0,
        empty_rows: 0,
      },
      recipientsPreview: preview,
    };
  }

  const event = (await invoke('load_recipients', { path })) as WorkerEvent;
  if (event.type === 'error') {
    throw new Error(event.error);
  }
  if (event.type !== 'recipients_loaded') {
    throw new Error(`Unexpected response type: ${event.type}`);
  }

  return {
    stats: event.stats,
    recipientsPreview: event.recipients_preview,
  };
}

export async function testSmtp(payload: SmtpPayload): Promise<void> {
  if (!isTauriRuntime()) {
    if (!payload.username || !payload.password || !payload.host) {
      throw new Error('请先填写 SMTP 配置后再测试');
    }
    return;
  }

  const event = (await invoke('test_smtp', { payload })) as WorkerEvent;
  if (event.type === 'error') {
    throw new Error(event.error);
  }
  if (event.type !== 'smtp_test_succeeded') {
    throw new Error(`Unexpected response type: ${event.type}`);
  }
}

export async function startSend(
  payload: SendPayload,
  onEvent: (event: WorkerEvent) => void,
): Promise<() => Promise<void>> {
  const effectivePayload: SendPayload = {
    ...payload,
    job_id: payload.job_id ?? randomJobId(),
  };

  if (!isTauriRuntime()) {
    return createMockSendingFlow(effectivePayload, onEvent);
  }

  let dispose: (() => void) | null = null;
  dispose = await listen<WorkerEvent>(WORKER_EVENT_CHANNEL, (event) => {
    onEvent(event.payload);
    if (
      event.payload.type === 'job_finished' ||
      event.payload.type === 'job_cancelled' ||
      event.payload.type === 'error'
    ) {
      dispose?.();
      dispose = null;
    }
  });

  try {
    await invoke('start_send', { payload: effectivePayload });
  } catch (error) {
    dispose?.();
    dispose = null;
    throw error;
  }

  return async () => {
    await invoke('cancel_send');
    dispose?.();
    dispose = null;
  };
}

export async function cancelSend(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke('cancel_send');
}

export async function clearSentRecords(): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke('clear_sent_records');
}

export async function getAppPaths(): Promise<AppPaths> {
  if (!isTauriRuntime()) {
    return {
      data_dir: '.',
      sent_store_file: 'sent_records.jsonl',
      sent_store_text_file: 'sent_records.txt',
      log_file: 'email_log.txt',
      app_draft_file: 'app_draft.json',
    };
  }
  return (await invoke('get_app_paths')) as AppPaths;
}

export async function setDataDir(path: string): Promise<AppPaths> {
  if (!isTauriRuntime()) {
    return getAppPaths();
  }
  return (await invoke('set_data_dir', { path })) as AppPaths;
}

export async function loadAppDraft(): Promise<Partial<AppDraft>> {
  if (!isTauriRuntime()) {
    const raw = window.localStorage.getItem('bulk-email-sender:draft:v1');
    if (!raw) {
      return {};
    }
    try {
      return JSON.parse(raw) as Partial<AppDraft>;
    } catch {
      return {};
    }
  }
  return (await invoke('load_app_draft')) as Partial<AppDraft>;
}

export async function saveAppDraft(payload: AppDraft): Promise<void> {
  if (!isTauriRuntime()) {
    window.localStorage.setItem('bulk-email-sender:draft:v1', JSON.stringify(payload));
    return;
  }
  await invoke('save_app_draft', { payload });
}

export async function openPath(path: string): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  await invoke('open_path', { path });
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'mock',
      executable_path: 'python3',
      version: 'Python 3.x (mock)',
      message: '当前为预览环境，使用模拟 Python 运行时',
    };
  }
  return (await invoke('get_runtime_status')) as RuntimeStatus;
}

export async function setRuntimePython(path: string): Promise<RuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'mock',
      executable_path: path || 'python3',
      version: 'Python 3.x (mock)',
      message: '当前为预览环境，已保存 Python 路径（模拟）',
    };
  }
  return (await invoke('set_runtime_python', { path })) as RuntimeStatus;
}

export async function clearRuntimePython(): Promise<RuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'mock',
      executable_path: 'python3',
      version: 'Python 3.x (mock)',
      message: '当前为预览环境，已清除 Python 配置（模拟）',
    };
  }
  return (await invoke('clear_runtime_python')) as RuntimeStatus;
}

export async function installRuntimeFromArchive(archivePath: string): Promise<RuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'mock',
      executable_path: 'python3',
      version: 'Python 3.x (mock)',
      message: '当前为预览环境，已导入运行时压缩包（模拟）',
    };
  }
  return (await invoke('install_runtime_from_archive', { archivePath })) as RuntimeStatus;
}

export async function autoInstallRuntime(manifestUrl: string): Promise<RuntimeStatus> {
  const manifestUrls = manifestUrl
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);

  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'mock',
      executable_path: 'python3',
      version: 'Python 3.x (mock)',
      message: '当前为预览环境，已完成自动安装（模拟）',
    };
  }
  return (await invoke('auto_install_runtime', {
    payload: {
      manifest_url: manifestUrl,
      manifest_urls: manifestUrls,
    },
  })) as RuntimeStatus;
}

export async function autoDetectRuntime(): Promise<RuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'configured',
      executable_path: 'python3',
      version: 'Python 3.x (mock)',
      message: '当前为预览环境，已完成自动检测（模拟）',
    };
  }
  return (await invoke('auto_detect_runtime')) as RuntimeStatus;
}

async function createMockSendingFlow(
  payload: SendPayload,
  onEvent: (event: WorkerEvent) => void,
): Promise<() => Promise<void>> {
  const jobId = payload.job_id ?? randomJobId();
  const recipients = payload.recipients;
  const minDelay = Math.max(0, Math.min(payload.options.min_delay_sec, payload.options.max_delay_sec));
  const maxDelay = Math.max(0, Math.max(payload.options.min_delay_sec, payload.options.max_delay_sec));
  let cursor = 0;
  let success = 0;
  let failed = 0;
  let cancelled = false;
  let timer: number | null = null;
  const failures: Array<{ email: string; name: string; error: string }> = [];

  onEvent({ type: 'job_accepted', job_id: jobId });
  onEvent({ type: 'job_started', job_id: jobId, total: recipients.length });

  const pickDelay = () => {
    if (maxDelay <= minDelay) {
      return minDelay;
    }
    return Math.floor(Math.random() * (maxDelay - minDelay + 1)) + minDelay;
  };

  const emitFinished = () => {
    onEvent({
      type: 'job_finished',
      job_id: jobId,
      success,
      failed,
      skipped: 0,
      total: recipients.length,
      failures,
    });
  };

  const schedule = (callback: () => void, delayMs: number) => {
    if (cancelled) {
      return;
    }
    timer = window.setTimeout(callback, delayMs);
  };

  const runNext = () => {
    if (cancelled) {
      return;
    }
    if (cursor >= recipients.length) {
      emitFinished();
      return;
    }

    const target = recipients[cursor];
    const index = cursor + 1;
    onEvent({
      type: 'recipient_started',
      job_id: jobId,
      index,
      email: target.email,
      name: target.name,
    });

    if (target.email.includes('fail')) {
      failed += 1;
      const failure = { email: target.email, name: target.name, error: '模拟发送失败' };
      failures.push(failure);
      onEvent({
        type: 'recipient_failed',
        job_id: jobId,
        index,
        email: target.email,
        name: target.name,
        error: failure.error,
      });
    } else {
      success += 1;
      onEvent({
        type: 'recipient_sent',
        job_id: jobId,
        index,
        email: target.email,
        name: target.name,
      });
    }

    cursor += 1;
    if (cursor >= recipients.length) {
      emitFinished();
      return;
    }

    const delaySec = pickDelay();
    if (delaySec <= 0) {
      schedule(runNext, 200);
      return;
    }

    let remainingSec = delaySec;
    const currentIndex = index;
    const waitTick = () => {
      if (cancelled) {
        return;
      }
      if (remainingSec <= 0) {
        schedule(runNext, 200);
        return;
      }
      onEvent({
        type: 'inter_send_wait',
        job_id: jobId,
        index: currentIndex,
        next_index: currentIndex + 1,
        delay_sec: delaySec,
        remaining_sec: remainingSec,
      });
      remainingSec -= 1;
      schedule(waitTick, 1000);
    };
    waitTick();
  };

  schedule(runNext, 100);

  return async () => {
    cancelled = true;
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    onEvent({
      type: 'job_cancelled',
      job_id: jobId,
      success,
      failed,
      skipped: 0,
      total: recipients.length,
    });
  };
}
