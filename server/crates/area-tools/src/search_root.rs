//! Validation of the directory root glob and grep search (`_search_root.py`).

use std::path::{Path, PathBuf};

use crate::fsutil::{exists, is_dir, is_file};
use crate::pyfmt::repr_str;
use crate::sandbox::Sandbox;

/// Resolve a search root, explaining why it is not a usable directory.
pub(crate) fn validate(
    sandbox: &Sandbox,
    directory: &str,
    tool_name: &str,
) -> Result<PathBuf, String> {
    let resolved = sandbox.validate_path(directory)?;
    if is_dir(&resolved) {
        return Ok(resolved);
    }

    let display = sandbox.display_path(&resolved);
    if is_file(&resolved) {
        let parent = sandbox.display_path(resolved.parent().unwrap_or(&resolved));
        return Err(format!(
            "{tool_name} search root is a file, not a directory: {display}. \
             Use `read` to inspect that file, or search its parent directory \
             {} with a narrower pattern.",
            repr_str(&parent)
        ));
    }

    let mut existing: &Path = &resolved;
    while !exists(existing) {
        match existing.parent() {
            Some(parent) => existing = parent,
            None => break,
        }
    }
    if is_file(existing) {
        let component = sandbox.display_path(existing);
        let parent = sandbox.display_path(existing.parent().unwrap_or(existing));
        return Err(format!(
            "{tool_name} search path has a file as a directory component: \
             {component} is a file in {}. Search its parent \
             directory {} instead.",
            repr_str(&display),
            repr_str(&parent)
        ));
    }

    Err(format!(
        "{tool_name} search directory does not exist: {display}. \
         Check the path and use an existing directory."
    ))
}
