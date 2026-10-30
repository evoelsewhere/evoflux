//! The gateway routing table (`server/routing.toml`, design §3 and §3.1).
//!
//! Each `[[unit]]` names a cutover unit, its owner and its routes. Matching
//! follows the contract in the header of `server/routing.toml`, whose
//! reference is `scripts/migration/check_board.py` (`_specificity`): a trailing
//! `/**` covers the prefix and everything below it, any other route is an exact
//! path; `{name}` matches one non-empty segment and a final `{name:path}` the
//! rest of the path. The most specific route wins, ranked by segment count,
//! then literal segment count, then exact over `/**`; on a full tie the first
//! route in the table wins. Unmatched paths go to Python.
//! `EVOFLUX_ROUTE_OVERRIDE=<unit>=<owner>,...` overrides owners at runtime.

use percent_encoding::percent_decode_str;
use serde::Deserialize;
use std::collections::HashSet;
use std::path::Path;

/// Who answers a unit's routes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Owner {
    Python,
    Rust,
    /// Python answers; Rust runs the same GET in the background (Task 15).
    Shadow,
}

impl Owner {
    fn parse(raw: &str) -> Option<Self> {
        match raw {
            "python" => Some(Self::Python),
            "rust" => Some(Self::Rust),
            "shadow" => Some(Self::Shadow),
            _ => None,
        }
    }
}

