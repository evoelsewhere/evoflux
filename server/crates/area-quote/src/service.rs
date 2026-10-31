//! Port of app/services/quote_service.py.

use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;

const FALLBACK_QUOTE: &str = "First, solve the problem. Then, write the code.";
const FALLBACK_AUTHOR: &str = "John Johnson";
const CACHE_FILENAME: &str = "quoteoftheday.json";
const TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Quote {
    pub quote: String,
    pub author: String,
}

impl Quote {
    fn fallback() -> Self {
        Self {
            quote: FALLBACK_QUOTE.to_owned(),
            author: FALLBACK_AUTHOR.to_owned(),
        }
    }

    /// Compact JSON in field order, like FastAPI's response body.
    pub(crate) fn to_json(&self) -> String {
        format!(
            r#"{{"quote":{},"author":{}}}"#,
            json_string(&self.quote),
            json_string(&self.author)
        )
    }
}

fn json_string(text: &str) -> String {
    Value::String(text.to_owned()).to_string()
}

pub(crate) type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Any failure of the outbound call (status, network, JSON); all end in the fallback.
#[derive(Debug)]
pub(crate) struct FetchError;

/// `GET https://api.api-ninjas.com/v2/quoteoftheday` with `X-Api-Key`.
pub(crate) trait Fetcher: Send + Sync {
    fn fetch<'a>(&'a self, api_key: &'a str) -> BoxFuture<'a, Result<Value, FetchError>>;
}

pub(crate) trait Clock: Send + Sync {
    fn unix_seconds(&self) -> i64;
}

pub(crate) struct QuoteService {
    cache_path: PathBuf,
    api_key: Option<String>,
    fetcher: Arc<dyn Fetcher>,
    clock: Arc<dyn Clock>,
}

struct SystemClock;

impl Clock for SystemClock {
    fn unix_seconds(&self) -> i64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| i64::try_from(elapsed.as_secs()).unwrap_or(i64::MAX))
            .unwrap_or(0)
    }
}

/// There is no HTTPS client in the workspace yet (NOTES.md), so every fetch fails.
struct UnavailableFetcher;

impl Fetcher for UnavailableFetcher {
    fn fetch<'a>(&'a self, _api_key: &'a str) -> BoxFuture<'a, Result<Value, FetchError>> {
        Box::pin(async { Err(FetchError) })
    }
}

impl QuoteService {
    pub(crate) fn new(
        cache_dir: &Path,
        api_key: Option<String>,
        fetcher: Arc<dyn Fetcher>,
        clock: Arc<dyn Clock>,
    ) -> Self {
        Self {
            cache_path: cache_dir.join(CACHE_FILENAME),
            api_key,
            fetcher,
            clock,
        }
    }

    pub(crate) fn production(cache_dir: PathBuf) -> Self {
        Self::new(
            &cache_dir,
            None,
            Arc::new(UnavailableFetcher),
            Arc::new(SystemClock),
        )
    }

    fn today(&self) -> String {
        utc_date(self.clock.unix_seconds())
    }

    /// Today's cached quote, else `None` (every failure is a miss).
    async fn read_cache(&self) -> Option<Quote> {
        let bytes = tokio::fs::read(&self.cache_path).await.ok()?;
        let quote = parse_cache(&bytes, &self.today());
        if quote.is_none() && !bytes.iter().all(u8::is_ascii_whitespace) {
            tracing::debug!("quote_cache_read_failed");
        }
        quote
    }

    async fn write_cache(&self, quote: &Quote) {
        let body = format!(
            r#"{{"date": {}, "quote": {}, "author": {}}}"#,
            json_string(&self.today()),
            json_string(&quote.quote),
            json_string(&quote.author)
        );
        let result = async {
            if let Some(parent) = self.cache_path.parent() {
                tokio::fs::create_dir_all(parent).await?;
            }
            tokio::fs::write(&self.cache_path, body).await
        }
        .await;
        if let Err(error) = result {
            tracing::warn!(%error, "quote_cache_write_failed");
        }
    }

    pub(crate) async fn get_quote_of_the_day(&self) -> Quote {
        if let Some(cached) = self.read_cache().await {
            tracing::debug!("quote_of_the_day cache_hit");
            return cached;
        }
        let Some(api_key) = &self.api_key else {
            tracing::warn!("quote_of_the_day no_api_key, using fallback");
            return Quote::fallback();
        };
        let fetched = tokio::time::timeout(TIMEOUT, self.fetcher.fetch(api_key)).await;
        let quote = match fetched {
            Ok(Ok(data)) => parse_fetched(data),
            _ => {
                tracing::warn!("quote_of_the_day fetch_failed, using fallback");
                return Quote::fallback();
            }
        };
        let Some(quote) = quote else {
            tracing::warn!("quote_of_the_day empty_response, using fallback");
            return Quote::fallback();
        };
        self.write_cache(&quote).await;
        tracing::info!(author = %quote.author, "quote_of_the_day fetched");
        quote
    }
}

