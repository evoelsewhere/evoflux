//! Package preflight (v3 `security.py` `preflight_ooxml_package`).
//!
//! OOXML files are ZIP containers. Preview parsers must not see an archive until
//! its central directory has passed inexpensive structural and resource checks:
//! the end-of-central-directory record and every central header are read and
//! bounded here, by hand, before the `zip` crate (which materializes the whole
//! directory) is asked to open the archive.
//!
//! The cache helpers of v3's module (never following symlinks while cleaning
//! generated data) live in [`super::cache`].

use std::io::{Cursor, Read};
use std::path::Path;

use super::PreviewError;

/// Package types that are ZIP containers.
pub const OOXML_PREVIEW_EXTENSIONS: [&str; 3] = ["docx", "xlsx", "pptx"];

pub const MAX_OOXML_ARCHIVE_ENTRIES: usize = 4_096;
pub const MAX_OOXML_CENTRAL_DIRECTORY_BYTES: u64 = 8 * 1024 * 1024;
pub const MAX_OOXML_EXPANDED_BYTES: u64 = 256 * 1024 * 1024;
pub const MAX_OOXML_MEMBER_BYTES: u64 = 64 * 1024 * 1024;
pub const MAX_OOXML_COMPRESSION_RATIO: f64 = 200.0;
pub const MAX_OOXML_PART_NAME_BYTES: usize = 1_024;
pub const MAX_OOXML_CONTENT_TYPES_BYTES: u64 = 1024 * 1024;

/// The limits [`preflight`] applies (v3 module constants; tests lower them).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Limits {
    pub max_entries: usize,
    pub max_central_directory_bytes: u64,
    pub max_expanded_bytes: u64,
    pub max_member_bytes: u64,
    pub max_compression_ratio: f64,
    pub max_part_name_bytes: usize,
    pub max_content_types_bytes: u64,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_entries: MAX_OOXML_ARCHIVE_ENTRIES,
            max_central_directory_bytes: MAX_OOXML_CENTRAL_DIRECTORY_BYTES,
            max_expanded_bytes: MAX_OOXML_EXPANDED_BYTES,
            max_member_bytes: MAX_OOXML_MEMBER_BYTES,
            max_compression_ratio: MAX_OOXML_COMPRESSION_RATIO,
            max_part_name_bytes: MAX_OOXML_PART_NAME_BYTES,
            max_content_types_bytes: MAX_OOXML_CONTENT_TYPES_BYTES,
        }
    }
}

const EOCD_SIGNATURE: &[u8; 4] = b"PK\x05\x06";
const EOCD_SIZE: usize = 22;
const CENTRAL_HEADER_SIGNATURE: &[u8; 4] = b"PK\x01\x02";
const CENTRAL_HEADER_SIZE: usize = 46;
const OLE_SIGNATURE: &[u8; 8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1";
const ZIP_SIGNATURES: [&[u8; 4]; 2] = [b"PK\x03\x04", b"PK\x05\x06"];
/// How far into a `.pdf` the `%PDF-` header may start (PDF readers accept
/// leading junk within the first kilobyte).
const PDF_HEADER_WINDOW: usize = 1024;

const EXPECTED_MAIN_PART: [(&str, &str); 3] = [
    ("docx", "word/document.xml"),
    ("xlsx", "xl/workbook.xml"),
    ("pptx", "ppt/presentation.xml"),
];
const ACTIVE_PART_MARKERS: [&str; 7] = [
    "/activex/",
    "/ctrlprops/",
    "/customui/",
    "/dialogsheets/",
    "/macrosheets/",
    "/vbadata.xml",
    "/vbaproject.bin",
];
const ACTIVE_CONTENT_TYPE_MARKERS: [&[u8]; 4] = [
    b"macroenabled",
    b"vnd.ms-office.activex",
    b"vnd.ms-office.oleobject",
    b"vnd.ms-office.vbaproject",
];
const DANGEROUS_EMBEDDED_SUFFIXES: [&str; 15] = [
    ".bat", ".cmd", ".com", ".dll", ".exe", ".hta", ".jar", ".js", ".jse", ".msi", ".ps1", ".scr",
    ".vbe", ".vbs", ".wsf",
];

fn format_name(suffix: &str) -> &'static str {
    match suffix {
        "docx" => "Word document",
        "xlsx" => "Excel workbook",
        "pptx" => "PowerPoint presentation",
        "pdf" => "PDF document",
        _ => "Office document",
    }
}

