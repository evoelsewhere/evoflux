//! Port of Python plugin archive attack tests, extended to the shared tar reader.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
use shared_archive::{extract_tar_gz, extract_zip, ArchiveError, Extracted, Limits};
use std::io::{Cursor, Write};
use std::path::Path;

fn zip(entries: &[(&str, &[u8])], deflate: bool) -> Vec<u8> {
    let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let options = zip::write::SimpleFileOptions::default()
        .unix_permissions(0o755)
        .compression_method(if deflate {
            zip::CompressionMethod::Deflated
        } else {
            zip::CompressionMethod::Stored
        });
    for (name, data) in entries {
        if name.ends_with('/') {
            zip.add_directory(*name, options).unwrap();
        } else {
            zip.start_file(*name, options).unwrap();
            zip.write_all(data).unwrap();
        }
    }
    zip.finish().unwrap().into_inner()
}
fn tar(entries: &[(&str, &[u8], u8, &str)]) -> Vec<u8> {
    let mut builder = tar::Builder::new(Vec::new());
    for (name, data, kind, target) in entries {
        let mut header = tar::Header::new_gnu();
        header.set_size(data.len() as u64);
        header.set_mode(0o755);
        header.set_entry_type(tar::EntryType::new(*kind));
        if !target.is_empty() {
            header.set_link_name(target).unwrap();
        }
        // Write raw name bytes: tar::Builder's ordinary path API rejects attacks.
        header.as_mut_bytes()[..name.len()].copy_from_slice(name.as_bytes());
        header.set_cksum();
        builder.append(&header, *data).unwrap();
    }
    let bytes = builder.into_inner().unwrap();
    let mut gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    gz.write_all(&bytes).unwrap();
    gz.finish().unwrap()
}
fn extract(
    zip_format: bool,
    src: &[u8],
    dest: &Path,
    limits: Limits,
) -> Result<Extracted, ArchiveError> {
    if zip_format {
        extract_zip(src, dest, limits)
    } else {
        extract_tar_gz(src, dest, limits)
    }
}
fn regular(zip_format: bool, entries: &[(&str, &[u8])], compressed: bool) -> Vec<u8> {
    if zip_format {
        zip(entries, compressed)
    } else {
        tar(&entries
            .iter()
            .map(|(name, data)| {
                (
                    *name,
                    *data,
                    if name.ends_with('/') { b'5' } else { b'0' },
                    "",
                )
            })
            .collect::<Vec<_>>())
    }
}

#[test]
fn normal_archives_extract_nested_unicode_content_and_report_actual_totals() {
    for zipped in [true, false] {
        let temp = tempfile::tempdir().unwrap();
        let dest = temp.path().join("out");
        let src = regular(
            zipped,
            &[
                ("folder/", b""),
                ("folder/café.txt", b"hello"),
                ("empty", b""),
            ],
            true,
        );
        assert_eq!(
            extract(zipped, &src, &dest, Limits::default()).unwrap(),
            Extracted {
                entries: 3,
                bytes: 5
            }
        );
        assert_eq!(
            std::fs::read(dest.join("folder/café.txt")).unwrap(),
            b"hello"
        );
        assert_eq!(std::fs::metadata(dest.join("empty")).unwrap().len(), 0);
    }
}

#[test]
fn refuses_cross_platform_path_attacks_without_writing_outside() {
    for zipped in [true, false] {
        for name in [
            "../escape",
            "/absolute",
            "C:/escape",
            "C:escape",
            "..\\escape",
            "dir\\file",
            "//host/share",
            "a/../../escape",
            "a/./file",
            "a//file",
            "file.",
            "file ",
            "NUL",
            "con.txt",
            "a:stream",
            "foo/COM1",
            "a\u{1}b",
        ] {
            let temp = tempfile::tempdir().unwrap();
            let dest = temp.path().join("out");
            let src = regular(zipped, &[(name, b"bad")], false);
            assert!(
                matches!(
                    extract(zipped, &src, &dest, Limits::default()),
                    Err(ArchiveError::Path)
                ),
                "{name}, zip={zipped}"
            );
            assert!(!temp.path().join("escape").exists());
        }
    }
}

#[test]
fn refuses_zip_symlinks_even_if_their_target_is_inside() {
    for target in ["../escape", "/outside", "inside"] {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.add_symlink("link", target, zip::write::SimpleFileOptions::default())
            .unwrap();
        let src = zip.finish().unwrap().into_inner();
        let temp = tempfile::tempdir().unwrap();
        let result = extract_zip(src.as_slice(), temp.path(), Limits::default());
        assert!(
            matches!(result, Err(ArchiveError::Link)),
            "target {target}: {result:?}"
        );
        assert!(!temp.path().join("link").exists());
    }
}

