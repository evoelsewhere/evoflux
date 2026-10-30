use std::process::ExitCode;

fn main() -> ExitCode {
    evoflux_server::serve::main(std::env::args_os().skip(1))
}