fn main_part(suffix: &str) -> &'static str {
    EXPECTED_MAIN_PART
        .iter()
        .find(|(s, _)| *s == suffix)
        .map(|(_, part)| *part)
        .unwrap_or_default()
}

fn invalid_package() -> PreviewError {
    PreviewError::failed("Could not render this document: invalid or damaged OpenXML package.")
}

fn unsupported(message: &str) -> PreviewError {
    PreviewError::unsupported(message)
}

/// Check that `bytes` (the content of `source`) is a safe package of the type its
/// extension says, before any parser sees it.
pub fn preflight(source: &Path, bytes: &[u8]) -> Result<(), PreviewError> {
    preflight_with(source, bytes, &Limits::default())
}

/// [`preflight`] with explicit limits.
pub fn preflight_with(source: &Path, bytes: &[u8], limits: &Limits) -> Result<(), PreviewError> {
    let suffix = super::extension(source);
    if suffix == "pdf" {
        return check_pdf(bytes);
    }
    if !OOXML_PREVIEW_EXTENSIONS.contains(&suffix.as_str()) {
        return Ok(());
    }
    reject_non_package(bytes, &suffix)?;
    let entries = read_bounded_central_directory(bytes, limits)?;

    let mut expanded_size: u64 = 0;
    // Folded name → (index, raw name), in archive order.
    let mut names: Vec<(String, usize, String)> = Vec::with_capacity(entries.len());
    let mut seen = std::collections::HashSet::with_capacity(entries.len());
    for (index, entry) in entries.iter().enumerate() {
        let part_name = normalise_part_name(&entry.name, limits)?;
        let folded = part_name.to_lowercase();
        if !seen.insert(folded.clone()) {
            return Err(unsupported(
                "This OpenXML package contains duplicate part names.",
            ));
        }
        names.push((folded, index, entry.name.clone()));

        if entry.flags & 0x1 != 0 || entry.flags & 0x40 != 0 {
            return Err(unsupported(
                "Encrypted OpenXML packages cannot be previewed in-app.",
            ));
        }
        if entry.method != 0 && entry.method != 8 {
            return Err(unsupported(
                "This OpenXML package uses an unsupported compression method.",
            ));
        }
        let unix_mode = (entry.external_attr >> 16) & 0xFFFF;
        if unix_mode != 0 && unix_mode & 0o170000 == 0o120000 {
            return Err(unsupported(
                "This OpenXML package contains an unsafe symbolic link.",
            ));
        }
        let file_size = u64::from(entry.file_size);
        if file_size > limits.max_member_bytes {
            return Err(unsupported(
                "This OpenXML package contains an oversized part.",
            ));
        }
        expanded_size += file_size;
        if expanded_size > limits.max_expanded_bytes {
            return Err(unsupported(
                "This OpenXML package expands beyond the safe preview limit.",
            ));
        }
        if file_size > 0 {
            let ratio_error =
                || unsupported("This OpenXML package has an unsafe compression ratio.");
            if entry.compress_size == 0 {
                return Err(ratio_error());
            }
            if file_size as f64 / f64::from(entry.compress_size) > limits.max_compression_ratio {
                return Err(ratio_error());
            }
        }
        reject_active_part(&part_name)?;
    }

    let required = ["[content_types].xml", "_rels/.rels", main_part(&suffix)];
    let has = |name: &str| names.iter().any(|(n, _, _)| n == name);
    if !required.iter().all(|r| has(r)) {
        return Err(missing_parts_error(&names, &suffix));
    }

    let (_, content_types_index, _) = names
        .iter()
        .find(|(n, _, _)| n == "[content_types].xml")
        .expect("checked above");
    if u64::from(entries[*content_types_index].file_size) > limits.max_content_types_bytes {
        return Err(unsupported(
            "This OpenXML package has oversized content metadata.",
        ));
    }
    // The `zip` crate only opens the archive once its directory is bounded.
    let mut archive = zip::ZipArchive::new(Cursor::new(bytes)).map_err(|_| invalid_package())?;
    if archive.len() != entries.len() {
        return Err(invalid_package());
    }
    let mut content_types = Vec::new();
    {
        let entry = archive
            .by_index(*content_types_index)
            .map_err(|_| invalid_package())?;
        entry
            .take(limits.max_content_types_bytes + 1)
            .read_to_end(&mut content_types)
            .map_err(|_| invalid_package())?;
    }
    content_types.make_ascii_lowercase();
    if ACTIVE_CONTENT_TYPE_MARKERS
        .iter()
        .any(|marker| contains(&content_types, marker))
    {
        return Err(unsupported(
            "Documents with macros, OLE objects, or active controls cannot be previewed safely.",
        ));
    }
    Ok(())
}

