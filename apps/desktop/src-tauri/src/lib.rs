use lettre::transport::smtp::authentication::Credentials;
use lettre::transport::smtp::client::{Tls, TlsParameters};
use lettre::{SmtpTransport};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read, Write};
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};
use walkdir::WalkDir;
use zip::ZipArchive;
use sha2::{Digest, Sha256};

const WORKER_EVENT_CHANNEL: &str = "worker-event";
const RUNTIME_CONFIG_RELATIVE_PATH: &str = "runtime/python_runtime.json";
const APP_SETTINGS_RELATIVE_PATH: &str = "settings/app_settings.json";
const APP_DRAFT_RELATIVE_PATH: &str = "config/app_draft.json";
const DEFAULT_DATA_DIR_NAME: &str = "Bulk-Email-Sender";
const SAMPLE_RECIPIENTS_RESOURCE_DIR: &str = "examples/recipients";
const SAMPLE_RECIPIENT_JSON_FILE: &str = "recipients_sample.json";
const SAMPLE_RECIPIENT_XLSX_FILE: &str = "recipients_sample.xlsx";
const PYTHON_MIN_MAJOR: u32 = 3;
const PYTHON_MIN_MINOR: u32 = 9;

#[derive(Default)]
struct WorkerState {
    child: Mutex<Option<Child>>,
}

#[derive(Deserialize, Serialize)]
struct SmtpPayload {
    host: String,
    port: u16,
    username: String,
    password: String,
    use_ssl: bool,
    use_starttls: bool,
    timeout_sec: u32,
}

#[tauri::command]
fn load_recipients(app: AppHandle, path: String) -> Result<Value, String> {
    run_worker_request(json!({
        "type": "load_recipients",
        "protocol": 1,
        "payload": { "path": path }
    }), &app)
}

#[tauri::command]
async fn test_smtp(payload: SmtpPayload) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let creds = Credentials::new(payload.username.clone(), payload.password.clone());

        let tls = if payload.use_ssl || payload.use_starttls {
            let tls_params = TlsParameters::builder(payload.host.clone())
                .build()
                .map_err(|e| format!("TLS 配置失败: {e}"))?;
            if payload.use_ssl {
                Tls::Wrapper(tls_params)
            } else {
                Tls::Required(tls_params)
            }
        } else {
            Tls::None
        };

        let transport = SmtpTransport::builder_dangerous(&payload.host)
            .port(payload.port)
            .tls(tls)
            .credentials(creds)
            .timeout(Some(Duration::from_secs(payload.timeout_sec.into())))
            .build();

        // Retry once after 2 s: some SMTP servers (e.g. 126.com) apply a
        // cold-start delay on the first connection and temporarily reject it.
        let mut last_err: Option<String> = None;
        for attempt in 0..2u32 {
            match transport.test_connection() {
                Ok(_) => return Ok(json!({ "type": "smtp_test_succeeded" })),
                Err(e) => {
                    last_err = Some(format!("SMTP 连接失败: {e}"));
                    if attempt == 0 {
                        std::thread::sleep(Duration::from_secs(2));
                    }
                }
            }
        }
        Err(last_err.unwrap())
    })
    .await
    .map_err(|e| format!("SMTP test task failed: {e}"))?
}

#[tauri::command]
fn start_send(
    app: AppHandle,
    state: State<'_, WorkerState>,
    payload: Value,
) -> Result<Value, String> {
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "failed to acquire worker state lock".to_string())?;

    if let Some(child) = guard.as_mut() {
        if child
            .try_wait()
            .map_err(|err| err.to_string())?
            .is_none()
        {
            return Err("another job is running".to_string());
        }
        *guard = None;
    }

    let mut command = worker_command(&app)?;
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|err| format!("failed to spawn worker: {err}"))?;

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "failed to open worker stdin".to_string())?;
    let request = json!({
        "type": "start_send",
        "protocol": 1,
        "payload": payload
    });
    writeln!(stdin, "{}", request)
        .and_then(|_| stdin.flush())
        .map_err(|err| format!("failed to write worker request: {err}"))?;
    // Drop stdin to send EOF — the Python worker loop exits after the job thread finishes.

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "failed to open worker stdout".to_string())?;

    spawn_event_forwarder(app, stdout);

    let response = json!({ "type": "job_accepted" });
    *guard = Some(child);
    Ok(response)
}

#[tauri::command]
fn cancel_send(state: State<'_, WorkerState>) -> Result<(), String> {
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "failed to acquire worker state lock".to_string())?;

    if let Some(child) = guard.as_mut() {
        child
            .kill()
            .map_err(|err| format!("failed to kill worker process: {err}"))?;
    }

    *guard = None;
    Ok(())
}

#[tauri::command]
fn clear_sent_records(app: AppHandle) -> Result<(), String> {
    let paths = resolve_app_paths(&app)?;
    for target in [paths.sent_store_file, paths.sent_store_text_file] {
        let file = PathBuf::from(target);
        if file.exists() {
            fs::remove_file(&file)
                .map_err(|err| format!("failed to remove sent records: {err}"))?;
        }
    }
    Ok(())
}

#[tauri::command]
fn get_app_paths(app: AppHandle) -> Result<AppPaths, String> {
    resolve_app_paths(&app)
}

#[tauri::command]
fn set_data_dir(app: AppHandle, path: String) -> Result<AppPaths, String> {
    let mut settings = read_app_settings(&app)?;
    let trimmed = path.trim();
    if trimmed.is_empty() {
        settings.data_dir = None;
    } else {
        settings.data_dir = Some(trimmed.to_string());
    }
    write_app_settings(&app, &settings)?;
    resolve_app_paths(&app)
}

#[tauri::command]
fn load_app_draft(app: AppHandle) -> Result<Value, String> {
    let paths = resolve_app_paths(&app)?;
    let draft_path = PathBuf::from(paths.app_draft_file);
    if !draft_path.exists() {
        return Ok(json!({}));
    }
    let text = fs::read_to_string(&draft_path)
        .map_err(|err| format!("读取草稿配置失败: {err}"))?;
    serde_json::from_str(&text).map_err(|err| format!("草稿配置格式错误: {err}"))
}