#[test]
fn refuses_tar_symbolic_hard_links_and_special_files() {
    for kind in *b"12346S" {
        for target in ["../escape", "/outside", "inside"] {
            let src = tar(&[("link", b"", kind, target)]);
            let temp = tempfile::tempdir().unwrap();
            assert!(
                matches!(
                    extract_tar_gz(src.as_slice(), temp.path(), Limits::default()),
                    Err(ArchiveError::Link)
                ),
                "kind={kind}"
            );
            assert!(!temp.path().join("link").exists());
        }
    }
}

#[test]
fn enforces_entry_total_byte_and_compressed_byte_limits_at_exact_boundaries() {
    for zipped in [true, false] {
        let src = regular(zipped, &[("a", b"abc"), ("b", b"def")], false);
        for (limits, error) in [
            (
                Limits {
                    max_entries: 1,
                    ..Limits::default()
                },
                "entries",
            ),
            (
                Limits {
                    max_total_bytes: 5,
                    ..Limits::default()
                },
                "size",
            ),
            (
                Limits {
                    max_archive_bytes: src.len() as u64 - 1,
                    ..Limits::default()
                },
                "size",
            ),
        ] {
            let temp = tempfile::tempdir().unwrap();
            let result = extract(zipped, &src, temp.path(), limits);
            if error == "entries" {
                assert!(matches!(result, Err(ArchiveError::Entries)));
            } else {
                assert!(matches!(result, Err(ArchiveError::Size)));
            }
        }
        let temp = tempfile::tempdir().unwrap();
        let limits = Limits {
            max_entries: 2,
            max_total_bytes: 6,
            max_archive_bytes: src.len() as u64,
            ..Limits::default()
        };
        assert_eq!(
            extract(zipped, &src, temp.path(), limits).unwrap(),
            Extracted {
                entries: 2,
                bytes: 6
            }
        );
    }
}

#[test]
fn refuses_compression_bombs_and_counts_directory_entries() {
    for zipped in [true, false] {
        let data = vec![0; 2 * 1024 * 1024];
        let src = regular(zipped, &[("bomb", &data)], true);
        let temp = tempfile::tempdir().unwrap();
        assert!(matches!(
            extract(zipped, &src, temp.path(), Limits::default()),
            Err(ArchiveError::Ratio)
        ));
        let src = regular(zipped, &[("a/", b""), ("b/", b"")], false);
        let temp = tempfile::tempdir().unwrap();
        assert!(matches!(
            extract(
                zipped,
                &src,
                temp.path(),
                Limits {
                    max_entries: 1,
                    ..Limits::default()
                }
            ),
            Err(ArchiveError::Entries)
        ));
    }
}

#[test]
fn duplicate_case_collisions_and_existing_files_are_never_overwritten() {
    for zipped in [true, false] {
        let src = regular(zipped, &[("file", b"first"), ("FILE", b"second")], false);
        let temp = tempfile::tempdir().unwrap();
        assert!(matches!(
            extract(zipped, &src, temp.path(), Limits::default()),
            Err(ArchiveError::Duplicate)
        ));
        let src = regular(zipped, &[("existing", b"attack")], false);
        let temp = tempfile::tempdir().unwrap();
        std::fs::write(temp.path().join("existing"), b"original").unwrap();
        assert!(extract(zipped, &src, temp.path(), Limits::default()).is_err());
        assert_eq!(
            std::fs::read(temp.path().join("existing")).unwrap(),
            b"original"
        );
    }
}

#[test]
fn existing_hard_links_cannot_overwrite_an_outside_file() {
    for zipped in [true, false] {
        let temp = tempfile::tempdir().unwrap();
        let dest = temp.path().join("out");
        std::fs::create_dir(&dest).unwrap();
        std::fs::write(temp.path().join("outside"), b"original").unwrap();
        std::fs::hard_link(temp.path().join("outside"), dest.join("file")).unwrap();
        let src = regular(zipped, &[("file", b"attack")], false);
        assert!(extract(zipped, &src, &dest, Limits::default()).is_err());
        assert_eq!(
            std::fs::read(temp.path().join("outside")).unwrap(),
            b"original"
        );
    }
}