/// A cache hit needs today's date (string equality) and string `quote` and `author`.
fn parse_cache(bytes: &[u8], today: &str) -> Option<Quote> {
    let text = std::str::from_utf8(bytes).ok()?.trim();
    let data: Value = serde_json::from_str(text).ok()?;
    let data = data.as_object()?;
    if data.get("date")?.as_str()? != today {
        return None;
    }
    Some(Quote {
        quote: data.get("quote")?.as_str()?.to_owned(),
        author: data.get("author")?.as_str()?.to_owned(),
    })
}

/// A list response uses element 0; the quote must be a non-empty string and the
/// author (default `"Unknown"`) a string, otherwise the fallback applies.
fn parse_fetched(data: Value) -> Option<Quote> {
    let data = match data {
        Value::Array(items) => items.into_iter().next().unwrap_or(Value::Null),
        other => other,
    };
    // An empty list is `{}` (no quote); a non-dict raises. Both end in the fallback.
    let data = data.as_object()?;
    let quote = data
        .get("quote")?
        .as_str()
        .filter(|text| !text.is_empty())?;
    let author = match data.get("author") {
        None => "Unknown",
        Some(author) => author.as_str()?,
    };
    Some(Quote {
        quote: quote.to_owned(),
        author: author.to_owned(),
    })
}

/// `datetime.now(timezone.utc).date().isoformat()` for a Unix timestamp
/// (days-to-civil conversion, proleptic Gregorian).
fn utc_date(unix_seconds: i64) -> String {
    let z = unix_seconds.div_euclid(86_400) + 719_468;
    let era = z.div_euclid(146_097);
    let day_of_era = z.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let mp = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]
pub(crate) mod testing {
    use super::*;
    use std::sync::atomic::{AtomicI64, AtomicUsize, Ordering};

    pub(crate) const FALLBACK_JSON: &str =
        r#"{"quote":"First, solve the problem. Then, write the code.","author":"John Johnson"}"#;

    /// 2026-10-31T12:00:00Z
    pub(crate) const NOON: i64 = 1_793_448_000;

    pub(crate) struct FixedClock(pub AtomicI64);

    impl Clock for FixedClock {
        fn unix_seconds(&self) -> i64 {
            self.0.load(Ordering::SeqCst)
        }
    }

    pub(crate) struct StubFetcher {
        pub response: Option<Value>,
        pub calls: AtomicUsize,
        pub hang: bool,
    }

    impl StubFetcher {
        pub(crate) fn answering(response: Value) -> Arc<Self> {
            Arc::new(Self {
                response: Some(response),
                calls: AtomicUsize::new(0),
                hang: false,
            })
        }
        pub(crate) fn failing() -> Arc<Self> {
            Arc::new(Self {
                response: None,
                calls: AtomicUsize::new(0),
                hang: false,
            })
        }
        pub(crate) fn hanging() -> Arc<Self> {
            Arc::new(Self {
                response: None,
                calls: AtomicUsize::new(0),
                hang: true,
            })
        }
        pub(crate) fn calls(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    impl Fetcher for StubFetcher {
        fn fetch<'a>(&'a self, api_key: &'a str) -> BoxFuture<'a, Result<Value, FetchError>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async move {
                assert_eq!(api_key, "test-key");
                if self.hang {
                    std::future::pending::<()>().await;
                }
                self.response.clone().ok_or(FetchError)
            })
        }
    }

    pub(crate) fn clock_at(seconds: i64) -> Arc<FixedClock> {
        Arc::new(FixedClock(AtomicI64::new(seconds)))
    }

    /// A keyless service on the noon clock: cache or fallback only.
    pub(crate) fn service_at(dir: &Path) -> Arc<QuoteService> {
        Arc::new(QuoteService::new(
            dir,
            None,
            StubFetcher::failing(),
            clock_at(NOON),
        ))
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]
mod tests {
    use super::testing::*;
    use super::*;
    use serde_json::json;

    fn keyed(dir: &Path, fetcher: Arc<StubFetcher>, clock: Arc<FixedClock>) -> QuoteService {
        QuoteService::new(dir, Some("test-key".to_owned()), fetcher, clock)
    }

    fn cache_file(dir: &Path) -> PathBuf {
        dir.join(CACHE_FILENAME)
    }

    fn seed(dir: &Path, text: &str) {
        std::fs::write(cache_file(dir), text).unwrap();
    }

