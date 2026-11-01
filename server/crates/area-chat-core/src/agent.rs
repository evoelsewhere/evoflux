//! The Work lead agent as `app/agent/config.py` reads it (`parse_agent_md`,
//! `resolve_agent_roster`): `role: lead` files in `<config>/agents/*.md`,
//! `evoflux` by default. Only what a chat-core turn needs is read: name,
//! model, thinking level and the prompt body.

use std::path::Path;

use evoflux_core::config::Settings;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LeadAgent {
    pub name: String,
    pub model: Option<String>,
    pub thinking_level: Option<String>,
    pub prompt: String,
}

/// Split `---` front matter from the body, as `parse_agent_md` does.
fn split_front_matter(text: &str) -> Option<(&str, &str)> {
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    let rest = text.strip_prefix("---")?;
    let rest = rest
        .strip_prefix("\r\n")
        .or_else(|| rest.strip_prefix('\n'))?;
    let mut offset = 0;
    for line in rest.split_inclusive('\n') {
        if line.trim_end() == "---" {
            let body = rest.get(offset + line.len()..).unwrap_or_default();
            return Some((rest.get(..offset).unwrap_or_default(), body));
        }
        offset += line.len();
    }
    None
}

/// A scalar `key: value` from simple YAML front matter (quotes removed).
fn scalar(front: &str, key: &str) -> Option<String> {
    front.lines().find_map(|line| {
        let (k, v) = line.split_once(':')?;
        if k.trim() != key || line.starts_with([' ', '\t']) {
            return None;
        }
        let v = v.trim();
        let v = v
            .strip_prefix('"')
            .and_then(|s| s.strip_suffix('"'))
            .or_else(|| v.strip_prefix('\'').and_then(|s| s.strip_suffix('\'')))
            .unwrap_or(v);
        (!v.is_empty() && v != "null" && v != "~").then(|| v.to_owned())
    })
}

pub(crate) fn parse_agent_md(text: &str, file_stem: &str) -> Option<(String, LeadAgent)> {
    let (front, body) = split_front_matter(text)?;
    let role = scalar(front, "role").unwrap_or_else(|| "member".to_owned());
    let agent = LeadAgent {
        name: scalar(front, "name").unwrap_or_else(|| file_stem.to_owned()),
        model: scalar(front, "model"),
        thinking_level: scalar(front, "thinking_level"),
        prompt: body.trim().to_owned(),
    };
    Some((role, agent))
}

/// The configured Work leads, sorted by name.
pub(crate) async fn work_leads(config_dir: &Path) -> Vec<LeadAgent> {
    let dir = config_dir.join("agents");
    let Ok(mut entries) = tokio::fs::read_dir(&dir).await else {
        return Vec::new();
    };
    let mut leads = Vec::new();
    while let Ok(Some(entry)) = entries.next_entry().await {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("md") {
            continue;
        }
        let stem = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or_default()
            .to_owned();
        let Ok(text) = tokio::fs::read_to_string(&path).await else {
            continue;
        };
        if let Some((role, agent)) = parse_agent_md(&text, &stem) {
            if role == "lead" {
                leads.push(agent);
            }
        }
    }
    leads.sort_by(|a, b| a.name.cmp(&b.name));
    leads
}

/// `resolve_agent_roster`'s lead: the requested one, else `evoflux`, else the first.
pub(crate) fn select_lead(leads: Vec<LeadAgent>, requested: Option<&str>) -> Option<LeadAgent> {
    let wanted = requested
        .map(str::to_owned)
        .or_else(|| {
            leads
                .iter()
                .any(|l| l.name == "evoflux")
                .then(|| "evoflux".to_owned())
        })
        .or_else(|| leads.first().map(|l| l.name.clone()))?;
    leads.into_iter().find(|l| l.name == wanted)
}

/// Settings for one turn: the startup settings with the provider variables of
/// `<config>/.env` on top, because saving a provider in Settings writes that
/// file (and `os.environ` in Python) while the server runs.
pub(crate) async fn turn_settings(base: &Settings) -> Settings {
    let path = base.config_dir.join(".env");
    match tokio::fs::read_to_string(&path).await {
        Ok(text) => {
            let pairs = evoflux_core::config::parse_dotenv(&text);
            base.with_provider_vars(pairs.iter().map(|(k, v)| (k.as_str(), v.as_str())))
        }
        Err(_) => base.clone(),
    }
}