#[test]
fn malformed_archives_and_corrupt_gzip_trailers_fail() {
    for zipped in [true, false] {
        let temp = tempfile::tempdir().unwrap();
        assert!(extract(zipped, b"not an archive", temp.path(), Limits::default()).is_err());
    }
    let mut src = tar(&[("file", b"hello", b'0', "")]);
    let len = src.len();
    src[len - 8] ^= 1;
    let temp = tempfile::tempdir().unwrap();
    assert!(extract_tar_gz(src.as_slice(), temp.path(), Limits::default()).is_err());
}

#[cfg(unix)]
fn link_directory(source: &Path, target: &Path) {
    std::os::unix::fs::symlink(source, target).unwrap();
}
#[cfg(windows)]
fn link_directory(source: &Path, target: &Path) {
    let output = std::process::Command::new("cmd.exe")
        .args(["/c", "mklink", "/J"])
        .arg(target)
        .arg(source)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}
#[cfg(any(unix, windows))]
#[test]
fn refuses_existing_root_and_intermediate_directory_links() {
    for zipped in [true, false] {
        for root_link in [true, false] {
            let temp = tempfile::tempdir().unwrap();
            let outside = temp.path().join("outside");
            std::fs::create_dir(&outside).unwrap();
            let dest = temp.path().join("out");
            if root_link {
                link_directory(&outside, &dest);
            } else {
                std::fs::create_dir(&dest).unwrap();
                link_directory(&outside, &dest.join("folder"));
            }
            let src = regular(zipped, &[("folder/new", b"attack")], false);
            assert!(extract(zipped, &src, &dest, Limits::default()).is_err());
            assert!(!outside.join("folder/new").exists());
            assert!(!outside.join("new").exists());
        }
    }
}

fn gzip(bytes: &[u8]) -> Vec<u8> {
    let mut gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    gz.write_all(bytes).unwrap();
    gz.finish().unwrap()
}
fn gnu_tar(name: &str) -> Vec<u8> {
    let mut builder = tar::Builder::new(Vec::new());
    let mut header = tar::Header::new_gnu();
    header.set_mode(0o644);
    header.set_size(2);
    header.set_cksum();
    builder
        .append_data(&mut header, name, b"ok".as_slice())
        .unwrap();
    gzip(&builder.into_inner().unwrap())
}

#[test]
fn accepts_gnu_long_paths_and_enforces_the_portable_path_length_boundary() {
    let segments: Vec<_> = (0..31).map(|_| "a".repeat(127)).collect();
    let prefix = segments.join("/");
    let name = format!("{prefix}/{}", "b".repeat(128)); // 4096 bytes
    assert_eq!(name.len(), 4096);
    for zipped in [true, false] {
        let src = if zipped {
            zip(&[(&name, b"ok")], false)
        } else {
            gnu_tar(&name)
        };
        let temp = tempfile::tempdir().unwrap();
        assert_eq!(
            extract(zipped, &src, temp.path(), Limits::default()).unwrap(),
            Extracted {
                entries: 1,
                bytes: 2
            }
        );
        let bad = format!("{name}b");
        let src = if zipped {
            zip(&[(&bad, b"ok")], false)
        } else {
            gnu_tar(&bad)
        };
        let temp = tempfile::tempdir().unwrap();
        assert!(matches!(
            extract(zipped, &src, temp.path(), Limits::default()),
            Err(ArchiveError::Path)
        ));
    }
}

#[test]
fn pax_local_paths_are_validated_and_github_global_comments_are_accepted() {
    let src = tar(&[
        ("pax", b"18 path=../escape\n", b'x', ""),
        ("safe", b"ok", b'0', ""),
    ]);
    let temp = tempfile::tempdir().unwrap();
    assert!(extract_tar_gz(src.as_slice(), temp.path(), Limits::default()).is_err());
    let src = tar(&[
        ("pax", b"16 path=renamed\n", b'x', ""),
        ("safe", b"ok", b'0', ""),
    ]);
    let temp = tempfile::tempdir().unwrap();
    assert_eq!(
        extract_tar_gz(src.as_slice(), temp.path(), Limits::default()).unwrap(),
        Extracted {
            entries: 1,
            bytes: 2
        }
    );
    assert_eq!(std::fs::read(temp.path().join("renamed")).unwrap(), b"ok");
    let src = tar(&[
        ("pax_global_header", b"15 comment=abc\n", b'g', ""),
        ("file", b"ok", b'0', ""),
    ]);
    let temp = tempfile::tempdir().unwrap();
    assert_eq!(
        extract_tar_gz(src.as_slice(), temp.path(), Limits::default()).unwrap(),
        Extracted {
            entries: 1,
            bytes: 2
        }
    );
    assert_eq!(std::fs::read(temp.path().join("file")).unwrap(), b"ok");
}

