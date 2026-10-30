//! Run unavoidable synchronous work off the async runtime.

use crate::error::ApiError;

/// Run `f` on the blocking pool. A panic inside `f` becomes a 500.
pub async fn run<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Result<T, ApiError> {
    match tokio::task::spawn_blocking(f).await {
        Ok(value) => Ok(value),
        Err(error) => {
            tracing::error!(%error, "blocking_task_failed");
            Err(ApiError::internal())
        }
    }
}