    fn seeded(date: &str) -> String {
        json!({"date": date, "quote": "Seeded “quote” — ünïcode ✓", "author": "Test Author"})
            .to_string()
    }

    fn seeded_quote() -> Quote {
        Quote {
            quote: "Seeded “quote” — ünïcode ✓".to_owned(),
            author: "Test Author".to_owned(),
        }
    }

    #[test]
    fn utc_date_formats_calendar_days() {
        assert_eq!(utc_date(0), "1970-01-01");
        assert_eq!(utc_date(-1), "1969-12-31");
        assert_eq!(utc_date(951_825_600), "2000-02-29");
        assert_eq!(utc_date(1_735_689_599), "2024-12-31");
        assert_eq!(utc_date(1_735_689_600), "2025-01-01");
        assert_eq!(utc_date(1_793_491_199), "2026-10-31");
        assert_eq!(utc_date(1_793_491_200), "2026-11-01");
    }

    /// The day boundary is midnight UTC: N-1 and N+1 miss, N hits.
    #[tokio::test]
    async fn cache_hits_only_on_the_same_utc_day() {
        let dir = tempfile::tempdir().unwrap();
        let clock = clock_at(1_793_491_199); // 2026-10-31T23:59:59Z
        let service = QuoteService::new(dir.path(), None, StubFetcher::failing(), clock.clone());
        seed(dir.path(), &seeded("2026-10-31"));
        assert_eq!(service.get_quote_of_the_day().await, seeded_quote());
        seed(dir.path(), &seeded("2026-10-30"));
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
        seed(dir.path(), &seeded("2026-11-01"));
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());

        seed(dir.path(), &seeded("2026-10-31"));
        clock
            .0
            .store(1_793_491_200, std::sync::atomic::Ordering::SeqCst); // 2026-11-01T00:00:00Z
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
        seed(dir.path(), &seeded("2026-11-01"));
        assert_eq!(service.get_quote_of_the_day().await, seeded_quote());
    }

    #[tokio::test]
    async fn missing_cache_file_is_a_miss() {
        let dir = tempfile::tempdir().unwrap();
        let service = service_at(dir.path());
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
        assert!(!cache_file(dir.path()).exists());
    }

    #[tokio::test]
    async fn unreadable_cache_shapes_are_misses() {
        let dir = tempfile::tempdir().unwrap();
        let service = service_at(dir.path());
        for content in [
            "",
            "   \n",
            "not json",
            "[]",
            "\"text\"",
            "null",
            r#"{"date": "2000-01-01"}"#,
            r#"{"quote": "x", "author": "y"}"#,
            r#"{"date": 123, "quote": "x", "author": "y"}"#,
            r#"{"date": "2026-10-31", "quote": "only a quote"}"#,
            r#"{"date": "2026-10-31", "quote": "x", "author": 5}"#,
            r#"{"date": "2026-10-31", "quote": 5, "author": "y"}"#,
        ] {
            seed(dir.path(), content);
            assert_eq!(
                service.get_quote_of_the_day().await,
                Quote::fallback(),
                "{content}"
            );
        }
        std::fs::write(cache_file(dir.path()), [0xff, 0xfe, 0x00]).unwrap();
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
    }

    #[tokio::test]
    async fn extra_cache_fields_are_ignored() {
        let dir = tempfile::tempdir().unwrap();
        seed(
            dir.path(),
            r#"{"date": "2026-10-31", "quote": "q", "author": "a", "extra": 1}"#,
        );
        let got = service_at(dir.path()).get_quote_of_the_day().await;
        assert_eq!((got.quote.as_str(), got.author.as_str()), ("q", "a"));
    }

    #[tokio::test]
    async fn cache_hit_makes_no_network_call_and_keeps_the_file() {
        let dir = tempfile::tempdir().unwrap();
        let text = seeded("2026-10-31");
        seed(dir.path(), &text);
        let fetcher = StubFetcher::answering(json!({"quote": "new", "author": "n"}));
        let service = keyed(dir.path(), fetcher.clone(), clock_at(NOON));
        assert_eq!(service.get_quote_of_the_day().await, seeded_quote());
        assert_eq!(fetcher.calls(), 0);
        assert_eq!(
            std::fs::read_to_string(cache_file(dir.path())).unwrap(),
            text
        );
    }

    #[tokio::test]
    async fn without_an_api_key_the_fallback_is_answered_and_not_cached() {
        let dir = tempfile::tempdir().unwrap();
        let fetcher = StubFetcher::answering(json!({"quote": "new", "author": "n"}));
        let service = QuoteService::new(dir.path(), None, fetcher.clone(), clock_at(NOON));
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
        assert_eq!(fetcher.calls(), 0);
        assert!(!cache_file(dir.path()).exists());
    }