#[tauri::command]
fn save_app_draft(app: AppHandle, payload: Value) -> Result<(), String> {
    if !payload.is_object() {
        return Err("草稿配置必须是 JSON 对象".to_string());
    }
    let paths = resolve_app_paths(&app)?;
    let draft_path = PathBuf::from(paths.app_draft_file);
    if let Some(parent) = draft_path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("创建草稿配置目录失败: {err}"))?;
    }
    let text = serde_json::to_string_pretty(&payload).map_err(|err| err.to_string())?;
    fs::write(draft_path, text).map_err(|err| format!("写入草稿配置失败: {err}"))
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("路径不能为空".to_string());
    }

    let raw_target = PathBuf::from(trimmed);
    let target = if raw_target.exists() {
        raw_target
    } else if let Some(parent) = raw_target.parent() {
        if parent.exists() {
            parent.to_path_buf()
        } else {
            return Err("路径不存在，请先保存一次配置或发送记录".to_string());
        }
    } else {
        return Err("路径不存在，请先保存一次配置或发送记录".to_string());
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut c = Command::new("open");
        c.arg(&target);
        c
    };
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut c = Command::new("explorer");
        c.arg(&target);
        c
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut c = Command::new("xdg-open");
        c.arg(&target);
        c
    };

    let status = command
        .status()
        .map_err(|err| format!("打开路径失败: {err}"))?;
    if !status.success() {
        return Err("打开路径失败：系统命令返回非 0 状态码".to_string());
    }
    Ok(())
}

#[derive(Serialize, Default)]
struct RuntimeStatus {
    ready: bool,
    source: String,
    executable_path: Option<String>,
    version: Option<String>,
    message: String,
}

#[derive(Serialize, Deserialize, Default)]
struct RuntimeConfig {
    python_path: Option<String>,
}

#[derive(Serialize, Deserialize, Default)]
struct AppSettings {
    data_dir: Option<String>,
}

#[derive(Serialize)]
struct AppPaths {
    data_dir: String,
    sent_store_file: String,
    sent_store_text_file: String,
    log_file: String,
    app_draft_file: String,
}

#[derive(Deserialize, Default)]
struct RuntimeManifest {
    bundles: Vec<RuntimeManifestBundle>,
}

#[derive(Deserialize, Clone)]
struct RuntimeManifestBundle {
    target: String,
    url: String,
    sha256: Option<String>,
    urls: Option<Vec<String>>,
}

#[derive(Deserialize)]
struct AutoInstallPayload {
    manifest_url: Option<String>,
    manifest_urls: Option<Vec<String>>,
}

#[tauri::command]
fn get_runtime_status(app: AppHandle) -> Result<RuntimeStatus, String> {
    Ok(resolve_runtime_status(&app))
}

#[tauri::command]
fn set_runtime_python(app: AppHandle, path: String) -> Result<RuntimeStatus, String> {
    let candidate = PathBuf::from(path.trim());
    if !candidate.exists() {
        return Err("指定的 Python 可执行文件不存在".to_string());
    }

    let version = probe_python_version(&candidate)
        .ok_or_else(|| "指定路径不是可用的 Python 运行时".to_string())?;
    if !is_supported_python_version(&version) {
        return Err(format!(
            "Python 版本过低，当前为 `{version}`，要求 >= {}.{}",
            PYTHON_MIN_MAJOR, PYTHON_MIN_MINOR
        ));
    }

    let mut config = read_runtime_config(&app)?;
    config.python_path = Some(candidate.to_string_lossy().to_string());
    write_runtime_config(&app, &config)?;

    Ok(RuntimeStatus {
        ready: true,
        source: "configured".to_string(),
        executable_path: Some(candidate.to_string_lossy().to_string()),
        version: Some(version),
        message: "Python 运行时已保存".to_string(),
    })
}

#[tauri::command]
fn clear_runtime_python(app: AppHandle) -> Result<RuntimeStatus, String> {
    let mut config = read_runtime_config(&app)?;
    config.python_path = None;
    write_runtime_config(&app, &config)?;
    Ok(resolve_runtime_status(&app))
}

#[tauri::command]
fn install_runtime_from_archive(app: AppHandle, archive_path: String) -> Result<RuntimeStatus, String> {
    let source_path = PathBuf::from(archive_path.trim());
    if !source_path.exists() {
        return Err("运行时压缩包不存在".to_string());
    }

    install_runtime_from_archive_internal(&app, &source_path, "archive")
}

#[tauri::command]
fn auto_install_runtime(
    app: AppHandle,
    payload: Option<AutoInstallPayload>,
) -> Result<RuntimeStatus, String> {
    let payload = payload.unwrap_or(AutoInstallPayload {
        manifest_url: None,
        manifest_urls: None,
    });
    let manifest_sources = collect_manifest_sources(payload.manifest_url, payload.manifest_urls);
    if manifest_sources.is_empty() {
        return Err("未配置 runtime manifest 地址，请先填写 manifest URL".to_string());
    }

    let target = runtime_target_key(std::env::consts::OS, std::env::consts::ARCH);
    let mut manifest_errors: Vec<String> = Vec::new();
    let mut selected_bundle: Option<RuntimeManifestBundle> = None;

    for source in &manifest_sources {
        if let Err(err) = validate_remote_url_scheme(source, "manifest") {
            manifest_errors.push(err);
            continue;
        }
        match load_runtime_manifest(source) {
            Ok(manifest) => {
                if let Some(bundle) = select_manifest_bundle(&manifest, &target) {
                    selected_bundle = Some(bundle.clone());
                    break;
                }
                manifest_errors.push(format!("manifest `{source}` 未包含平台 `{target}`"));
            }
            Err(err) => {
                manifest_errors.push(format!("manifest `{source}` 加载失败：{err}"));
            }
        }
    }

    let bundle = selected_bundle.ok_or_else(|| format!("自动安装失败：{}", manifest_errors.join(" | ")))?;

    let runtime_root = runtime_root_dir(&app)?;
    let download_dir = runtime_root.join("downloads");
    fs::create_dir_all(&download_dir).map_err(|err| format!("创建下载目录失败: {err}"))?;
    let archive_path = download_dir.join(format!("python-runtime-{target}.zip"));
    let download_urls = resolve_bundle_download_urls(&bundle);
    for url in &download_urls {
        validate_remote_url_scheme(url, "runtime 包下载地址")?;
    }
    if download_urls.iter().any(|url| is_remote_url(url)) && !bundle_has_checksum(&bundle) {
        return Err("远程 runtime 包必须提供 sha256 校验值".to_string());
    }
    let mut download_errors: Vec<String> = Vec::new();
    let mut downloaded = false;
    for url in download_urls {
        match download_bundle_to_path(&url, &archive_path) {
            Ok(_) => {
                downloaded = true;
                break;
            }
            Err(err) => download_errors.push(format!("`{url}` 下载失败：{err}")),
        }
    }
    if !downloaded {
        return Err(format!("runtime 包下载失败：{}", download_errors.join(" | ")));
    }

    if let Some(checksum) = &bundle.sha256 {
        if let Err(err) = verify_sha256_checksum(&archive_path, checksum) {
            let _ = fs::remove_file(&archive_path);
            return Err(err);
        }
    }

    install_runtime_from_archive_internal(&app, &archive_path, "download")
}

