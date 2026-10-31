//! Port of app/services/snippets.py (`_candidate_roots`).

use std::path::{Path, PathBuf};

/// Where discovery looks, in precedence order.
pub fn candidate_roots(workspace: &Path, config_dir: &Path) -> Vec<(PathBuf, &'static str)> {
    vec![
        (
            workspace.join(".evoflux").join("snippets"),
            "project-EvoFlux",
        ),
        (config_dir.join("snippets"), "global-EvoFlux"),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_root_comes_before_the_global_one() {
        assert_eq!(
            candidate_roots(Path::new("w"), Path::new("cfg")),
            vec![
                (
                    Path::new("w/.evoflux/snippets").to_path_buf(),
                    "project-EvoFlux"
                ),
                (Path::new("cfg/snippets").to_path_buf(), "global-EvoFlux"),
            ]
        );
    }
}