#[test]
fn bounded_tar_framing_cannot_hide_an_unlimited_metadata_bomb() {
    let src = tar(&[("metadata", &[b'a'; 4096], b'g', "")]);
    let temp = tempfile::tempdir().unwrap();
    let limits = Limits {
        max_total_bytes: 0,
        max_tar_metadata_bytes: 2048,
        ..Limits::default()
    };
    assert!(matches!(
        extract_tar_gz(src.as_slice(), temp.path(), limits),
        Err(ArchiveError::Size)
    ));
}

#[test]
fn ratio_equality_is_allowed_for_a_stored_zip() {
    let src = zip(&[("file", b"hello")], false);
    let temp = tempfile::tempdir().unwrap();
    let limits = Limits {
        max_compression_ratio: 1,
        ..Limits::default()
    };
    assert_eq!(
        extract_zip(src.as_slice(), temp.path(), limits).unwrap(),
        Extracted {
            entries: 1,
            bytes: 5
        }
    );
}

#[test]
fn malformed_pax_records_and_global_path_overrides_are_refused() {
    for (payload, kind) in [
        (b"15 path=renamed\n".as_slice(), b'x'),
        (b"18 path=../escape\n".as_slice(), b'g'),
    ] {
        let src = tar(&[("pax", payload, kind, ""), ("safe", b"ok", b'0', "")]);
        let temp = tempfile::tempdir().unwrap();
        assert!(extract_tar_gz(src.as_slice(), temp.path(), Limits::default()).is_err());
    }
}

#[test]
fn zip_entry_limit_is_checked_before_central_directory_metadata_parsing() {
    let mut src = zip(&[("a", b"a"), ("b", b"b")], false);
    let headers: Vec<_> = src
        .windows(4)
        .enumerate()
        .filter_map(|(i, bytes)| (bytes == b"PK\x01\x02").then_some(i))
        .collect();
    src[headers[1]] = 0; // Keep the EOCD and first header valid; corrupt the second.
    let temp = tempfile::tempdir().unwrap();
    assert!(matches!(
        extract_zip(
            src.as_slice(),
            temp.path(),
            Limits {
                max_entries: 1,
                ..Limits::default()
            }
        ),
        Err(ArchiveError::Entries)
    ));
}

#[test]
fn unicode_casefold_collisions_match_python() {
    for zipped in [true, false] {
        for (a, b) in [("Straße", "STRASSE"), ("σ", "ς")] {
            let src = regular(zipped, &[(a, b"one"), (b, b"two")], false);
            let temp = tempfile::tempdir().unwrap();
            assert!(matches!(
                extract(zipped, &src, temp.path(), Limits::default()),
                Err(ArchiveError::Duplicate)
            ));
        }
    }
}

#[test]
fn zip_special_file_modes_are_refused() {
    for mode in [0o010644u32, 0o020644, 0o060644, 0o140644] {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        let options = zip::write::SimpleFileOptions::default()
            .system(zip::System::Unix)
            .external_attributes(mode << 16);
        zip.start_file("special", options).unwrap();
        let src = zip.finish().unwrap().into_inner();
        let temp = tempfile::tempdir().unwrap();
        let result = extract_zip(src.as_slice(), temp.path(), Limits::default());
        assert!(
            matches!(result, Err(ArchiveError::Link)),
            "mode {mode:o}: {result:?}"
        );
    }
}

#[test]
fn pax_size_must_agree_with_the_raw_header_size() {
    for raw_size in [0, 2] {
        let mut builder = tar::Builder::new(Vec::new());
        let mut pax = tar::Header::new_gnu();
        pax.set_path("pax").unwrap();
        pax.set_mode(0o644);
        pax.set_entry_type(tar::EntryType::new(b'x'));
        pax.set_size(9);
        pax.set_cksum();
        builder.append(&pax, b"9 size=2\n".as_slice()).unwrap();
        let mut file = tar::Header::new_gnu();
        file.set_path("file").unwrap();
        file.set_mode(0o644);
        file.set_size(raw_size);
        file.set_cksum();
        builder.append(&file, b"ok".as_slice()).unwrap();
        let src = gzip(&builder.into_inner().unwrap());
        let temp = tempfile::tempdir().unwrap();
        let result = extract_tar_gz(src.as_slice(), temp.path(), Limits::default());
        if raw_size == 0 {
            assert!(matches!(result, Err(ArchiveError::Size)));
        } else {
            assert_eq!(
                result.unwrap(),
                Extracted {
                    entries: 1,
                    bytes: 2
                }
            );
        }
    }
}