    async fn fetched(response: Value) -> (Quote, tempfile::TempDir) {
        let dir = tempfile::tempdir().unwrap();
        let service = keyed(dir.path(), StubFetcher::answering(response), clock_at(NOON));
        (service.get_quote_of_the_day().await, dir)
    }

    #[tokio::test]
    async fn fetch_on_miss_returns_and_caches_the_quote() {
        let (got, dir) = fetched(json!([{"quote": "Ünï “q” ✓", "author": "Ä"}])).await;
        assert_eq!(
            got,
            Quote {
                quote: "Ünï “q” ✓".to_owned(),
                author: "Ä".to_owned()
            }
        );
        let written = std::fs::read_to_string(cache_file(dir.path())).unwrap();
        assert_eq!(
            written,
            r#"{"date": "2026-10-31", "quote": "Ünï “q” ✓", "author": "Ä"}"#
        );
    }

    #[tokio::test]
    async fn fetched_quote_is_served_from_the_cache_next_time() {
        let dir = tempfile::tempdir().unwrap();
        let fetcher = StubFetcher::answering(json!({"quote": "q", "author": "a"}));
        let service = keyed(dir.path(), fetcher.clone(), clock_at(NOON));
        let first = service.get_quote_of_the_day().await;
        let second = service.get_quote_of_the_day().await;
        assert_eq!(first, second);
        assert_eq!(fetcher.calls(), 1);
    }

    #[tokio::test]
    async fn dict_response_is_accepted_and_missing_author_is_unknown() {
        let (got, _dir) = fetched(json!({"quote": "q"})).await;
        assert_eq!(
            got,
            Quote {
                quote: "q".to_owned(),
                author: "Unknown".to_owned()
            }
        );
    }

    #[tokio::test]
    async fn unusable_responses_fall_back_without_caching() {
        for response in [
            json!([]),
            json!({}),
            json!({"author": "a"}),
            json!({"quote": "", "author": "a"}),
            json!({"quote": null, "author": "a"}),
            json!({"quote": "q", "author": 7}),
            json!({"quote": 7, "author": "a"}),
            json!("text"),
            json!(null),
            json!([1]),
        ] {
            let (got, dir) = fetched(response.clone()).await;
            assert_eq!(got, Quote::fallback(), "{response}");
            assert!(!cache_file(dir.path()).exists(), "{response}");
        }
    }

    #[tokio::test]
    async fn fetch_failure_falls_back_without_caching() {
        let dir = tempfile::tempdir().unwrap();
        let service = keyed(dir.path(), StubFetcher::failing(), clock_at(NOON));
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
        assert!(!cache_file(dir.path()).exists());
    }

    #[tokio::test(start_paused = true)]
    async fn a_hanging_fetch_times_out_after_ten_seconds() {
        let dir = tempfile::tempdir().unwrap();
        let service = keyed(dir.path(), StubFetcher::hanging(), clock_at(NOON));
        let started = tokio::time::Instant::now();
        assert_eq!(service.get_quote_of_the_day().await, Quote::fallback());
        assert_eq!(started.elapsed(), Duration::from_secs(10));
    }

    #[tokio::test]
    async fn cache_write_creates_missing_parent_directories() {
        let dir = tempfile::tempdir().unwrap();
        let nested = dir.path().join("a").join("b");
        let service = keyed(
            &nested,
            StubFetcher::answering(json!({"quote": "q", "author": "a"})),
            clock_at(NOON),
        );
        service.get_quote_of_the_day().await;
        assert!(nested.join(CACHE_FILENAME).is_file());
    }

    #[tokio::test]
    async fn cache_write_error_is_swallowed() {
        let dir = tempfile::tempdir().unwrap();
        let blocker = dir.path().join("blocker");
        std::fs::write(&blocker, "a file, not a directory").unwrap();
        let service = keyed(
            &blocker,
            StubFetcher::answering(json!({"quote": "q", "author": "a"})),
            clock_at(NOON),
        );
        let got = service.get_quote_of_the_day().await;
        assert_eq!((got.quote.as_str(), got.author.as_str()), ("q", "a"));
    }

    #[tokio::test]
    async fn cache_date_is_read_from_the_clock_when_writing() {
        let dir = tempfile::tempdir().unwrap();
        let service = keyed(
            dir.path(),
            StubFetcher::answering(json!({"quote": "q", "author": "a"})),
            clock_at(1_793_491_200),
        );
        service.get_quote_of_the_day().await;
        let written = std::fs::read_to_string(cache_file(dir.path())).unwrap();
        assert!(written.starts_with(r#"{"date": "2026-11-01""#), "{written}");
    }
}
