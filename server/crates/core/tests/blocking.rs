#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use axum::http::StatusCode;
use evoflux_core::blocking;

#[tokio::test]
async fn run_returns_the_closure_value() {
    assert_eq!(blocking::run(|| 21 * 2).await.unwrap(), 42);
}

#[tokio::test]
async fn run_maps_a_panicking_closure_to_a_500() {
    let err = blocking::run(|| -> u8 { panic!("boom") })
        .await
        .unwrap_err();
    assert_eq!(err.status, StatusCode::INTERNAL_SERVER_ERROR);
}
