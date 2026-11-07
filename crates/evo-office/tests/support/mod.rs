//! Shared helpers: build runtime archives and wait for installs.
#![allow(dead_code)]

use std::io::Write;
use std::path::Path;
use std::time::{Duration, Instant};

use evo_office::manifest::Asset;
use evo_office::Runtime;
use sha2::{Digest, Sha256};

pub enum Member<'a> {
    File(&'a str, &'a [u8], u32),
    Dir(&'a str),
    Symlink(&'a str, &'a str),
    Fifo(&'a str),
    /// A file whose stored name is written verbatim (bypasses the builder's own checks).
    RawName(&'a str, &'a [u8]),
}

pub fn archive(members: &[Member]) -> Vec<u8> {
    let mut builder = tar::Builder::new(Vec::new());
    for member in members {
        let mut header = tar::Header::new_gnu();
        match member {
            Member::File(name, data, mode) => {
                header.set_size(data.len() as u64);
                header.set_mode(*mode);
                header.set_entry_type(tar::EntryType::Regular);
                builder.append_data(&mut header, name, *data).unwrap();
            }
            Member::Dir(name) => {
                header.set_entry_type(tar::EntryType::Directory);
                header.set_mode(0o755);
                header.set_size(0);
                builder
                    .append_data(&mut header, name, std::io::empty())
                    .unwrap();
            }
            Member::Symlink(name, target) => {
                header.set_entry_type(tar::EntryType::Symlink);
                header.set_size(0);
                header.set_link_name(target).unwrap();
                builder
                    .append_data(&mut header, name, std::io::empty())
                    .unwrap();
            }
            Member::Fifo(name) => {
                header.set_entry_type(tar::EntryType::Fifo);
                header.set_size(0);
                builder
                    .append_data(&mut header, name, std::io::empty())
                    .unwrap();
            }
            Member::RawName(name, data) => {
                header.set_size(data.len() as u64);
                header.set_mode(0o644);
                header.set_entry_type(tar::EntryType::Regular);
                let bytes = name.as_bytes();
                header.as_old_mut().name[..bytes.len()].copy_from_slice(bytes);
                header.set_cksum();
                builder.append(&header, *data).unwrap();
            }
        }
    }
    let tar = builder.into_inner().unwrap();
    let mut gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
    gz.write_all(&tar).unwrap();
    gz.finish().unwrap()
}

pub fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn asset(url: String, bytes: &[u8], executable: &str) -> Asset {
    Asset {
        platform: "test-x64".into(),
        version: "1.0".into(),
        url,
        sha256: sha(bytes),
        size: bytes.len() as u64,
        executable: executable.into(),
        installed_size: None,
    }
}

pub fn file_url(path: &Path) -> String {
    url::Url::from_file_path(path).unwrap().to_string()
}

/// Wait until the install job is gone or failed; returns the failure, if any.
pub async fn finish(runtime: &Runtime) -> Option<String> {
    let started = Instant::now();
    loop {
        let status = runtime.status();
        match status.job {
            None => return None,
            Some(job) if job.error.is_some() => return job.error,
            _ => {}
        }
        assert!(
            started.elapsed() < Duration::from_secs(30),
            "install did not finish"
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

/// A runtime holding a fake `soffice` script, installed through the real installer.
pub async fn fake_runtime(dir: &Path, script: &str) -> Runtime {
    let (name, mode) = if cfg!(windows) {
        ("soffice/fake.cmd", 0o644)
    } else {
        ("soffice/fake.sh", 0o755)
    };
    let bytes = archive(&[Member::File(name, script.as_bytes(), mode)]);
    let archive_path = dir.join("runtime.tar.gz");
    std::fs::write(&archive_path, &bytes).unwrap();
    let runtime = Runtime::with_asset(
        &dir.join("runtimes"),
        Some(asset(file_url(&archive_path), &bytes, name)),
    );
    runtime.start_install().unwrap();
    assert_eq!(finish(&runtime).await, None);
    assert!(runtime.installed().is_some());
    runtime
}