// ── uv / Python 自动安装常量 ───────────────────────────────────────────────
const UV_INSTALL_RETRIES: u32 = 3;
const UV_RETRY_SLEEP_SECS: u64 = 4;

/// 自动探测并配置 Python 运行时：
///   1. 查找已有 uv → 查找 / 安装 Python 3.11
///   2. uv 不存在 → 自动安装 uv（带重试），再执行 1
///   3. 全部失败 → 回退系统 python3 / python
#[tauri::command]
fn auto_detect_runtime(app: AppHandle) -> Result<RuntimeStatus, String> {
    let mut uv_install_err: Option<String> = None;

    let uv_opt = find_uv_executable().or_else(|| {
        match install_uv() {
            Ok(p) => Some(p),
            Err(e) => { uv_install_err = Some(e); None }
        }
    });

    if let Some(uv) = uv_opt {
        // 1a. 查找 uv 已管理的 Python（任意 >=3.9）
        if let Ok(out) = Command::new(&uv).args(["python", "find"]).output() {
            if out.status.success() {
                let p = String::from_utf8_lossy(&out.stdout).trim().to_string();
                if !p.is_empty() {
                    let c = PathBuf::from(&p);
                    if let Some(ver) = probe_python_version(&c) {
                        if is_supported_python_version(&ver) {
                            return save_configured_runtime(&app, c, ver);
                        }
                    }
                }
            }
        }

        // 1b. 通过 uv 安装 Python 3.11，最多重试 UV_INSTALL_RETRIES 次
        let mut py_ok = false;
        for attempt in 1..=UV_INSTALL_RETRIES {
            if let Ok(out) = Command::new(&uv).args(["python", "install", "3.11"]).output() {
                if out.status.success() { py_ok = true; break; }
            }
            if attempt < UV_INSTALL_RETRIES {
                std::thread::sleep(std::time::Duration::from_secs(UV_RETRY_SLEEP_SECS));
            }
        }
        if py_ok {
            if let Ok(out) = Command::new(&uv).args(["python", "find", "3.11"]).output() {
                if out.status.success() {
                    let p = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    if !p.is_empty() {
                        let c = PathBuf::from(&p);
                        if let Some(ver) = probe_python_version(&c) {
                            if is_supported_python_version(&ver) {
                                return save_configured_runtime(&app, c, ver);
                            }
                        }
                    }
                }
            }
        }
        // uv python install 失败（如网络差），继续回退
    }

    // 2. 回退到系统 Python
    #[cfg(target_os = "windows")]
    let candidates = ["python", "python3"];
    #[cfg(not(target_os = "windows"))]
    let candidates = ["python3", "python"];

    for name in candidates {
        let exe = PathBuf::from(name);
        if let Some(ver) = probe_python_version(&exe) {
            if is_supported_python_version(&ver) {
                return save_configured_runtime(&app, exe, ver);
            }
        }
    }

    // 3. 全部失败：给出有针对性的错误提示
    let base = "未找到可用的 Python 运行时（需 ≥3.9）。";
    let hint = "https://docs.astral.sh/uv/getting-started/installation/";
    if let Some(uv_err) = uv_install_err {
        Err(format!(
            "{base}\n\n安装 uv 失败：{uv_err}\n\n建议：\n① 检查网络后点击「自动安装 Python」重试\n② 或访问 {hint} 手动安装 uv\n③ 或点击「选择 Python 文件」指定已有 Python"
        ))
    } else {
        Err(format!(
            "{base}\n\n建议：\n① 检查网络后点击「自动安装 Python」重试\n② 或访问 {hint} 安装 uv\n③ 或点击「选择 Python 文件」指定已有 Python"
        ))
    }
}

/// 查找已安装的 uv 可执行文件（PATH + 平台默认路径）。
fn find_uv_executable() -> Option<PathBuf> {
    // 优先 PATH
    if Command::new("uv").arg("--version").output().map(|o| o.status.success()).unwrap_or(false) {
        return Some(PathBuf::from("uv"));
    }
    for path in uv_default_paths() {
        if path.exists()
            && Command::new(&path).arg("--version").output().map(|o| o.status.success()).unwrap_or(false)
        {
            return Some(path);
        }
    }
    None
}

