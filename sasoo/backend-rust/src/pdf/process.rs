//! Candidate process boundary. Extraction identity stays text-layer-v2.
use super::{DocumentArtifact, PdfInput, PdfOptions, artifacts::*, extract_document};
use crate::error::{Result, SasooError};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{
    fs,
    io::{BufRead, Read, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

const MAX_OUTPUT: u64 = 128 * 1024 * 1024;
#[derive(Clone)]
pub struct Policy {
    pub executable: PathBuf,
    pub timeout: Duration,
}
impl Policy {
    pub fn new(executable: impl Into<PathBuf>, timeout: Duration) -> Self {
        Self {
            executable: executable.into(),
            timeout,
        }
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    operation: Uuid,
    nonce: Uuid,
    source_sha256: [u8; 32],
    options: PdfOptions,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Complete {
    operation: Uuid,
    nonce: Uuid,
    pid: u32,
    document_sha256: String,
}
struct OwnedChild(Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        // Never release the producer slot with an unreaped child.
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
fn incomplete(message: &str) -> SasooError {
    SasooError::Incomplete(message.into())
}

// This synchronous owner survives HTTP future cancellation inside spawn_blocking.
pub fn extract(
    policy: &Policy,
    input: &PdfInput,
    options: &PdfOptions,
    cancel: &CancellationToken,
    operation: Uuid,
    work_parent: &Path,
) -> Result<DocumentArtifact> {
    if cancel.is_cancelled() {
        return Err(incomplete("PDF cancellation requested before child spawn"));
    }
    if policy.timeout.is_zero() {
        return Err(SasooError::InvalidInput(
            "PDF child timeout must be explicitly positive".into(),
        ));
    }
    let executable = policy.executable.canonicalize()?;
    let executable_hash = hash(&read_bounded(&executable, 512 * 1024 * 1024)?);
    let work = work_parent.join(format!("process-{}", Uuid::new_v4()));
    fs::create_dir(&work)?;
    let work = work.canonicalize()?;
    let bytes = read_bounded(&input.path, MAX_PDF_BYTES as u64)?;
    if hash(&bytes) != hash256(input.source_sha256) {
        return Err(SasooError::Conflict(
            "PDF source changed before child dispatch".into(),
        ));
    }
    write_new(&work.join("input.pdf"), &bytes)?;
    let request = Request {
        operation,
        nonce: Uuid::new_v4(),
        source_sha256: input.source_sha256,
        options: options.clone(),
    };
    write_new(&work.join("intent.json"), &serde_json::to_vec(&json!({"operation":operation,"nonce":request.nonce,"executable_sha256":executable_hash,"timeout_ms":policy.timeout.as_millis(),"state":"spawn_intent","policy":"macos-seatbelt-v1","memory_hard_cap":false})) .map_err(|_| incomplete("Invalid PDF intent"))?)?;
    let mut command = sandbox_command(&executable, &work)?;
    command
        .arg("--pdf-operation")
        .current_dir(&work)
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    let mut child = OwnedChild(command.spawn()?);
    let pid = child.0.id();
    write_new(&work.join("child.json"), &serde_json::to_vec(&json!({"operation":operation,"nonce":request.nonce,"pid":pid,"executable_sha256":executable_hash})).unwrap())?;
    let mut stdin = child
        .0
        .stdin
        .take()
        .ok_or_else(|| incomplete("PDF child stdin unavailable"))?;
    let mut wire =
        serde_json::to_vec(&request).map_err(|_| incomplete("Invalid PDF child request"))?;
    wire.push(b'\n');
    let dispatch_failed = stdin.write_all(&wire).is_err();
    // Keep stdin open as the parent's liveness lease. EOF makes the child exit.
    let started = Instant::now();
    let (status, stop) = loop {
        if let Some(status) = child.0.try_wait()? {
            let stop = if dispatch_failed {
                Some("dispatch_io_failed")
            } else if cancel.is_cancelled() {
                Some("cancel_requested")
            } else if started.elapsed() >= policy.timeout {
                Some("deadline_elapsed")
            } else {
                None
            };
            break (status, stop);
        }
        let stop = if dispatch_failed {
            Some("dispatch_io_failed")
        } else if cancel.is_cancelled() {
            Some("cancel_requested")
        } else if started.elapsed() >= policy.timeout {
            Some("deadline_elapsed")
        } else if ["document.json", "complete.json"].iter().any(|name| {
            fs::metadata(work.join(name)).is_ok_and(|m| {
                m.len()
                    > if *name == "document.json" {
                        MAX_OUTPUT
                    } else {
                        4096
                    }
            })
        }) {
            Some("output_limit")
        } else {
            None
        };
        if let Some(reason) = stop {
            write_new(&work.join("termination-request.json"), &serde_json::to_vec(&json!({"operation":operation,"pid":pid,"reason":reason,"elapsed_ms":started.elapsed().as_millis()})).unwrap())?;
            child.0.kill()?;
            break (child.0.wait()?, Some(reason));
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    write_new(&work.join("reaped.json"), &serde_json::to_vec(&json!({"operation":operation,"pid":pid,"exit_success":status.success(),"stop":stop,"elapsed_ms":started.elapsed().as_millis(),"state":"child_exited_and_reaped"})).unwrap())?;
    if stop.is_some() || cancel.is_cancelled() {
        return Err(incomplete(
            "PDF child stopped and reaped; publication rejected",
        ));
    }
    if !status.success() {
        return Err(incomplete(
            "PDF child exited abnormally and was reaped; publication rejected",
        ));
    }
    let complete: Complete =
        serde_json::from_slice(&read_bounded(&work.join("complete.json"), 4096)?)
            .map_err(|_| incomplete("Invalid PDF child completion"))?;
    if complete.operation != operation || complete.nonce != request.nonce || complete.pid != pid {
        return Err(SasooError::Conflict(
            "PDF child identity differs; publication rejected".into(),
        ));
    }
    let bytes = read_bounded(&work.join("document.json"), MAX_OUTPUT)?;
    let document: DocumentArtifact =
        serde_json::from_slice(&bytes).map_err(|_| incomplete("Invalid PDF child document"))?;
    document.validate()?;
    if complete.operation != operation
        || complete.nonce != request.nonce
        || complete.pid != pid
        || complete.document_sha256 != hash(&bytes)
        || document.source_sha256 != input.source_sha256
        || document.engine != options.engine
        || document.extraction_options_sha256 != Some(options.options_hash)
        || options != &super::native::native_options()
    {
        return Err(SasooError::Conflict(
            "PDF child identity or output differs; publication rejected".into(),
        ));
    }
    if cancel.is_cancelled() {
        return Err(incomplete(
            "PDF child result cancelled; publication rejected",
        ));
    }
    write_new(&work.join("validated.json"), &serde_json::to_vec(&json!({"operation":operation,"document_sha256":hash(&bytes),"state":"validated_not_published"})).unwrap())?;
    Ok(document)
}
fn hash256(value: [u8; 32]) -> String {
    value.iter().map(|b| format!("{b:02x}")).collect()
}

#[cfg(target_os = "macos")]
fn sandbox_command(executable: &Path, work: &Path) -> Result<Command> {
    let quote = |p: &Path| serde_json::to_string(&p.to_string_lossy()).unwrap();
    let profile = format!(
        r#"(version 1)(deny default)
(allow process-exec (literal {}))
(allow file-read* (literal "/") (literal {}) (subpath "/System/Library") (subpath "/usr/lib") (literal "/dev/null") (subpath {}))
(allow file-write* (subpath {}))
(allow sysctl-read)
(allow process-info* (target self))"#,
        quote(executable),
        quote(executable),
        quote(work),
        quote(work)
    );
    let mut command = Command::new("/usr/bin/sandbox-exec");
    command.args(["-p", &profile]).arg(executable);
    Ok(command)
}
#[cfg(not(target_os = "macos"))]
fn sandbox_command(_: &Path, _: &Path) -> Result<Command> {
    Err(SasooError::Unsupported(
        "PDF child credential/filesystem sandbox is not implemented on this platform".into(),
    ))
}

// Called before the server runtime, DB owner, or credential factories are created.
pub fn child_main() -> Result<()> {
    let mut line = String::new();
    let mut stdin = std::io::BufReader::new(std::io::stdin());
    stdin.by_ref().take(16385).read_line(&mut line)?;
    if line.len() > 16384 || !line.ends_with('\n') {
        return Err(incomplete("PDF child request is missing or oversized"));
    }
    let request: Request =
        serde_json::from_str(&line).map_err(|_| incomplete("Invalid PDF child request"))?;
    std::thread::spawn(move || {
        let mut byte = [0];
        let _ = stdin.read(&mut byte);
        std::process::exit(74);
    });
    let work = std::env::current_dir()?;
    let document = extract_document(
        &PdfInput {
            path: work.join("input.pdf"),
            source_sha256: request.source_sha256,
        },
        &request.options,
        &CancellationToken::new(),
    )?;
    let bytes =
        serde_json::to_vec(&document).map_err(|_| incomplete("Invalid PDF child document"))?;
    if bytes.len() as u64 > MAX_OUTPUT {
        return Err(incomplete("PDF child output exceeds 128 MiB"));
    }
    write_new(&work.join("document.json"), &bytes)?;
    write_new(
        &work.join("complete.json"),
        &serde_json::to_vec(&Complete {
            operation: request.operation,
            nonce: request.nonce,
            pid: std::process::id(),
            document_sha256: hash(&bytes),
        })
        .unwrap(),
    )?;
    Ok(())
}