/// The provider's own name for a `provider:model` id (what its chunks report).
pub(crate) fn wire_model(model: &str) -> &str {
    model.split_once(':').map_or(model, |(_, m)| m)
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    const SEED: &str = "---\nname: evoflux\nrole: lead\nmodel: router9:mock-model\nthinking_level: low\nskills: [intelligent-ui]\n---\n\n<!-- note -->\n";

    #[test]
    fn parses_the_seeded_lead() {
        let (role, agent) = parse_agent_md(SEED, "evoflux").unwrap();
        assert_eq!(role, "lead");
        assert_eq!(agent.name, "evoflux");
        assert_eq!(agent.model.as_deref(), Some("router9:mock-model"));
        assert_eq!(agent.thinking_level.as_deref(), Some("low"));
        assert_eq!(agent.prompt, "<!-- note -->");
    }

    #[test]
    fn front_matter_variants() {
        let (role, agent) = parse_agent_md(
            "\u{feff}---\r\nmodel: 'p:m'\r\nname: \"x\"\r\n---\r\nbody\r\n",
            "f",
        )
        .unwrap();
        assert_eq!(role, "member");
        assert_eq!(agent.name, "x");
        assert_eq!(agent.model.as_deref(), Some("p:m"));
        assert_eq!(agent.prompt, "body");
        let (_, agent) = parse_agent_md("---\nmodel: null\n  name: nested\n---\n", "stem").unwrap();
        assert_eq!(agent.name, "stem");
        assert_eq!(agent.model, None);
        assert!(parse_agent_md("no front matter", "f").is_none());
        assert!(parse_agent_md("---\nunterminated", "f").is_none());
    }

    fn lead(name: &str) -> LeadAgent {
        LeadAgent {
            name: name.into(),
            model: None,
            thinking_level: None,
            prompt: String::new(),
        }
    }

    #[test]
    fn selects_requested_then_evoflux_then_first() {
        let leads = vec![lead("alpha"), lead("evoflux"), lead("zeta")];
        assert_eq!(
            select_lead(leads.clone(), Some("zeta")).unwrap().name,
            "zeta"
        );
        assert_eq!(select_lead(leads.clone(), None).unwrap().name, "evoflux");
        assert!(select_lead(leads, Some("missing")).is_none());
        assert_eq!(
            select_lead(vec![lead("b"), lead("a")], None).unwrap().name,
            "b"
        );
        assert!(select_lead(Vec::new(), None).is_none());
    }

    #[tokio::test]
    async fn reads_leads_and_provider_overrides_from_the_config_dir() {
        let dir = tempfile::tempdir().unwrap();
        let agents = dir.path().join("agents");
        std::fs::create_dir_all(agents.join("coding")).unwrap();
        std::fs::write(agents.join("evoflux.md"), SEED).unwrap();
        std::fs::write(agents.join("helper.md"), "---\nname: helper\n---\n").unwrap();
        std::fs::write(
            agents.join("notes.txt"),
            SEED.replace("name: evoflux", "name: ghost"),
        )
        .unwrap();
        std::fs::write(agents.join("coding").join("evoflux.md"), SEED).unwrap();
        let leads = work_leads(dir.path()).await;
        assert_eq!(leads.len(), 1);
        assert_eq!(leads[0].name, "evoflux");
        assert!(work_leads(&dir.path().join("missing")).await.is_empty());

        let vars = std::collections::HashMap::from([(
            "EVOFLUX_CONFIG_DIR".to_owned(),
            dir.path().to_string_lossy().into_owned(),
        )]);
        let base = Settings::from_vars(&vars, None, dir.path()).unwrap();
        assert!(turn_settings(&base)
            .await
            .provider_var("ROUTER9_API_KEY")
            .is_none());
        std::fs::write(dir.path().join(".env"), "ROUTER9_API_KEY=k\nAPP_ENV=dev\n").unwrap();
        let settings = turn_settings(&base).await;
        assert_eq!(
            settings.provider_var("ROUTER9_API_KEY").unwrap().expose(),
            "k"
        );
        assert_eq!(settings.app_env, base.app_env);
    }

    #[test]
    fn wire_model_strips_the_provider() {
        assert_eq!(wire_model("router9:mock-model"), "mock-model");
        assert_eq!(wire_model("bare"), "bare");
    }
}