/// 平台相关的 uv 默认安装位置。
fn uv_default_paths() -> Vec<PathBuf> {
    let mut paths: Vec<PathBuf> = Vec::new();
    #[cfg(target_os = "windows")]
    {
        for var in ["USERPROFILE", "APPDATA", "LOCALAPPDATA"] {
            if let Ok(base) = std::env::var(var) {
                let b = PathBuf::from(base);
                paths.push(b.join(".cargo").join("bin").join("uv.exe"));
                paths.push(b.join(".local").join("bin").join("uv.exe"));
                paths.push(b.join("uv").join("bin").join("uv.exe"));
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(home) = std::env::var("HOME") {
            let h = PathBuf::from(home);
            paths.push(h.join(".local").join("bin").join("uv"));
            paths.push(h.join(".cargo").join("bin").join("uv"));
        }
    }
    paths
}

/// 通过官方脚本自动安装 uv（跨平台，带重试），成功后返回可执行路径。
fn install_uv() -> Result<PathBuf, String> {
    let mut last_err = String::new();

    for attempt in 1..=UV_INSTALL_RETRIES {
        let ok = {
            #[cfg(target_os = "windows")]
            {
                Command::new("powershell")
                    .args([
                        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "irm https://astral.sh/uv/install.ps1 | iex",
                    ])
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .map(|s| s.success())
                    .unwrap_or(false)
            }
            #[cfg(not(target_os = "windows"))]
            {
                Command::new("sh")
                    .args(["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"])
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .map(|s| s.success())
                    .unwrap_or(false)
            }
        };

        if ok {
            // 安装成功，在默认路径中寻找
            if Command::new("uv").arg("--version").output().map(|o| o.status.success()).unwrap_or(false) {
                return Ok(PathBuf::from("uv"));
            }
            for p in uv_default_paths() {
                if p.exists() { return Ok(p); }
            }
            return Err("uv 安装完成，但未找到可执行文件，请重启应用后重试。".to_string());
        }

        last_err = format!("第 {attempt} 次安装失败");
        if attempt < UV_INSTALL_RETRIES {
            std::thread::sleep(std::time::Duration::from_secs(UV_RETRY_SLEEP_SECS));
        }
    }

    Err(format!(
        "{last_err}（共重试 {UV_INSTALL_RETRIES} 次）。\n请检查网络连接后重试，或手动安装：https://docs.astral.sh/uv/"
    ))
}

fn save_configured_runtime(app: &AppHandle, path: PathBuf, version: String) -> Result<RuntimeStatus, String> {
    let mut config = read_runtime_config(app)?;
    config.python_path = Some(path.to_string_lossy().to_string());
    write_runtime_config(app, &config)?;
    Ok(RuntimeStatus {
        ready: true,
        source: "configured".to_string(),
        executable_path: Some(path.to_string_lossy().to_string()),
        version: Some(version),
        message: "Python 运行时已就绪".to_string(),
    })
}

fn install_runtime_from_archive_internal(
    app: &AppHandle,
    source_path: &Path,
    source_label: &str,
) -> Result<RuntimeStatus, String> {
    if !source_path.exists() {
        return Err("运行时压缩包不存在".to_string());
    }

    let runtime_root = runtime_root_dir(app)?;
    fs::create_dir_all(&runtime_root).map_err(|err| format!("创建 runtime 根目录失败: {err}"))?;
    let staging_dir = runtime_root.join("python_staging");
    let active_dir = runtime_root.join("python");

    extract_zip_archive(source_path, &staging_dir)?;

    let staging_python = find_python_executable(&staging_dir)
        .ok_or_else(|| "压缩包中未找到可用 Python 可执行文件".to_string())?;
    let version = probe_python_version(&staging_python)
        .ok_or_else(|| "解压后的 Python 运行时不可执行".to_string())?;
    if !is_supported_python_version(&version) {
        return Err(format!(
            "压缩包中的 Python 版本过低，当前为 `{version}`，要求 >= {}.{}",
            PYTHON_MIN_MAJOR, PYTHON_MIN_MINOR
        ));
    }

    let relative_python = staging_python
        .strip_prefix(&staging_dir)
        .map_err(|err| format!("运行时路径解析失败: {err}"))?
        .to_path_buf();

    if active_dir.exists() {
        fs::remove_dir_all(&active_dir).map_err(|err| format!("清理旧运行时目录失败: {err}"))?;
    }
    fs::rename(&staging_dir, &active_dir).map_err(|err| format!("启用新运行时失败: {err}"))?;
    let active_python = active_dir.join(relative_python);

    let mut config = read_runtime_config(app)?;
    config.python_path = Some(active_python.to_string_lossy().to_string());
    write_runtime_config(app, &config)?;

    Ok(RuntimeStatus {
        ready: true,
        source: source_label.to_string(),
        executable_path: Some(active_python.to_string_lossy().to_string()),
        version: Some(version),
        message: "运行时导入成功".to_string(),
    })
}

fn spawn_event_forwarder(app: AppHandle, stdout: impl std::io::Read + Send + 'static) {
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(raw) => {
                    let parsed: Result<Value, _> = serde_json::from_str(&raw);
                    match parsed {
                        Ok(payload) => {
                            let _ = app.emit(WORKER_EVENT_CHANNEL, payload);
                        }
                        Err(err) => {
                            let _ = app.emit(
                                WORKER_EVENT_CHANNEL,
                                json!({ "type": "error", "error": format!("invalid worker payload: {err}") }),
                            );
                        }
                    }
                }
                Err(err) => {
                    let _ = app.emit(
                        WORKER_EVENT_CHANNEL,
                        json!({ "type": "error", "error": format!("worker stdout read failure: {err}") }),
                    );
                    break;
                }
            }
        }
    });
}

fn run_worker_request(request: Value, app: &AppHandle) -> Result<Value, String> {
    let mut command = worker_command(app)?;
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|err| format!("failed to spawn worker: {err}"))?;

    {
        // Take stdin out of child so it is dropped (closed) at end of scope.
        // This lets the Python worker see EOF and exit its input loop.
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| "failed to open worker stdin".to_string())?;

        writeln!(stdin, "{}", request)
            .and_then(|_| stdin.flush())
            .map_err(|err| format!("failed to write worker request: {err}"))?;
    }

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "failed to open worker stdout".to_string())?;
    let mut lines = BufReader::new(stdout).lines();

    let first_line = lines
        .next()
        .ok_or_else(|| "worker returned empty response".to_string())?
        .map_err(|err| format!("failed to read worker response: {err}"))?;

    let payload: Value =
        serde_json::from_str(&first_line).map_err(|err| format!("invalid worker response: {err}"))?;

    let _ = child.wait();
    Ok(payload)
}