#[test]
fn duplicate_pax_size_keys_cannot_select_different_values_between_passes() {
    let src = tar(&[
        ("pax", b"9 size=0\n9 size=2\n", b'x', ""),
        ("file", b"\0\0", b'0', ""),
    ]);
    let temp = tempfile::tempdir().unwrap();
    assert!(matches!(
        extract_tar_gz(src.as_slice(), temp.path(), Limits::default()),
        Err(ArchiveError::Size)
    ));
}

#[test]
fn files_larger_than_one_copy_buffer_extract_completely() {
    // Incompressible bytes spanning several 64 KiB copy chunks.
    let mut state = 0x2545_f491_u32;
    let data: Vec<u8> = (0..200 * 1024)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 17;
            state ^= state << 5;
            state.to_le_bytes()[0]
        })
        .collect();
    for zip_format in [true, false] {
        let src = regular(zip_format, &[("big.bin", data.as_slice())], zip_format);
        let temp = tempfile::tempdir().unwrap();
        let dest = temp.path().join("out");
        let extracted = extract(zip_format, &src, &dest, Limits::default()).unwrap();
        assert_eq!(
            extracted,
            Extracted {
                entries: 1,
                bytes: data.len() as u64
            }
        );
        assert_eq!(std::fs::read(dest.join("big.bin")).unwrap(), data);
    }
}

#[test]
fn refuses_windows_short_name_aliases_on_every_platform() {
    // SR-014: `~` and digits ending the base name, in any component.
    for zipped in [true, false] {
        for name in [
            "LONGDI~1/b.txt",
            "longdi~1/b.txt",
            "FILENA~12.TXT",
            "dir/PROGRA~1/x.txt",
            "a~1",
            "~1",
            "x~0099.t",
            "LO1A2B~1.TAR.GZ",
            "a~b~2",
        ] {
            let temp = tempfile::tempdir().unwrap();
            let dest = temp.path().join("out");
            let src = regular(zipped, &[("ok.txt", b"ok"), (name, b"bad")], false);
            assert!(
                matches!(
                    extract(zipped, &src, &dest, Limits::default()),
                    Err(ArchiveError::Path)
                ),
                "{name}, zip={zipped}"
            );
            let top = name.split('/').next().unwrap();
            assert!(!dest.join(top).exists(), "{name} was written");
        }
    }
}

#[test]
fn keeps_tilde_names_that_are_not_short_name_aliases() {
    let names = [
        "a~b",
        "~tmp",
        "a~",
        "~",
        "a~1b",
        "x.y~1",
        "back~up.txt",
        "v~.1",
        "~~",
    ];
    for zipped in [true, false] {
        let temp = tempfile::tempdir().unwrap();
        let dest = temp.path().join("out");
        let entries: Vec<(&str, &[u8])> = names.iter().map(|n| (*n, &b"x"[..])).collect();
        let src = regular(zipped, &entries, false);
        let extracted = extract(zipped, &src, &dest, Limits::default()).unwrap();
        assert_eq!(extracted.entries, names.len(), "zip={zipped}");
        for name in names {
            assert_eq!(std::fs::read(dest.join(name)).unwrap(), b"x", "{name}");
        }
    }
}

#[cfg(windows)]
#[test]
fn short_name_alias_cannot_land_in_an_existing_long_directory_on_windows() {
    // The SR-014 PoC on a volume that creates 8.3 names (the system temp dir).
    for zipped in [true, false] {
        let temp = tempfile::tempdir().unwrap();
        let dest = temp.path().join("out");
        std::fs::create_dir_all(dest.join("longdirectoryname")).unwrap();
        if !dest.join("LONGDI~1").is_dir() {
            eprintln!(
                "skipped: 8.3 short names are not created in {}",
                temp.path().display()
            );
            return;
        }
        let src = regular(
            zipped,
            &[("longdirectoryname/a.txt", b"a"), ("LONGDI~1/b.txt", b"b")],
            false,
        );
        assert!(
            matches!(
                extract(zipped, &src, &dest, Limits::default()),
                Err(ArchiveError::Path)
            ),
            "zip={zipped}"
        );
        assert!(!dest.join("longdirectoryname").join("b.txt").exists());
    }
}
