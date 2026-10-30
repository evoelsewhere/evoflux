//! Filesystem layout derived from [`Settings`].
//!
//! Port of the `EVOFLUX_*_DIR` roots in `app/core/config.py`; the database is
//! `{data}/evoflux.db` and application logs `{state}/logs/app/`
//! (`app/core/logging_config.py`).

use std::path::PathBuf;

use crate::config::Settings;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Paths {
    pub data_dir: PathBuf,
    pub config_dir: PathBuf,
    pub state_dir: PathBuf,
    pub db_file: PathBuf,
    pub log_dir: PathBuf,
}

impl Paths {
    pub fn resolve(settings: &Settings) -> Self {
        Self {
            db_file: settings.data_dir.join("evoflux.db"),
            log_dir: settings.state_dir.join("logs").join("app"),
            data_dir: settings.data_dir.clone(),
            config_dir: settings.config_dir.clone(),
            state_dir: settings.state_dir.clone(),
        }
    }
}