fn worker_command(app: &AppHandle) -> Result<Command, String> {
    let worker_script = resolve_worker_script(app)?;
    let project_root = worker_script
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let use_uv = project_root.join("pyproject.toml").exists();

    if use_uv {
        if let Some(project_python) = find_project_python(&project_root) {
            let mut command = Command::new(project_python);
            command.arg(&worker_script);
            command.current_dir(&project_root);
            command.env("PYTHONPATH", &project_root);
            return Ok(command);
        }

        // Dev fallback: use "uv run python" to activate local project env.
        if let Some(uv) = find_uv_executable() {
            let mut command = Command::new(uv);
            command.args(["run", "python"]);
            command.arg(&worker_script);
            command.current_dir(&project_root);
            return Ok(command);
        }
    }

    // Fallback: use the configured Python binary directly.
    // Set CWD + PYTHONPATH so bulk_email_sender is importable; third-party deps
    // (openpyxl) may be absent in base Python – xlsx loading will fail gracefully.
    let runtime = resolve_python_runtime(app)
        .ok_or_else(|| "未找到可用 Python 运行时，请先在客户端完成 Python 运行时设置".to_string())?;
    let mut command = Command::new(runtime.executable_path);
    command.arg(worker_script);
    command.current_dir(&project_root);
    command.env("PYTHONPATH", &project_root);
    Ok(command)
}

fn find_project_python(project_root: &Path) -> Option<PathBuf> {
    let candidates = if cfg!(target_os = "windows") {
        vec![
            project_root.join(".venv").join("Scripts").join("python.exe"),
            project_root.join(".venv").join("python.exe"),
        ]
    } else {
        vec![
            project_root.join(".venv").join("bin").join("python3"),
            project_root.join(".venv").join("bin").join("python"),
        ]
    };

    for candidate in candidates {
        if !candidate.exists() {
            continue;
        }
        if let Some(version) = probe_python_version(&candidate) {
            if is_supported_python_version(&version) {
                return Some(candidate);
            }
        }
    }
    None
}

fn resolve_worker_script(app: &AppHandle) -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_candidates = vec![
        manifest_dir.join("../../..").join("worker.py"),
        manifest_dir.join("../..").join("worker.py"),
        manifest_dir.join("worker.py"),
    ];

    for candidate in &dev_candidates {
        if candidate.exists() {
            return candidate
                .canonicalize()
                .or_else(|_| Ok(candidate.clone()));
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let packaged_script = resource_dir.join("worker.py");
        if packaged_script.exists() {
            return Ok(packaged_script);
        }

        for entry in WalkDir::new(&resource_dir)
            .max_depth(4)
            .into_iter()
            .filter_map(Result::ok)
        {
            if entry.file_type().is_file() && entry.file_name() == "worker.py" {
                return Ok(entry.path().to_path_buf());
            }
        }
    }

    let searched = dev_candidates
        .iter()
        .map(|path| path.to_string_lossy().to_string())
        .collect::<Vec<String>>()
        .join(" | ");
    Err(format!("未找到 worker.py，请检查打包资源配置（已检查：{searched}）"))
}

fn resolve_runtime_status(app: &AppHandle) -> RuntimeStatus {
    if let Some(runtime) = resolve_python_runtime(app) {
        let message = if runtime.source == "system" {
            "检测到系统 Python，可直接使用".to_string()
        } else {
            "Python 运行时可用".to_string()
        };
        return RuntimeStatus {
            ready: true,
            source: runtime.source,
            executable_path: Some(runtime.executable_path.to_string_lossy().to_string()),
            version: Some(runtime.version),
            message,
        };
    }

    RuntimeStatus {
        ready: false,
        source: "none".to_string(),
        executable_path: None,
        version: None,
        message: "未检测到 Python 运行时，请导入运行时压缩包或手动指定可执行文件".to_string(),
    }
}

struct PythonRuntime {
    source: String,
    executable_path: PathBuf,
    version: String,
}

fn resolve_python_runtime(app: &AppHandle) -> Option<PythonRuntime> {
    if let Ok(config) = read_runtime_config(app) {
        if let Some(path) = config.python_path {
            let configured = PathBuf::from(path);
            if let Some(version) = probe_python_version(&configured) {
                if is_supported_python_version(&version) {
                    return Some(PythonRuntime {
                        source: "configured".to_string(),
                        executable_path: configured,
                        version,
                    });
                }
            }
        }
    }

    for candidate in ["python3", "python"] {
        let executable = PathBuf::from(candidate);
        if let Some(version) = probe_python_version(&executable) {
            if is_supported_python_version(&version) {
                return Some(PythonRuntime {
                    source: "system".to_string(),
                    executable_path: executable,
                    version,
                });
            }
        }
    }

    None
}

fn probe_python_version(path: &Path) -> Option<String> {
    let output = Command::new(path).arg("--version").output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let line = if !stdout.is_empty() { stdout } else { stderr };
    if line.is_empty() {
        return None;
    }
    if parse_python_version(&line).is_none() {
        return None;
    }
    Some(line)
}

fn parse_python_version(line: &str) -> Option<(u32, u32, u32)> {
    let normalized = line.trim();
    let payload = normalized.strip_prefix("Python ")?;
    let mut chunks = payload.split('.');
    let major = chunks.next()?.parse::<u32>().ok()?;
    let minor = chunks.next()?.parse::<u32>().ok()?;
    let patch = chunks
        .next()
        .unwrap_or("0")
        .split_whitespace()
        .next()
        .unwrap_or("0")
        .parse::<u32>()
        .ok()?;
    Some((major, minor, patch))
}

fn is_supported_python_version(line: &str) -> bool {
    let Some((major, minor, _patch)) = parse_python_version(line) else {
        return false;
    };
    major > PYTHON_MIN_MAJOR || (major == PYTHON_MIN_MAJOR && minor >= PYTHON_MIN_MINOR)
}

fn runtime_target_key(os: &str, arch: &str) -> String {
    format!("{os}-{arch}")
}

fn collect_manifest_sources(
    manifest_url: Option<String>,
    manifest_urls: Option<Vec<String>>,
) -> Vec<String> {
    let mut ordered: Vec<String> = Vec::new();

    if let Some(raw) = manifest_url {
        for item in raw.split(['\n', ',', ';']) {
            let trimmed = item.trim();
            if !trimmed.is_empty() && !ordered.iter().any(|existing| existing == trimmed) {
                ordered.push(trimmed.to_string());
            }
        }
    }

    if let Some(list) = manifest_urls {
        for item in list {
            let trimmed = item.trim();
            if !trimmed.is_empty() && !ordered.iter().any(|existing| existing == trimmed) {
                ordered.push(trimmed.to_string());
            }
        }
    }

    ordered
}