/// A `.pdf` must carry the `%PDF-` header (v4 addition: v3 left this to pdfium).
fn check_pdf(bytes: &[u8]) -> Result<(), PreviewError> {
    let window = &bytes[..bytes.len().min(PDF_HEADER_WINDOW)];
    if contains(window, b"%PDF-") {
        return Ok(());
    }
    Err(PreviewError::unsupported(
        "This file has a .pdf name but is not a PDF document.",
    ))
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|w| w == needle)
}

/// Explain files that carry an Office name but are not OOXML packages.
///
/// Without this every such file surfaced as "damaged", which sends people
/// looking for corruption in what is really a mislabelled file.
fn reject_non_package(bytes: &[u8], suffix: &str) -> Result<(), PreviewError> {
    let head = &bytes[..bytes.len().min(OLE_SIGNATURE.len())];
    if ZIP_SIGNATURES.iter().any(|sig| head.starts_with(&sig[..])) {
        return Ok(());
    }
    if head == OLE_SIGNATURE {
        return Err(PreviewError::unsupported(format!(
            "This .{suffix} file is password-protected or was saved in the legacy \
Office 97–2003 format. Open it in Office and save it without a password as .{suffix} to \
preview it here."
        )));
    }
    Err(PreviewError::unsupported(format!(
        "This file has a .{suffix} name but is not a {}.",
        format_name(suffix)
    )))
}

/// Name what a ZIP without the expected OOXML parts actually is.
fn missing_parts_error(names: &[(String, usize, String)], suffix: &str) -> PreviewError {
    let has = |name: &str| names.iter().any(|(n, _, _)| n == name);
    for (other_suffix, part) in EXPECTED_MAIN_PART {
        if other_suffix != suffix && has(part) {
            return PreviewError::unsupported(format!(
                "This file is a {} saved with a .{suffix} name. Rename it to .{other_suffix} to \
preview it.",
                format_name(other_suffix)
            ));
        }
    }
    if !has("[content_types].xml") {
        let files: Vec<&str> = names
            .iter()
            .map(|(_, _, raw)| raw.as_str())
            .filter(|raw| !raw.ends_with('/'))
            .collect();
        let examples = files
            .iter()
            .take(3)
            .map(|name| file_name(name))
            .collect::<Vec<_>>()
            .join(", ");
        let more = if examples.is_empty() {
            String::new()
        } else {
            format!(" (for example {examples})")
        };
        return PreviewError::unsupported(format!(
            "This file is a ZIP archive with a .{suffix} name, not a {}. It contains {} file{}{more}.",
            format_name(suffix),
            files.len(),
            if files.len() != 1 { "s" } else { "" },
        ));
    }
    invalid_package()
}

/// The last path segment (Python `Path(name).name`).
fn file_name(name: &str) -> &str {
    name.trim_end_matches('/')
        .rsplit('/')
        .next()
        .unwrap_or(name)
}

/// One central directory header, as v3's `zipfile.ZipInfo` exposed it.
#[derive(Debug, Clone)]
struct CentralEntry {
    name: String,
    flags: u16,
    method: u16,
    compress_size: u32,
    file_size: u32,
    external_attr: u32,
}

fn u16_at(data: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([data[offset], data[offset + 1]])
}

fn u32_at(data: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ])
}

