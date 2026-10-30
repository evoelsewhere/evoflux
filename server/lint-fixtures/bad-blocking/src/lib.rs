pub async fn blocking_sleep() {
    std::thread::sleep(std::time::Duration::from_millis(1));
}

pub async fn blocking_read() {
    let _ = std::fs::read("fixture");
}

pub fn unwrap_value(value: Option<u8>) -> u8 {
    value.unwrap()
}

pub fn expect_value(value: Option<u8>) -> u8 {
    value.expect("fixture")
}

pub fn panic_value() {
    panic!("fixture");
}

pub fn todo_value() {
    todo!("fixture");
}

pub fn unimplemented_value() {
    unimplemented!("fixture");
}

pub fn index_value(values: &[u8]) -> u8 {
    values[0]
}

pub async fn hold_lock(lock: &std::sync::Mutex<()>) {
    if let Ok(guard) = lock.lock() {
        std::future::ready(()).await;
        drop(guard);
    }
}

pub fn blocking_command() {
    let _ = std::process::Command::new("fixture");
}