fn select_manifest_bundle<'a>(
    manifest: &'a RuntimeManifest,
    target: &str,
) -> Option<&'a RuntimeManifestBundle> {
    manifest
        .bundles
        .iter()
        .find(|item| item.target == target)
}

fn resolve_bundle_download_urls(bundle: &RuntimeManifestBundle) -> Vec<String> {
    let mut urls = vec![bundle.url.trim().to_string()];
    if let Some(extra) = &bundle.urls {
        for item in extra {
            let trimmed = item.trim();
            if !trimmed.is_empty() && !urls.iter().any(|existing| existing == trimmed) {
                urls.push(trimmed.to_string());
            }
        }
    }
    urls
}

fn bundle_has_checksum(bundle: &RuntimeManifestBundle) -> bool {
    bundle
        .sha256
        .as_ref()
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false)
}

fn is_remote_url(url: &str) -> bool {
    let trimmed = url.trim();
    trimmed.starts_with("http://") || trimmed.starts_with("https://")
}

fn validate_remote_url_scheme(url: &str, label: &str) -> Result<(), String> {
    let trimmed = url.trim();
    if trimmed.starts_with("http://") && !is_localhost_http_url(trimmed) {
        return Err(format!(
            "{label} 必须使用 https:// 或 file://（仅 localhost 允许 http://）：{trimmed}"
        ));
    }
    Ok(())
}

fn is_localhost_http_url(url: &str) -> bool {
    if !url.starts_with("http://") {
        return false;
    }
    let suffix = &url["http://".len()..];
    let host_port = suffix.split('/').next().unwrap_or_default();
    let authority = host_port.split('@').next_back().unwrap_or(host_port);
    let host = if let Some(ipv6) = authority.strip_prefix('[') {
        ipv6.split(']').next().unwrap_or_default().to_ascii_lowercase()
    } else {
        authority
            .split(':')
            .next()
            .unwrap_or(authority)
            .to_ascii_lowercase()
    };
    host == "localhost" || host == "127.0.0.1" || host == "::1"
}

fn load_runtime_manifest(manifest_url: &str) -> Result<RuntimeManifest, String> {
    let body = if manifest_url.starts_with("http://") || manifest_url.starts_with("https://") {
        reqwest::blocking::get(manifest_url)
            .map_err(|err| format!("下载 manifest 失败: {err}"))?
            .error_for_status()
            .map_err(|err| format!("manifest 响应异常: {err}"))?
            .text()
            .map_err(|err| format!("读取 manifest 内容失败: {err}"))?
    } else if manifest_url.starts_with("file://") {
        let path = manifest_url.trim_start_matches("file://");
        fs::read_to_string(path).map_err(|err| format!("读取本地 manifest 失败: {err}"))?
    } else {
        fs::read_to_string(manifest_url).map_err(|err| format!("读取 manifest 失败: {err}"))?
    };

    serde_json::from_str::<RuntimeManifest>(&body).map_err(|err| format!("manifest JSON 格式错误: {err}"))
}

fn download_bundle_to_path(url: &str, destination: &Path) -> Result<(), String> {
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("创建下载目录失败: {err}"))?;
    }

    if url.starts_with("http://") || url.starts_with("https://") {
        let mut response = reqwest::blocking::get(url)
            .map_err(|err| format!("下载 runtime 包失败: {err}"))?
            .error_for_status()
            .map_err(|err| format!("runtime 包响应异常: {err}"))?;
        let mut target = File::create(destination).map_err(|err| format!("创建下载文件失败: {err}"))?;
        std::io::copy(&mut response, &mut target).map_err(|err| format!("写入下载文件失败: {err}"))?;
        return Ok(());
    }

    let source_path = if url.starts_with("file://") {
        PathBuf::from(url.trim_start_matches("file://"))
    } else {
        PathBuf::from(url)
    };

    if !source_path.exists() {
        return Err("runtime 包地址无效，文件不存在".to_string());
    }
    fs::copy(source_path, destination).map_err(|err| format!("复制 runtime 包失败: {err}"))?;
    Ok(())
}

fn verify_sha256_checksum(path: &Path, expected: &str) -> Result<(), String> {
    let mut file = File::open(path).map_err(|err| format!("读取下载文件失败: {err}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 8192];
    loop {
        let size = file
            .read(&mut buffer)
            .map_err(|err| format!("读取下载文件失败: {err}"))?;
        if size == 0 {
            break;
        }
        hasher.update(&buffer[..size]);
    }
    let actual = format!("{:x}", hasher.finalize());
    let expected_trimmed = expected.trim().to_lowercase();
    if expected_trimmed.is_empty() {
        return Ok(());
    }
    if actual != expected_trimmed {
        return Err(format!(
            "runtime 包校验失败：期望 sha256={expected_trimmed}，实际 sha256={actual}"
        ));
    }
    Ok(())
}

fn runtime_config_path(app: &AppHandle) -> Result<PathBuf, String> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|err| format!("无法获取应用数据目录: {err}"))?;
    let config_path = app_data_dir.join(RUNTIME_CONFIG_RELATIVE_PATH);
    if let Some(parent) = config_path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("无法创建运行时配置目录: {err}"))?;
    }
    Ok(config_path)
}

fn read_runtime_config(app: &AppHandle) -> Result<RuntimeConfig, String> {
    let config_path = runtime_config_path(app)?;
    if !config_path.exists() {
        return Ok(RuntimeConfig::default());
    }

    let text = fs::read_to_string(config_path).map_err(|err| format!("读取运行时配置失败: {err}"))?;
    serde_json::from_str(&text).map_err(|err| format!("运行时配置格式错误: {err}"))
}

fn write_runtime_config(app: &AppHandle, config: &RuntimeConfig) -> Result<(), String> {
    let config_path = runtime_config_path(app)?;
    let text = serde_json::to_string_pretty(config).map_err(|err| err.to_string())?;
    fs::write(config_path, text).map_err(|err| format!("写入运行时配置失败: {err}"))
}

