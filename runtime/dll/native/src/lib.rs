//! Inject DLL for the dll runtime path.
//!
//! On load: connect to `python -m runtime.dll` at 127.0.0.1:27111, receive the
//! watch list (`save_object` identities), scan this process for packed
//! ObjectID+RegionID+LayerID dwords, and report `op=open` when a nearby byte
//! flips 0→1 (same idea as the mem-path heap dump, in-process).
//!
//! Build: `cargo build --release` → `target/release/darkside_arch.dll`

mod ipc;
mod scan;

use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

use windows::Win32::Foundation::{BOOL, HINSTANCE, TRUE};
use windows::Win32::System::SystemServices::DLL_PROCESS_ATTACH;

static STARTED: AtomicBool = AtomicBool::new(false);

fn worker() {
    // Host may start after the game; retry forever until process exit.
    loop {
        match ipc::run_session() {
            Ok(()) => {}
            Err(err) => {
                let _ = err;
            }
        }
        thread::sleep(Duration::from_secs(2));
    }
}

#[no_mangle]
pub extern "system" fn DllMain(
    _module: HINSTANCE,
    reason: u32,
    _reserved: *mut core::ffi::c_void,
) -> BOOL {
    if reason == DLL_PROCESS_ATTACH
        && STARTED
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
    {
        let _ = thread::spawn(worker);
    }
    TRUE
}
