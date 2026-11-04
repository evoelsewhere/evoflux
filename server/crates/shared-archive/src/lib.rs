//! Port of app/plugin_platform/installer.py and app/cli/seed.py archive handling.
//!
//! Synchronous, bounded extraction for staging directories. Async consumers must
//! call this on the bounded blocking pool. Files already present are never
//! overwritten. Errors can leave partial output; callers own staging cleanup.
#![forbid(unsafe_code)]

mod output;
use output::Output;
use std::io::{Cursor, Read};
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum ArchiveError {
    #[error("unsafe archive path")]
    Path,
    #[error("archive links and special files are forbidden")]
    Link,
    #[error("duplicate archive path")]
    Duplicate,
    #[error("archive contains too many entries")]
    Entries,
    #[error("archive exceeds its byte limit or declares an invalid size")]
    Size,
    #[error("archive exceeds its compression ratio limit")]
    Ratio,
    #[error("invalid ZIP archive: {0}")]
    Zip(#[from] zip::result::ZipError),
    #[error("cannot extract archive: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Copy)]
pub struct Limits {
    pub max_entries: usize,
    pub max_total_bytes: u64,
    pub max_archive_bytes: u64,
    pub max_compression_ratio: u64,
    /// Additional decoded tar bytes (headers, padding and GNU/PAX metadata).
    pub max_tar_metadata_bytes: u64,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            max_entries: 4096,
            max_total_bytes: 120 * 1024 * 1024,
            max_archive_bytes: 50 * 1024 * 1024,
            max_compression_ratio: 200,
            max_tar_metadata_bytes: 8 * 1024 * 1024,
        }
    }
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct Extracted {
    /// Logical entries, including directories.
    pub entries: usize,
    /// Actual extracted file bytes, excluding archive framing.
    pub bytes: u64,
}

fn bounded_read(src: impl Read, max: u64) -> Result<Vec<u8>, ArchiveError> {
    let end = max.checked_add(1).ok_or(ArchiveError::Size)?;
    let mut bytes = Vec::new();
    src.take(end).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > max {
        return Err(ArchiveError::Size);
    }
    Ok(bytes)
}

fn ratio(expanded: u64, compressed: u64, limits: Limits) -> Result<(), ArchiveError> {
    if expanded > compressed.saturating_mul(limits.max_compression_ratio) {
        return Err(ArchiveError::Ratio);
    }
    Ok(())
}

/// Extract ZIP files/directories only. Paths are validated before any OS parsing.
pub fn extract_zip(
    src: impl Read,
    dest: impl AsRef<Path>,
    limits: Limits,
) -> Result<Extracted, ArchiveError> {
    let bytes = bounded_read(src, limits.max_archive_bytes)?;
    // Read only EOCD/ZIP64 first, before allocating/parsing per-entry metadata.
    let mut archive = zip::unstable::read::ZipIterable::try_new(
        Cursor::new(bytes),
        zip::read::Config::default(),
    )?
    .enforce_header_consistency(true);
    if archive.len() > limits.max_entries {
        return Err(ArchiveError::Entries);
    }
    let mut output = Output::new(dest.as_ref(), limits)?;
    let files = archive.files()?;
    while let Some(entry) = files.next() {
        let entry = entry?;
        let mut file = entry.with_reader(files.reader_mut(), zip::ZipReadOptions::default())?;
        let dir = file.is_dir();
        let mode = file.unix_mode().unwrap_or(0);
        let kind = mode & 0o170000;
        if file.is_symlink() || !matches!(kind, 0 | 0o100000 | 0o040000) {
            return Err(ArchiveError::Link);
        }
        let name = file.name()?.into_owned();
        let size = file.size();
        ratio(size, file.compressed_size(), limits)?;
        output.entry(&name, dir, size, mode, &mut file)?;
    }
    Ok(output.finish())
}

/// Decode the complete bounded gzip stream (including CRC) before parsing tar.
/// GNU/PAX metadata expansion is bounded even when it contains no logical files.
pub fn extract_tar_gz(
    src: impl Read,
    dest: impl AsRef<Path>,
    limits: Limits,
) -> Result<Extracted, ArchiveError> {
    let compressed = bounded_read(src, limits.max_archive_bytes)?;
    let budget = limits
        .max_total_bytes
        .checked_add(limits.max_tar_metadata_bytes)
        .ok_or(ArchiveError::Size)?;
    let bytes = bounded_read(
        flate2::read::MultiGzDecoder::new(compressed.as_slice()),
        budget,
    )?;
    ratio(bytes.len() as u64, compressed.len() as u64, limits)?;
    // Reject sparse/device/link records before tar interprets GNU extensions.
    // GNU long names and PAX metadata are interpreted by the second pass.
    let mut headers = tar::Archive::new(Cursor::new(bytes.as_slice()));
    let mut pax_size = None;
    for entry in headers.entries()?.raw(true) {
        let mut entry = entry?;
        let kind = entry.header().entry_type();
        if !(kind.is_file()
            || kind.is_dir()
            || kind.is_gnu_longname()
            || kind.is_pax_local_extensions()
            || kind.is_pax_global_extensions())
        {
            return Err(ArchiveError::Link);
        }
        if (kind.is_file() || kind.is_dir())
            && pax_size.take().is_some_and(|size| size != entry.size())
        {
            // Avoid interpreting the same physical records differently in
            // the raw type check and the effective GNU/PAX name pass.
            return Err(ArchiveError::Size);
        }
        if kind.is_pax_local_extensions() || kind.is_pax_global_extensions() {
            if let Some(fields) = entry.pax_extensions()? {
                // tar takes the first `size` key and this pass the last; one
                // header may declare it at most once so both passes agree.
                let mut seen_size = false;
                for field in fields {
                    let field = field?;
                    if kind.is_pax_global_extensions()
                        && matches!(field.key_bytes(), b"path" | b"linkpath" | b"size")
                    {
                        return Err(ArchiveError::Path);
                    }
                    if field.key_bytes() == b"size" {
                        if std::mem::replace(&mut seen_size, true) {
                            return Err(ArchiveError::Size);
                        }
                        let size = std::str::from_utf8(field.value_bytes())
                            .map_err(|_| ArchiveError::Size)?
                            .parse::<u64>()
                            .map_err(|_| ArchiveError::Size)?;
                        pax_size = Some(size);
                    }
                }
            }
        }
    }
    let mut archive = tar::Archive::new(Cursor::new(bytes));
    let mut output = Output::new(dest.as_ref(), limits)?;
    for entry in archive.entries()? {
        let mut entry = entry?;
        let kind = entry.header().entry_type();
        // GitHub tarballs carry a global PAX comment (commit id), validated in
        // the raw pass. Global path/size/link overrides were refused there.
        if kind.is_pax_global_extensions() {
            continue;
        }
        if !kind.is_file() && !kind.is_dir() {
            return Err(ArchiveError::Link);
        }
        let raw = entry.path_bytes();
        let name = std::str::from_utf8(&raw)
            .map_err(|_| ArchiveError::Path)?
            .to_owned();
        let size = entry.size();
        let mode = entry.header().mode()?;
        output.entry(&name, kind.is_dir(), size, mode, &mut entry)?;
    }
    Ok(output.finish())
}
