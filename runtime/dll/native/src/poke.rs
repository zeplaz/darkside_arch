//! In-process memory write for the DLL runtime "poke" command.
//!
//! The Python host resolves a targets.json row into an absolute address
//! (module base + pointer chain, same walk as runtime.mem.win32.resolve_address)
//! and sends ``{"op":"poke","address":…,"bytes":"<hex>"}`` over IPC. This module
//! writes those bytes directly into this (the game's own) address space — the
//! proof that the injected DLL can actually mutate the game, not just watch it.
//!
//! Safety: we only write after VirtualQuery confirms the range is committed and
//! page-writable (same writable check the scanner uses), so a poke to a bogus
//! address fails cleanly instead of faulting the process.

use std::mem;

use windows::Win32::System::Memory::{
    VirtualQuery, MEM_COMMIT, MEMORY_BASIC_INFORMATION, PAGE_EXECUTE_READWRITE,
    PAGE_EXECUTE_WRITECOPY, PAGE_READWRITE, PAGE_WRITECOPY,
};

fn is_writable_protect(p: u32) -> bool {
    // Ignore modifier bits (GUARD, NOCACHE, …); match the base protect.
    if p & 0x100 != 0 {
        // PAGE_GUARD — touching these can raise STATUS_GUARD_PAGE_VIOLATION.
        return false;
    }
    let base = p & 0xFF;
    base == PAGE_READWRITE.0
        || base == PAGE_EXECUTE_READWRITE.0
        || base == PAGE_WRITECOPY.0
        || base == PAGE_EXECUTE_WRITECOPY.0
}

/// True when ``[addr, addr+len)`` lies entirely inside one committed,
/// writable page.
pub fn page_is_writable(addr: usize, len: usize) -> bool {
    if len == 0 {
        return false;
    }
    let mut mbi = MEMORY_BASIC_INFORMATION::default();
    let got = unsafe {
        VirtualQuery(
            Some(addr as *const _),
            &mut mbi,
            mem::size_of::<MEMORY_BASIC_INFORMATION>(),
        )
    };
    if got == 0 || mbi.State != MEM_COMMIT {
        return false;
    }
    let region_end = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
    if addr.saturating_add(len) > region_end {
        return false;
    }
    is_writable_protect(mbi.Protect.0)
}

/// Copy ``data`` into this process at ``addr``, only if the page is writable.
pub fn write_bytes(addr: usize, data: &[u8]) -> bool {
    if data.is_empty() || !page_is_writable(addr, data.len()) {
        return false;
    }
    unsafe {
        std::ptr::copy_nonoverlapping(data.as_ptr(), addr as *mut u8, data.len());
    }
    true
}
