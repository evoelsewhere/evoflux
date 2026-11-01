//! Provider errors: the factory's `ValueError`s, `httpx` status and transport
//! errors, chunk validation errors, and the typed errors of `app/agent/errors.py`
//! that `app/agent/agent_loop/retry.py` raises.

/// Why a provider could not be built or a call failed.
#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum ProviderError {
    /// A configuration `ValueError` from `build_provider` (bad model string, missing key).
    #[error("{0}")]
    Config(String),
    /// `UnconfiguredProviderError`: no usable provider for this model string.
    #[error("{0}")]
    Unconfigured(String),
    /// A provider Python supports that this server does not serve yet.
    #[error("provider '{0}' is not available in the Rust server yet")]
    NotPorted(String),
    /// An option such as `temperature` has a type the wire field rejects.
    #[error("invalid option {name}: {reason}")]
    InvalidOption { name: String, reason: String },
    /// The shared HTTPS client could not be built.
    #[error("{0}")]
    Client(String),
    /// `httpx.HTTPStatusError`: the provider answered with a status of 400 or more.
    #[error("provider returned HTTP {status}")]
    Status {
        status: u16,
        /// The response text, up to `MAX_ERROR_BODY_BYTES` (Python reads it all).
        body: String,
        /// The raw `Retry-After` header, if any.
        retry_after: Option<String>,
    },
    /// A transport failure. `error_type` is the `httpx` exception name Python
    /// reports (`ConnectError`, `ReadTimeout`, ...); `transient` says whether
    /// `TRANSIENT_TRANSPORT_ERRORS` covers it, so a retry may help.
    #[error("{error_type}: {message}")]
    Transport {
        error_type: String,
        message: String,
        transient: bool,
    },
    /// A stream chunk that `OpenAIStreamChunk.model_validate` rejects (`ValidationError`).
    #[error("invalid stream chunk: {0}")]
    InvalidChunk(String),
    /// `ProviderAuthenticationError` (HTTP 401/403).
    #[error("{message}")]
    Authentication {
        message: String,
        status_code: u16,
        provider: String,
    },
    /// `ContextOverflowError`: the prompt does not fit the context window.
    #[error("{message}")]
    ContextOverflow {
        message: String,
        status_code: u16,
        provider: String,
    },
    /// `ProviderRequestError`: any other rejected request.
    #[error("{message}")]
    Request {
        message: String,
        status_code: u16,
        provider: String,
    },
    /// `ProviderRateLimitError`: every provider stayed rate-limited.
    #[error("All configured LLM providers are rate-limited or quota-exhausted.")]
    RateLimited,
    /// The stream sent more than this server buffers (an SSE line or one
    /// tool call's arguments over its cap). Python has no cap; not retried.
    #[error("The provider response was too large: {what} exceeded {limit} bytes.")]
    TooLarge { what: String, limit: usize },
}

impl ProviderError {
    /// The Python exception class name, for logs and the retry notices.
    pub fn kind(&self) -> &str {
        match self {
            Self::Config(_) | Self::InvalidOption { .. } | Self::Client(_) => "ValueError",
            Self::Unconfigured(_) => "UnconfiguredProviderError",
            Self::NotPorted(_) => "NotPorted",
            Self::Status { .. } => "HTTPStatusError",
            Self::Transport { error_type, .. } => error_type,
            Self::InvalidChunk(_) => "ValidationError",
            Self::Authentication { .. } => "ProviderAuthenticationError",
            Self::ContextOverflow { .. } => "ContextOverflowError",
            Self::Request { .. } => "ProviderRequestError",
            Self::RateLimited => "ProviderRateLimitError",
            Self::TooLarge { .. } => "ResponseTooLarge",
        }
    }

    /// The HTTP status the error carries, if any.
    pub fn status_code(&self) -> Option<u16> {
        match self {
            Self::Status { status, .. } => Some(*status),
            Self::Authentication { status_code, .. }
            | Self::ContextOverflow { status_code, .. }
            | Self::Request { status_code, .. } => Some(*status_code),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ProviderError as E;

    #[test]
    fn kinds_and_status_codes_follow_the_python_exceptions() {
        let typed = |make: fn(String, u16, String) -> E| make("m".into(), 418, "p".into());
        let cases = [
            (E::Config("c".into()), "ValueError", None),
            (
                E::InvalidOption {
                    name: "n".into(),
                    reason: "r".into(),
                },
                "ValueError",
                None,
            ),
            (E::Client("c".into()), "ValueError", None),
            (
                E::Unconfigured("u".into()),
                "UnconfiguredProviderError",
                None,
            ),
            (E::NotPorted("x".into()), "NotPorted", None),
            (
                E::Status {
                    status: 500,
                    body: String::new(),
                    retry_after: None,
                },
                "HTTPStatusError",
                Some(500),
            ),
            (
                E::Transport {
                    error_type: "ConnectError".into(),
                    message: "m".into(),
                    transient: true,
                },
                "ConnectError",
                None,
            ),
            (E::InvalidChunk("x".into()), "ValidationError", None),
            (
                typed(|message, status_code, provider| E::Authentication {
                    message,
                    status_code,
                    provider,
                }),
                "ProviderAuthenticationError",
                Some(418),
            ),
            (
                typed(|message, status_code, provider| E::ContextOverflow {
                    message,
                    status_code,
                    provider,
                }),
                "ContextOverflowError",
                Some(418),
            ),
            (
                typed(|message, status_code, provider| E::Request {
                    message,
                    status_code,
                    provider,
                }),
                "ProviderRequestError",
                Some(418),
            ),
            (E::RateLimited, "ProviderRateLimitError", None),
            (
                E::TooLarge {
                    what: "an SSE line".into(),
                    limit: 1,
                },
                "ResponseTooLarge",
                None,
            ),
        ];
        for (error, kind, status) in cases {
            assert_eq!(error.kind(), kind, "{error:?}");
            assert_eq!(error.status_code(), status, "{error:?}");
        }
    }
}
