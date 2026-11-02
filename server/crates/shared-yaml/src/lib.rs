//! YAML with PyYAML's semantics, for the files and front matter Python
//! EvoFlux reads with `yaml.safe_load` and writes with `yaml.safe_dump`.
//!
//! [`load`] is `safe_load` (YAML 1.1 implicit types: `yes`/`off` booleans,
//! `017` octal, `1:30` sexagesimal, timestamps, `<<` merge keys). Values are
//! [`Value`], which keeps what JSON cannot hold (dates, non-string keys);
//! [`Value::to_json`] and [`Value::from_json`] convert. [`dump`] is
//! `safe_dump(default_flow_style=False)` byte for byte.
//!
//! Known differences from PyYAML, all on input no EvoFlux file is expected
//! to hold: error messages are not PyYAML's; `!!binary`, `!!set`, `!!omap`
//! and `!!pairs` are refused; integers beyond `i128` are refused; nesting
//! deeper than [`MAX_DEPTH`] and alias expansion past [`MAX_NODES`] values
//! are refused; raw U+0085, U+2028 and U+2029 (line breaks in YAML 1.1,
//! content in the YAML 1.2 scanner used here) are refused; recursive
//! aliases are refused; a value used twice is never written with an anchor.

#![forbid(unsafe_code)]

mod dump;
mod load;
mod value;

pub use dump::{dump, DumpOpts};
pub use load::{load, MAX_DEPTH, MAX_NODES};
pub use value::{python_float_repr, Mapping, Time, Timestamp, Value};

/// Why a document could not be loaded. Messages carry positions, never the
/// document's text.
#[derive(Debug, thiserror::Error)]
pub enum YamlError {
    #[error("{0}")]
    Syntax(String),
    #[error("expected a single document in the stream")]
    MultipleDocuments,
    #[error("{0}")]
    Construct(String),
    #[error("nesting deeper than {0} levels")]
    TooDeep(usize),
    #[error("aliases expand the document past {0} values")]
    TooLarge(usize),
}