/// Read and bound the end-of-central-directory record and every central header
/// without the `zip` crate (v3 `_read_bounded_eocd`, which also returned the
/// headers through `ZipFile.infolist`).
///
/// Reading the small fixed trailer first rejects an excessive entry count or
/// central directory before anything allocates for it; the headers are then
/// walked one by one so a forged small count cannot hide a larger directory.
fn read_bounded_central_directory(
    bytes: &[u8],
    limits: &Limits,
) -> Result<Vec<CentralEntry>, PreviewError> {
    let source_size = bytes.len();
    if source_size < EOCD_SIZE {
        return Err(invalid_package());
    }
    let tail_size = source_size.min(EOCD_SIZE + 65_535);
    let tail_start = source_size - tail_size;
    let tail = &bytes[tail_start..];

    let mut cursor = tail.len();
    let (
        position,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
    ) = loop {
        let Some(position) = tail[..cursor]
            .windows(EOCD_SIGNATURE.len())
            .rposition(|w| w == EOCD_SIGNATURE)
        else {
            return Err(invalid_package());
        };
        cursor = position;
        if position + EOCD_SIZE > tail.len() {
            continue;
        }
        let record = &tail[position..position + EOCD_SIZE];
        let comment_size = usize::from(u16_at(record, 20));
        if tail_start + position + EOCD_SIZE + comment_size != source_size {
            continue;
        }
        break (
            tail_start + position,
            u16_at(record, 4),
            u16_at(record, 6),
            u16_at(record, 8),
            u16_at(record, 10),
            u32_at(record, 12),
            u32_at(record, 16),
        );
    };

    if disk_number != 0 || central_disk != 0 || disk_entries != total_entries {
        return Err(unsupported(
            "Multi-volume OpenXML packages are not supported by the in-app viewer.",
        ));
    }
    if total_entries == 0xFFFF || central_size == 0xFFFF_FFFF || central_offset == 0xFFFF_FFFF {
        return Err(unsupported(
            "ZIP64 OpenXML packages exceed the in-app preview safety limits.",
        ));
    }
    let too_many = || unsupported("This OpenXML package contains too many parts for safe preview.");
    if usize::from(total_entries) > limits.max_entries {
        return Err(too_many());
    }
    if u64::from(central_size) > limits.max_central_directory_bytes {
        return Err(unsupported(
            "This OpenXML package has an oversized directory for safe preview.",
        ));
    }
    let central_offset = central_offset as usize;
    let central_size = central_size as usize;
    if central_offset + central_size != position {
        return Err(invalid_package());
    }

    let directory = &bytes[central_offset..central_offset + central_size];
    let mut entries = Vec::new();
    let mut offset = 0;
    while offset < directory.len() {
        if offset + CENTRAL_HEADER_SIZE > directory.len() {
            return Err(invalid_package());
        }
        let header = &directory[offset..offset + CENTRAL_HEADER_SIZE];
        if &header[..4] != CENTRAL_HEADER_SIGNATURE {
            return Err(invalid_package());
        }
        let flags = u16_at(header, 8);
        let method = u16_at(header, 10);
        let compress_size = u32_at(header, 20);
        let file_size = u32_at(header, 24);
        let filename_size = usize::from(u16_at(header, 28));
        let extra_size = usize::from(u16_at(header, 30));
        let comment_size = usize::from(u16_at(header, 32));
        let entry_disk = u16_at(header, 34);
        let external_attr = u32_at(header, 38);
        if entry_disk != 0 || filename_size > limits.max_part_name_bytes {
            return Err(unsupported(
                "This OpenXML package contains an unsafe part directory.",
            ));
        }
        let name_start = offset + CENTRAL_HEADER_SIZE;
        offset = name_start + filename_size + extra_size + comment_size;
        if offset > directory.len() {
            return Err(invalid_package());
        }
        let raw_name = &directory[name_start..name_start + filename_size];
        let name = decode_name(raw_name, flags).ok_or_else(invalid_package)?;
        entries.push(CentralEntry {
            name,
            flags,
            method,
            compress_size,
            file_size,
            external_attr,
        });
        if entries.len() > limits.max_entries {
            return Err(too_many());
        }
    }
    if entries.len() != usize::from(total_entries) {
        return Err(invalid_package());
    }
    Ok(entries)
}

/// Decode a ZIP member name like Python's `zipfile`: UTF-8 when flag bit 11 is
/// set, otherwise code page 437.
fn decode_name(raw: &[u8], flags: u16) -> Option<String> {
    if flags & 0x800 != 0 {
        return String::from_utf8(raw.to_vec()).ok();
    }
    Some(
        raw.iter()
            .map(|&b| {
                if b < 0x80 {
                    char::from(b)
                } else {
                    CP437_HIGH[usize::from(b - 0x80)]
                }
            })
            .collect(),
    )
}

