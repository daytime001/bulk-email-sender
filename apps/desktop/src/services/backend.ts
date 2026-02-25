import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

import type { LoadRecipientsResult, Recipient, RuntimeStatus, SendPayload, SmtpPayload, WorkerEvent } from '../types';

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
        invalid_rows: 0,
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

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      ready: true,
      source: 'mock',
      executable_path: 'python3',
      version: 'Python 3.x (mock)',
      message: '浏览器开发模式，默认使用 mock runtime',
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
      message: '浏览器开发模式，已模拟保存 runtime',
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
      message: '浏览器开发模式，已模拟清除 runtime 配置',
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
      message: '浏览器开发模式，已模拟导入运行时压缩包',
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
      message: '浏览器开发模式，已模拟自动安装 runtime',
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
      message: '浏览器开发模式，已模拟自动检测 Python',
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
  let cursor = 0;
  let success = 0;
  let failed = 0;
  const failures: Array<{ email: string; name: string; error: string }> = [];

  onEvent({ type: 'job_accepted', job_id: jobId });
  onEvent({ type: 'job_started', job_id: jobId, total: recipients.length });

  const timer = window.setInterval(() => {
    if (cursor >= recipients.length) {
      window.clearInterval(timer);
      onEvent({
        type: 'job_finished',
        job_id: jobId,
        success,
        failed,
        skipped: 0,
        total: recipients.length,
        failures,
      });
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
  }, 650);

  return async () => {
    window.clearInterval(timer);
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
