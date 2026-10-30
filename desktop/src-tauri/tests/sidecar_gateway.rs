//! Task 12: the shell starts `evoflux-server serve` from the sidecar root.

#[path = "../src/sidecar_gateway.rs"]
mod sidecar_gateway;

mod sidecar_gateway_tests {
    use super::sidecar_gateway::{
        gateway_args, gateway_env, resolve_gateway_bin, GATEWAY_BIN_NAME,
    };
    use std::ffi::OsString;

    fn scratch(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "evoflux-sidecar-gateway-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn resolves_gateway_binary() {
        let root = scratch("present");
        let bin = root.join(GATEWAY_BIN_NAME);
        std::fs::write(&bin, b"").unwrap();

        assert_eq!(resolve_gateway_bin(&root).unwrap(), bin);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_gateway_binary_names_the_file() {
        let root = scratch("missing");

        let message = format!("{:#}", resolve_gateway_bin(&root).unwrap_err());
        assert!(message.contains(GATEWAY_BIN_NAME), "{message}");
        assert!(message.contains(&root.display().to_string()), "{message}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn gateway_args_match_the_python_serve_flags() {
        assert_eq!(
            gateway_args(true, 4242),
            [
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--handshake",
                "--generate-token",
                "--parent-pid",
                "4242",
            ]
        );
        assert!(!gateway_args(false, 1).contains(&"--generate-token".to_string()));
    }

    #[test]
    fn first_attempt_uses_the_gateway_default_python_wait() {
        let root = std::path::Path::new("sidecar");
        let env = gateway_env(root, 1);

        assert!(env.contains(&("EVOFLUX_SIDECAR_ROOT", OsString::from("sidecar"))));
        assert!(env
            .iter()
            .all(|(k, _)| *k != "EVOFLUX_GATEWAY_PYTHON_WAIT_S"));
    }

    #[test]
    fn retry_attempts_wait_40s_for_python_under_the_45s_handshake() {
        let env = gateway_env(std::path::Path::new("sidecar"), 2);

        assert!(env.contains(&("EVOFLUX_GATEWAY_PYTHON_WAIT_S", OsString::from("40"))));
    }
}