const CP437_HIGH: [char; 128] = [
    'Ç', 'ü', 'é', 'â', 'ä', 'à', 'å', 'ç', 'ê', 'ë', 'è', 'ï', 'î', 'ì', 'Ä', 'Å', 'É', 'æ', 'Æ',
    'ô', 'ö', 'ò', 'û', 'ù', 'ÿ', 'Ö', 'Ü', '¢', '£', '¥', '₧', 'ƒ', 'á', 'í', 'ó', 'ú', 'ñ', 'Ñ',
    'ª', 'º', '¿', '⌐', '¬', '½', '¼', '¡', '«', '»', '░', '▒', '▓', '│', '┤', '╡', '╢', '╖', '╕',
    '╣', '║', '╗', '╝', '╜', '╛', '┐', '└', '┴', '┬', '├', '─', '┼', '╞', '╟', '╚', '╔', '╩', '╦',
    '╠', '═', '╬', '╧', '╨', '╤', '╥', '╙', '╘', '╒', '╓', '╫', '╪', '┘', '┌', '█', '▄', '▌', '▐',
    '▀', 'α', 'ß', 'Γ', 'π', 'Σ', 'σ', 'µ', 'τ', 'Φ', 'Θ', 'Ω', 'δ', '∞', 'φ', 'ε', '∩', '≡', '±',
    '≥', '≤', '⌠', '⌡', '÷', '≈', '°', '∙', '·', '√', 'ⁿ', '²', '■', '\u{a0}',
];

fn normalise_part_name(raw_name: &str, limits: &Limits) -> Result<String, PreviewError> {
    let unsafe_name = || unsupported("This OpenXML package contains an unsafe part name.");
    if raw_name.is_empty() || raw_name.contains('\0') || raw_name.contains('\\') {
        return Err(unsafe_name());
    }
    if raw_name.len() > limits.max_part_name_bytes {
        return Err(unsupported(
            "This OpenXML package contains an oversized part name.",
        ));
    }
    let mut chars = raw_name.chars();
    let drive = matches!((chars.next(), chars.next()), (Some(c), Some(':')) if c.is_alphabetic());
    if raw_name.starts_with('/') || drive {
        return Err(unsafe_name());
    }
    let is_directory = raw_name.ends_with('/');
    let candidate = if is_directory {
        &raw_name[..raw_name.len() - 1]
    } else {
        raw_name
    };
    if candidate.is_empty() || candidate.split('/').any(|p| matches!(p, "" | "." | "..")) {
        return Err(unsafe_name());
    }
    Ok(raw_name.to_string())
}

fn reject_active_part(part_name: &str) -> Result<(), PreviewError> {
    let lowered = format!("/{}", part_name.to_lowercase());
    if ACTIVE_PART_MARKERS.iter().any(|m| lowered.contains(m)) {
        return Err(unsupported(
            "Documents with macros or active controls cannot be previewed safely.",
        ));
    }
    if lowered.contains("/embeddings/") {
        let suffix = path_suffix(part_name).to_lowercase();
        if DANGEROUS_EMBEDDED_SUFFIXES.contains(&suffix.as_str()) {
            return Err(unsupported(
                "Documents with executable embedded content cannot be previewed safely.",
            ));
        }
    }
    Ok(())
}

/// Python `Path(name).suffix`: the last dot of the last segment, unless that
/// dot leads or ends the segment.
fn path_suffix(name: &str) -> &str {
    let last = file_name(name);
    match last.rfind('.') {
        Some(i) if i > 0 && i < last.len() - 1 => &last[i..],
        _ => "",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_suffix_semantics() {
        assert_eq!(path_suffix("word/embeddings/payload.exe"), ".exe");
        assert_eq!(path_suffix("word/embeddings/.exe"), "");
        assert_eq!(path_suffix("word/embeddings/x."), "");
        assert_eq!(file_name("jira-docs/00-overview.md"), "00-overview.md");
    }

    #[test]
    fn cp437_names_decode() {
        assert_eq!(decode_name(b"caf\x82.xml", 0).as_deref(), Some("café.xml"));
        assert_eq!(
            decode_name("café".as_bytes(), 0x800).as_deref(),
            Some("café")
        );
    }
}
