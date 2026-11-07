//! Document versions (port of v3 `tests/services/test_document_versions.py`).

use std::io::Write;
use std::path::{Path, PathBuf};

use evo_office::versions::{
    is_versioned, DocumentVersions, VersionError, MAX_LABEL_CHARS, MAX_VERSIONS,
};

const SESSION: &str = "00000000-0000-0000-0000-000000000001";

struct Fixture {
    _dir: tempfile::TempDir,
    root: PathBuf,
    store: DocumentVersions,
}

fn fixture() -> Fixture {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    std::fs::create_dir_all(&root).unwrap();
    let store = DocumentVersions::new(dir.path().join("state").join("document-versions"));
    Fixture {
        _dir: dir,
        root,
        store,
    }
}

/// A complete zip package standing in for a deck whose one slide says `text`.
fn package(parts: &[(&str, &str)]) -> Vec<u8> {
    let mut bytes = Vec::new();
    {
        let mut zip = zip::ZipWriter::new(std::io::Cursor::new(&mut bytes));
        let options = zip::write::SimpleFileOptions::default();
        for (name, content) in parts {
            zip.start_file(*name, options).unwrap();
            zip.write_all(content.as_bytes()).unwrap();
        }
        zip.finish().unwrap();
    }
    bytes
}

fn deck(path: &Path, text: &str) {
    std::fs::write(path, package(&[("ppt/slides/slide1.xml", text)])).unwrap();
}

fn slide_text(path: &Path) -> String {
    let file = std::fs::File::open(path).unwrap();
    let mut archive = zip::ZipArchive::new(file).unwrap();
    let mut entry = archive.by_name("ppt/slides/slide1.xml").unwrap();
    let mut text = String::new();
    std::io::Read::read_to_string(&mut entry, &mut text).unwrap();
    text
}

fn live_deck(path: &Path, session: &str, state: &str) {
    let plan = format!(r#"{{"v":1,"total":3,"state":"{state}","session":"{session}"}}"#)
        .replace('"', "&quot;");
    let custom = format!(
        r#"<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="evo.deck"><vt:lpwstr>{plan}</vt:lpwstr></property></Properties>"#
    );
    std::fs::write(
        path,
        package(&[
            ("ppt/slides/slide1.xml", "building"),
            ("docProps/custom.xml", &custom),
        ]),
    )
    .unwrap();
}

#[test]
fn records_changes_and_steps_back_and_forward() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    deck(&deck_path, "one");

    let history = f
        .store
        .get_history(SESSION, &f.root, "deck.pptx", None)
        .unwrap();
    assert_eq!(
        history
            .versions
            .iter()
            .map(|v| v.source.as_str())
            .collect::<Vec<_>>(),
        ["baseline"]
    );
    assert!(!history.can_undo());

    f.store
        .checkpoint(SESSION, &f.root, "deck.pptx", "Make it blue", None)
        .unwrap();
    deck(&deck_path, "two");
    let history = f
        .store
        .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
        .unwrap();
    assert_eq!(history.versions.len(), 2);
    assert_eq!(history.versions.last().unwrap().label, "Make it blue");
    assert!(history.can_undo() && !history.can_redo());
    let two = std::fs::read(&deck_path).unwrap();

    let history = f
        .store
        .step(SESSION, &f.root, "deck.pptx", -1, None)
        .unwrap();
    assert!(history.can_redo());
    assert_eq!(slide_text(&deck_path), "one");
    // The restored file is already the head: the watcher records nothing new.
    let again = f
        .store
        .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
        .unwrap();
    assert_eq!(again.versions.len(), 2);

    f.store
        .step(SESSION, &f.root, "deck.pptx", 1, None)
        .unwrap();
    assert_eq!(std::fs::read(&deck_path).unwrap(), two);
    let error = f
        .store
        .step(SESSION, &f.root, "deck.pptx", 1, None)
        .unwrap_err();
    assert!(matches!(error, VersionError::Invalid(ref m) if m == "Nothing to redo."));
}

#[test]
fn a_new_save_after_undo_replaces_the_redo_branch() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    for text in ["one", "two"] {
        deck(&deck_path, text);
        f.store
            .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
            .unwrap();
    }
    f.store
        .step(SESSION, &f.root, "deck.pptx", -1, None)
        .unwrap();

    deck(&deck_path, "three");
    let history = f
        .store
        .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
        .unwrap();

    assert_eq!(history.versions.len(), 2);
    assert!(!history.can_redo());
    let blobs = std::fs::read_dir(f.store.history_dir(SESSION, "deck.pptx").join("blobs"))
        .unwrap()
        .count();
    assert_eq!(blobs, 2, "the dropped version's bytes are gone too");
}

#[test]
fn ignores_half_written_files_and_live_decks() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    std::fs::write(&deck_path, b"PK\x03\x04 not finished").unwrap();
    assert!(f
        .store
        .get_history(SESSION, &f.root, "deck.pptx", None)
        .unwrap()
        .versions
        .is_empty());

    live_deck(&deck_path, SESSION, "building");
    assert!(f
        .store
        .get_history(SESSION, &f.root, "deck.pptx", Some(SESSION))
        .unwrap()
        .versions
        .is_empty());
    // Once the turn ends (no running chat) the same bytes are a version.
    assert_eq!(
        f.store
            .get_history(SESSION, &f.root, "deck.pptx", None)
            .unwrap()
            .versions
            .len(),
        1
    );
    assert!(!is_versioned("~$deck.pptx"));
    assert!(f
        .store
        .get_history(SESSION, &f.root, "notes.txt", None)
        .unwrap()
        .versions
        .is_empty());
}