fn app_settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|err| format!("无法获取应用数据目录: {err}"))?;
    let settings_path = app_data_dir.join(APP_SETTINGS_RELATIVE_PATH);
    if let Some(parent) = settings_path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("无法创建应用设置目录: {err}"))?;
    }
    Ok(settings_path)
}

fn read_app_settings(app: &AppHandle) -> Result<AppSettings, String> {
    let settings_path = app_settings_path(app)?;
    if !settings_path.exists() {
        return Ok(AppSettings::default());
    }
    let text = fs::read_to_string(settings_path).map_err(|err| format!("读取应用设置失败: {err}"))?;
    serde_json::from_str(&text).map_err(|err| format!("应用设置格式错误: {err}"))
}

fn write_app_settings(app: &AppHandle, settings: &AppSettings) -> Result<(), String> {
    let settings_path = app_settings_path(app)?;
    let text = serde_json::to_string_pretty(settings).map_err(|err| err.to_string())?;
    fs::write(settings_path, text).map_err(|err| format!("写入应用设置失败: {err}"))
}

fn default_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(doc_dir) = app.path().document_dir() {
        return Ok(doc_dir.join(DEFAULT_DATA_DIR_NAME));
    }
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|err| format!("无法获取默认数据目录: {err}"))?;
    Ok(app_data_dir.join("user-data"))
}

fn resolve_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let settings = read_app_settings(app)?;
    let data_dir = match settings.data_dir {
        Some(path) if !path.trim().is_empty() => PathBuf::from(path),
        _ => default_data_dir(app)?,
    };
    fs::create_dir_all(&data_dir).map_err(|err| format!("无法创建数据目录: {err}"))?;
    Ok(data_dir)
}

fn resolve_app_paths(app: &AppHandle) -> Result<AppPaths, String> {
    let data_dir = resolve_data_dir(app)?;
    let records_dir = data_dir.join("records");
    let logs_dir = data_dir.join("logs");
    let config_dir = data_dir.join("config");
    fs::create_dir_all(&records_dir).map_err(|err| format!("创建 records 目录失败: {err}"))?;
    fs::create_dir_all(&logs_dir).map_err(|err| format!("创建 logs 目录失败: {err}"))?;
    fs::create_dir_all(&config_dir).map_err(|err| format!("创建 config 目录失败: {err}"))?;
    ensure_sample_recipient_files(app, &data_dir)?;

    Ok(AppPaths {
        data_dir: data_dir.to_string_lossy().to_string(),
        sent_store_file: records_dir
            .join("sent_records.jsonl")
            .to_string_lossy()
            .to_string(),
        sent_store_text_file: records_dir
            .join("sent_records.txt")
            .to_string_lossy()
            .to_string(),
        log_file: logs_dir.join("email_log.txt").to_string_lossy().to_string(),
        app_draft_file: data_dir
            .join(APP_DRAFT_RELATIVE_PATH)
            .to_string_lossy()
            .to_string(),
    })
}

fn ensure_sample_recipient_files(app: &AppHandle, data_dir: &Path) -> Result<(), String> {
    for file_name in [SAMPLE_RECIPIENT_JSON_FILE, SAMPLE_RECIPIENT_XLSX_FILE] {
        let target = data_dir.join(file_name);
        if target.exists() {
            continue;
        }

        let source = resolve_sample_recipient_source_path(app, file_name)
            .ok_or_else(|| format!("未找到内置示例文件资源: {file_name}"))?;
        fs::copy(&source, &target).map_err(|err| {
            format!(
                "复制内置示例文件失败: {} -> {} ({err})",
                source.to_string_lossy(),
                target.to_string_lossy()
            )
        })?;
    }
    Ok(())
}

fn resolve_sample_recipient_source_path(app: &AppHandle, file_name: &str) -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_candidate = manifest_dir
        .join("../../..")
        .join(SAMPLE_RECIPIENTS_RESOURCE_DIR)
        .join(file_name);
    if dev_candidate.exists() {
        if let Ok(canonical_path) = dev_candidate.canonicalize() {
            return Some(canonical_path);
        }
        return Some(dev_candidate);
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let direct = resource_dir
            .join(SAMPLE_RECIPIENTS_RESOURCE_DIR)
            .join(file_name);
        if direct.exists() {
            return Some(direct);
        }

        for entry in WalkDir::new(&resource_dir)
            .max_depth(6)
            .into_iter()
            .filter_map(Result::ok)
        {
            if entry.file_type().is_file() && entry.file_name().to_string_lossy() == file_name {
                return Some(entry.path().to_path_buf());
            }
        }
    }

    None
}

fn runtime_root_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_local_data_dir()
        .map_err(|err| format!("无法获取本地运行时目录: {err}"))?
        .join("runtime");
    Ok(root)
}

fn extract_zip_archive(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        fs::remove_dir_all(destination).map_err(|err| format!("清理临时目录失败: {err}"))?;
    }
    fs::create_dir_all(destination).map_err(|err| format!("创建临时目录失败: {err}"))?;

    let file = File::open(source).map_err(|err| format!("打开压缩包失败: {err}"))?;
    let mut archive = ZipArchive::new(file).map_err(|err| format!("读取压缩包失败: {err}"))?;
    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|err| format!("解压失败: {err}"))?;
        let Some(safe_name) = entry.enclosed_name().map(|path| path.to_owned()) else {
            continue;
        };
        let output_path = destination.join(safe_name);

        if entry.name().ends_with('/') {
            fs::create_dir_all(&output_path).map_err(|err| format!("创建目录失败: {err}"))?;
            continue;
        }

        if let Some(parent) = output_path.parent() {
            fs::create_dir_all(parent).map_err(|err| format!("创建目录失败: {err}"))?;
        }

        let mut output_file =
            File::create(&output_path).map_err(|err| format!("写入解压文件失败: {err}"))?;
        std::io::copy(&mut entry, &mut output_file).map_err(|err| format!("写入解压文件失败: {err}"))?;

        #[cfg(unix)]
        if let Some(mode) = entry.unix_mode() {
            let _ = fs::set_permissions(&output_path, fs::Permissions::from_mode(mode));
        }
    }
    Ok(())
}