/// One cutover unit as written in `routing.toml`, owner after overrides.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Unit {
    pub name: String,
    pub owner: Owner,
    pub routes: Vec<String>,
    #[serde(default)]
    pub services: Vec<String>,
    /// How the unit's pins are broken (documentation; `CUTOVER_UNITS.md`).
    #[serde(default)]
    pub pin_breakers: Vec<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum RoutingError {
    #[error("cannot read {path}: {source}")]
    Read {
        path: String,
        source: std::io::Error,
    },
    #[error("invalid routing table: {0}")]
    Parse(#[from] toml::de::Error),
    #[error("unit {0:?} is defined more than once")]
    DuplicateUnit(String),
    #[error("unit {unit:?} has invalid route {route:?}: routes start with '/', have no empty segments, use '{{param}}' only as a whole segment and '**' only as a final '/**'")]
    InvalidRoute { unit: String, route: String },
    #[error("route {route:?} is claimed by both {first:?} and {second:?}")]
    DuplicateRoute {
        route: String,
        first: String,
        second: String,
    },
    #[error("EVOFLUX_ROUTE_OVERRIDE entry {0:?} is not <unit>=python|rust|shadow")]
    InvalidOverride(String),
    #[error("EVOFLUX_ROUTE_OVERRIDE names unknown unit {0:?}")]
    UnknownOverrideUnit(String),
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct File {
    #[serde(default)]
    unit: Vec<Unit>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Segment {
    Literal(String),
    /// `{name}`; the name is not kept, so `/a/{x}` and `/a/{y}` are one route.
    Param,
    /// `{name:path}` as the last segment: the rest of the path.
    RestParam,
}

impl Segment {
    fn parse(raw: &str) -> Option<Self> {
        if raw.contains('*') {
            return None;
        }
        match raw.strip_prefix('{').and_then(|r| r.strip_suffix('}')) {
            Some(name) if name.is_empty() || name.contains(['{', '}']) => None,
            Some(name) if name.ends_with(":path") => Some(Self::RestParam),
            Some(name) if name.contains(':') => None,
            Some(_) => Some(Self::Param),
            None if raw.contains(['{', '}']) => None,
            None => Some(Self::Literal(raw.to_owned())),
        }
    }
}

/// A route split like `check_board.py`: `"/a/b"` is `["", "a", "b"]` and
/// `"/**"` is `[""]` with `glob`.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Pattern {
    base: Vec<Segment>,
    /// The route ends in `/**`.
    glob: bool,
}

/// `(segments, literal segments, 1 for an exact route)`; greater is more specific.
type Score = (usize, usize, u8);

impl Pattern {
    fn parse(route: &str) -> Option<Self> {
        if !route.starts_with('/') {
            return None;
        }
        let (base, glob) = match route.strip_suffix("/**") {
            Some(base) => (base, true),
            None => (route, false),
        };
        let base = base
            .split('/')
            .map(Segment::parse)
            .collect::<Option<Vec<_>>>()?;
        // `{name:path}` only as the last segment; empty segments only first.
        let last = base.len().saturating_sub(1);
        for (index, segment) in base.iter().enumerate() {
            let bad_rest = *segment == Segment::RestParam && index != last;
            let bad_empty = *segment == Segment::Literal(String::new()) && index != 0;
            if bad_rest || bad_empty {
                return None;
            }
        }
        Some(Self { base, glob })
    }

    /// Port of `scripts/migration/check_board.py` `_specificity`.
    fn score(&self, parts: &[&str]) -> Option<Score> {
        let exact = u8::from(!self.glob);
        let rest = self.base.last() == Some(&Segment::RestParam);
        if parts.len() < self.base.len() || (!self.glob && !rest && parts.len() != self.base.len())
        {
            return None;
        }
        let mut literals = 0;
        for (index, (want, got)) in self.base.iter().zip(parts).enumerate() {
            match want {
                Segment::RestParam => {
                    let remaining = parts.get(index..).unwrap_or_default();
                    if remaining.iter().all(|part| part.is_empty()) {
                        return None;
                    }
                    return Some((self.base.len(), literals, exact));
                }
                Segment::Param if got.is_empty() => return None,
                Segment::Param => {}
                Segment::Literal(literal) if literal == got => literals += 1,
                Segment::Literal(_) => return None,
            }
        }
        Some((self.base.len(), literals, exact))
    }
}

/// The loaded routing table.
#[derive(Debug, Clone)]
pub struct RoutingTable {
    units: Vec<Unit>,
    patterns: Vec<(Pattern, usize)>,
}

impl RoutingTable {
    /// Load `path` and apply `override_env` (the value of `EVOFLUX_ROUTE_OVERRIDE`).
    ///
    /// Called once at startup, before the server accepts connections.
    #[allow(clippy::disallowed_methods)] // startup-only read, before serving
    pub fn load(path: &Path, override_env: Option<&str>) -> Result<Self, RoutingError> {
        let text = std::fs::read_to_string(path).map_err(|source| RoutingError::Read {
            path: path.display().to_string(),
            source,
        })?;
        Self::from_toml(&text, override_env)
    }

    /// Parse a routing table from TOML text and apply `override_env`.
    pub fn from_toml(text: &str, override_env: Option<&str>) -> Result<Self, RoutingError> {
        let file: File = toml::from_str(text)?;
        let mut units = file.unit;
        let mut names = HashSet::new();
        for unit in &units {
            if !names.insert(unit.name.clone()) {
                return Err(RoutingError::DuplicateUnit(unit.name.clone()));
            }
        }
        let mut patterns: Vec<(Pattern, usize)> = Vec::new();
        for (index, unit) in units.iter().enumerate() {
            for route in &unit.routes {
                let pattern = Pattern::parse(route).ok_or_else(|| RoutingError::InvalidRoute {
                    unit: unit.name.clone(),
                    route: route.clone(),
                })?;
                if let Some((_, first)) = patterns.iter().find(|(p, _)| *p == pattern) {
                    let first = units
                        .get(*first)
                        .map(|u| u.name.clone())
                        .unwrap_or_default();
                    return Err(RoutingError::DuplicateRoute {
                        route: route.clone(),
                        first,
                        second: unit.name.clone(),
                    });
                }
                patterns.push((pattern, index));
            }
        }
        if let Some(raw) = override_env {
            apply_override(&mut units, raw)?;
        }
        Ok(Self { units, patterns })
    }

    /// The unit whose route matches `path` most specifically, if any.
    ///
    /// `path` is the raw request path; it is percent-decoded first, as
    /// Starlette does before routing.
    pub fn unit_for(&self, path: &str) -> Option<&Unit> {
        let decoded = percent_decode_str(path).decode_utf8_lossy();
        let parts: Vec<&str> = decoded.split('/').collect();
        // Strictly greater, so on a tie the first route in the table wins (`_best_match`).
        let mut best: Option<(Score, usize)> = None;
        for (pattern, index) in &self.patterns {
            if let Some(score) = pattern.score(&parts) {
                if best.as_ref().is_none_or(|(top, _)| score > *top) {
                    best = Some((score, *index));
                }
            }
        }
        best.and_then(|(_, index)| self.units.get(index))
    }

    /// Owner of `path`; unmatched paths belong to Python.
    pub fn owner_for(&self, path: &str) -> Owner {
        self.unit_for(path).map_or(Owner::Python, |unit| unit.owner)
    }

    /// Services Python must not start (`EVOFLUX_DISABLE_SERVICES`): those of
    /// the units owned by Rust, in table order, without duplicates.
    pub fn disabled_python_services(&self) -> Vec<String> {
        let mut seen = HashSet::new();
        self.units
            .iter()
            .filter(|unit| unit.owner == Owner::Rust)
            .flat_map(|unit| unit.services.iter())
            .filter(|service| seen.insert(service.as_str()))
            .cloned()
            .collect()
    }

    pub fn units(&self) -> &[Unit] {
        &self.units
    }
}

fn apply_override(units: &mut [Unit], raw: &str) -> Result<(), RoutingError> {
    for entry in raw.split(',').map(str::trim).filter(|e| !e.is_empty()) {
        let (name, owner) = entry
            .split_once('=')
            .map(|(n, o)| (n.trim(), o.trim()))
            .ok_or_else(|| RoutingError::InvalidOverride(entry.to_owned()))?;
        let owner =
            Owner::parse(owner).ok_or_else(|| RoutingError::InvalidOverride(entry.to_owned()))?;
        let unit = units
            .iter_mut()
            .find(|unit| unit.name == name)
            .ok_or_else(|| RoutingError::UnknownOverrideUnit(name.to_owned()))?;
        unit.owner = owner;
    }
    Ok(())
}