#[test]
fn a_finished_live_deck_is_versioned_while_the_turn_runs() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    live_deck(&deck_path, SESSION, "done");
    let history = f
        .store
        .get_history(SESSION, &f.root, "deck.pptx", Some(SESSION))
        .unwrap();
    assert_eq!(history.versions.len(), 1);
}

#[test]
fn restoring_a_version_dropped_by_an_unrecorded_change_fails() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    for text in ["one", "two"] {
        deck(&deck_path, text);
        f.store
            .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
            .unwrap();
    }
    let history = f
        .store
        .step(SESSION, &f.root, "deck.pptx", -1, None)
        .unwrap();
    let redo_id = history.versions[1].id.clone();
    // A save nobody recorded yet: restoring keeps it, which drops the redo branch.
    deck(&deck_path, "three");
    let error = f
        .store
        .restore_version(SESSION, &f.root, "deck.pptx", &redo_id)
        .unwrap_err();
    assert_eq!(
        error.to_string(),
        "The file changed since, so that version was replaced."
    );
    assert_eq!(slide_text(&deck_path), "three");
    let error = f
        .store
        .restore_version(SESSION, &f.root, "deck.pptx", "missing")
        .unwrap_err();
    assert_eq!(error.to_string(), "That version no longer exists.");
}

#[test]
fn keeps_at_most_fifty_versions_and_their_blobs() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    for n in 0..MAX_VERSIONS + 5 {
        deck(&deck_path, &format!("v{n}"));
        f.store
            .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
            .unwrap();
    }
    let history = f
        .store
        .get_history(SESSION, &f.root, "deck.pptx", None)
        .unwrap();
    assert_eq!(history.versions.len(), MAX_VERSIONS);
    assert_eq!(
        history.head.as_ref(),
        Some(&history.versions.last().unwrap().id)
    );
    let blobs = std::fs::read_dir(f.store.history_dir(SESSION, "deck.pptx").join("blobs"))
        .unwrap()
        .count();
    assert_eq!(blobs, MAX_VERSIONS);
    // Re-reading the manifest gives the same history.
    let reread = DocumentVersions::new(f.store.root().to_path_buf())
        .get_history(SESSION, &f.root, "deck.pptx", None)
        .unwrap();
    assert_eq!(reread, history);
}

#[test]
fn a_checkpoint_label_applies_once_and_is_cut() {
    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    deck(&deck_path, "one");
    let long = "x".repeat(MAX_LABEL_CHARS + 50);
    let history = f
        .store
        .checkpoint(SESSION, &f.root, "deck.pptx", &format!("  {long}  "), None)
        .unwrap();
    assert_eq!(history.versions[0].source, "baseline");
    deck(&deck_path, "two");
    let history = f
        .store
        .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
        .unwrap();
    assert_eq!(history.versions[1].label.chars().count(), MAX_LABEL_CHARS);
    assert_eq!(history.versions[1].source, "change");
    deck(&deck_path, "three");
    let history = f
        .store
        .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
        .unwrap();
    assert_eq!(history.versions[2].label, "");
    // A second checkpoint on an unchanged file records nothing.
    let history = f
        .store
        .checkpoint(SESSION, &f.root, "deck.pptx", "", None)
        .unwrap();
    assert_eq!(history.versions.len(), 3);
}

#[test]
fn deleting_a_chat_removes_its_histories() {
    let f = fixture();
    deck(&f.root.join("deck.pptx"), "one");
    f.store
        .get_history(SESSION, &f.root, "deck.pptx", None)
        .unwrap();
    let dir = f.store.history_dir(SESSION, "deck.pptx");
    assert!(dir.join("manifest.json").is_file());
    f.store.delete_chat(SESSION).unwrap();
    assert!(!dir.exists());
    f.store.delete_chat(SESSION).unwrap();
}

#[cfg(windows)]
#[test]
fn a_locked_file_is_reported_after_retries() {
    use std::os::windows::fs::OpenOptionsExt;

    let f = fixture();
    let deck_path = f.root.join("deck.pptx");
    for text in ["one", "two"] {
        deck(&deck_path, text);
        f.store
            .record_version(SESSION, &f.root, "deck.pptx", "", "change", None)
            .unwrap();
    }
    let holder = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(0)
        .open(&deck_path)
        .unwrap();
    let error = f
        .store
        .step(SESSION, &f.root, "deck.pptx", -1, None)
        .unwrap_err();
    assert!(matches!(error, VersionError::Locked), "{error:?}");
    assert_eq!(
        error.to_string(),
        "The file is open elsewhere; close it and retry."
    );
    drop(holder);
    // No restore temp files are left behind.
    let leftovers: Vec<_> = std::fs::read_dir(&f.root)
        .unwrap()
        .flatten()
        .filter(|e| e.file_name().to_string_lossy().ends_with(".restore"))
        .collect();
    assert!(leftovers.is_empty());
}