fn find_python_executable(root: &Path) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    for entry in WalkDir::new(root)
        .into_iter()
        .filter_map(Result::ok)
    {
        if !entry.file_type().is_file() {
            continue;
        }
        let file_name = entry.file_name().to_string_lossy().to_lowercase();
        if file_name == "python3"
            || file_name == "python"
            || file_name == "python.exe"
        {
            candidates.push(entry.path().to_path_buf());
        }
    }

    candidates.sort_by_key(|path| {
        let depth = path.components().count();
        let file_name = path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("")
            .to_lowercase();
        let is_python3 = usize::from(file_name == "python3");
        let is_bin = usize::from(path.components().any(|component| component.as_os_str() == "bin"));
        (1 - is_python3, 1 - is_bin, depth)
    });
    candidates
        .into_iter()
        .find(|candidate| probe_python_version(candidate.as_path()).is_some())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(WorkerState::default())
        .invoke_handler(tauri::generate_handler![
            load_recipients,
            test_smtp,
            start_send,
            cancel_send,
            get_runtime_status,
            set_runtime_python,
            clear_runtime_python,
            install_runtime_from_archive,
            auto_install_runtime,
            auto_detect_runtime,
            clear_sent_records,
            get_app_paths,
            set_data_dir,
            load_app_draft,
            save_app_draft,
            open_path,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::{
        bundle_has_checksum, collect_manifest_sources, is_localhost_http_url, is_supported_python_version,
        parse_python_version, resolve_bundle_download_urls, runtime_target_key, select_manifest_bundle,
        validate_remote_url_scheme, RuntimeManifest, RuntimeManifestBundle,
    };

    #[test]
    fn parses_python_version_line() {
        let parsed = parse_python_version("Python 3.11.8");
        assert_eq!(parsed, Some((3, 11, 8)));
    }

    #[test]
    fn rejects_invalid_version_line() {
        assert_eq!(parse_python_version("v3.11.8"), None);
    }

    #[test]
    fn validates_supported_python_version() {
        assert!(is_supported_python_version("Python 3.11.8"));
        assert!(is_supported_python_version("Python 3.9.18"));
        assert!(!is_supported_python_version("Python 3.8.18"));
    }

    #[test]
    fn builds_runtime_target_key() {
        assert_eq!(runtime_target_key("macos", "aarch64"), "macos-aarch64");
        assert_eq!(runtime_target_key("windows", "x86_64"), "windows-x86_64");
    }

    #[test]
    fn selects_bundle_by_target() {
        let manifest = RuntimeManifest {
            bundles: vec![
                RuntimeManifestBundle {
                    target: "macos-aarch64".to_string(),
                    url: "https://cdn.example.com/mac.zip".to_string(),
                    sha256: Some("abc".to_string()),
                    urls: None,
                },
                RuntimeManifestBundle {
                    target: "windows-x86_64".to_string(),
                    url: "https://cdn.example.com/win.zip".to_string(),
                    sha256: None,
                    urls: None,
                },
            ],
        };

        let bundle = select_manifest_bundle(&manifest, "windows-x86_64").expect("bundle should exist");
        assert_eq!(bundle.url, "https://cdn.example.com/win.zip");
    }

    #[test]
    fn collects_manifest_sources_with_dedup() {
        let sources = collect_manifest_sources(
            Some("https://a.example.com/manifest.json, https://b.example.com/manifest.json".to_string()),
            Some(vec![
                "https://b.example.com/manifest.json".to_string(),
                "https://c.example.com/manifest.json".to_string(),
            ]),
        );
        assert_eq!(
            sources,
            vec![
                "https://a.example.com/manifest.json".to_string(),
                "https://b.example.com/manifest.json".to_string(),
                "https://c.example.com/manifest.json".to_string(),
            ]
        );
    }

    #[test]
    fn resolves_bundle_download_urls() {
        let bundle = RuntimeManifestBundle {
            target: "macos-aarch64".to_string(),
            url: "https://primary.example.com/runtime.zip".to_string(),
            sha256: None,
            urls: Some(vec![
                "https://mirror1.example.com/runtime.zip".to_string(),
                "https://mirror2.example.com/runtime.zip".to_string(),
            ]),
        };
        let urls = resolve_bundle_download_urls(&bundle);
        assert_eq!(
            urls,
            vec![
                "https://primary.example.com/runtime.zip".to_string(),
                "https://mirror1.example.com/runtime.zip".to_string(),
                "https://mirror2.example.com/runtime.zip".to_string(),
            ]
        );
    }

    #[test]
    fn validates_remote_url_scheme() {
        assert!(validate_remote_url_scheme("https://example.com/runtime.zip", "bundle").is_ok());
        assert!(validate_remote_url_scheme("file:///tmp/runtime.zip", "bundle").is_ok());
        assert!(validate_remote_url_scheme("http://localhost:8080/runtime.zip", "bundle").is_ok());
        assert!(validate_remote_url_scheme("http://127.0.0.1/runtime.zip", "bundle").is_ok());
        assert!(validate_remote_url_scheme("http://example.com/runtime.zip", "bundle").is_err());
    }

    #[test]
    fn detects_localhost_http_url() {
        assert!(is_localhost_http_url("http://localhost/runtime.zip"));
        assert!(is_localhost_http_url("http://127.0.0.1:8000/runtime.zip"));
        assert!(is_localhost_http_url("http://[::1]:8000/runtime.zip"));
        assert!(!is_localhost_http_url("https://localhost/runtime.zip"));
        assert!(!is_localhost_http_url("http://example.com/runtime.zip"));
    }

    #[test]
    fn checks_bundle_checksum_presence() {
        let with_checksum = RuntimeManifestBundle {
            target: "linux-x86_64".to_string(),
            url: "https://example.com/runtime.zip".to_string(),
            sha256: Some("abc123".to_string()),
            urls: None,
        };
        let without_checksum = RuntimeManifestBundle {
            target: "linux-x86_64".to_string(),
            url: "https://example.com/runtime.zip".to_string(),
            sha256: Some("   ".to_string()),
            urls: None,
        };

        assert!(bundle_has_checksum(&with_checksum));
        assert!(!bundle_has_checksum(&without_checksum));
    }
}
