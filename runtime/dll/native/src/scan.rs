//! In-process heap scan for Keen ObjectID+RegionID+LayerID triples.
//!
//! When a byte in a small window around a newly seen triple flips 0→1, we treat
//! that as the chest/object open (mirrors mem-path RAM DUMP heuristics).

use std::collections::{HashMap, HashSet};
use std::mem;
use std::ptr;
use std::sync::Mutex;

use serde::Deserialize;
use windows::Win32::System::Memory::{
    VirtualQuery, MEM_COMMIT, MEMORY_BASIC_INFORMATION, PAGE_EXECUTE_READWRITE,
    PAGE_EXECUTE_WRITECOPY, PAGE_READWRITE, PAGE_WRITECOPY,
};

const WINDOW: isize = 0x80;
const MAX_ANCHORS_PER_WATCH: usize = 64;

#[derive(Debug, Clone, Deserialize)]
pub struct Watch {
    pub region_id: u32,
    pub layer_id: u32,
    pub object_id: u32,
    #[serde(default = "default_triggered")]
    pub value_key: String,
}

fn default_triggered() -> String {
    "Triggered".into()
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct OpenEvent {
    pub region_id: u32,
    pub layer_id: u32,
    pub object_id: u32,
    pub value_key: String,
}

#[derive(Clone)]
struct AnchorState {
    addr: usize,
    /// Bytes at [addr-WINDOW, addr+4+WINDOW) from the last sample where the
    /// ObjectID dword sat at ``addr``.
    prev: Vec<u8>,
    armed: bool,
}

static STATES: Mutex<Option<HashMap<(u32, u32, u32), Vec<AnchorState>>>> = Mutex::new(None);
static REPORTED: Mutex<Option<HashSet<(u32, u32, u32)>>> = Mutex::new(None);

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

fn pack_triple(object_id: u32, region_id: u32, layer_id: u32) -> [u8; 12] {
    let mut out = [0u8; 12];
    out[0..4].copy_from_slice(&object_id.to_le_bytes());
    out[4..8].copy_from_slice(&region_id.to_le_bytes());
    out[8..12].copy_from_slice(&layer_id.to_le_bytes());
    out
}

fn find_triples(object_id: u32, region_id: u32, layer_id: u32) -> Vec<usize> {
    let needle = pack_triple(object_id, region_id, layer_id);
    let mut hits = Vec::new();
    let mut address = 0usize;
    loop {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        let got = unsafe {
            VirtualQuery(
                Some(address as *const _),
                &mut mbi,
                mem::size_of::<MEMORY_BASIC_INFORMATION>(),
            )
        };
        if got == 0 {
            break;
        }
        let base = mbi.BaseAddress as usize;
        let size = mbi.RegionSize;
        let next = base.saturating_add(size);
        if next <= address {
            break;
        }

        if mbi.State == MEM_COMMIT && is_writable_protect(mbi.Protect.0) && size >= 12 {
            let slice = unsafe { std::slice::from_raw_parts(base as *const u8, size) };
            let mut off = 0usize;
            while off + 12 <= slice.len() {
                if slice[off..off + 12] == needle {
                    hits.push(base + off);
                    if hits.len() >= MAX_ANCHORS_PER_WATCH {
                        return hits;
                    }
                    off += 4;
                } else {
                    off += 4; // dword-aligned search
                }
            }
        }
        address = next;
    }
    hits
}

fn read_window(addr: usize) -> Option<Vec<u8>> {
    let start = addr.checked_sub(WINDOW as usize)?;
    let len = (WINDOW as usize) * 2 + 12;
    // VirtualQuery to ensure readable
    let mut mbi = MEMORY_BASIC_INFORMATION::default();
    let got = unsafe {
        VirtualQuery(
            Some(start as *const _),
            &mut mbi,
            mem::size_of::<MEMORY_BASIC_INFORMATION>(),
        )
    };
    if got == 0 || mbi.State != MEM_COMMIT {
        return None;
    }
    let end = start + len;
    let region_end = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
    if end > region_end {
        return None;
    }
    let mut buf = vec![0u8; len];
    unsafe {
        ptr::copy_nonoverlapping(start as *const u8, buf.as_mut_ptr(), len);
    }
    Some(buf)
}

fn zero_to_one(prev: &[u8], cur: &[u8]) -> bool {
    if prev.len() != cur.len() {
        return false;
    }
    prev.iter().zip(cur.iter()).any(|(&p, &c)| p == 0 && c == 1)
}

pub fn poll_opens(watches: &[Watch]) -> Vec<OpenEvent> {
    let mut out = Vec::new();
    let mut states_guard = STATES.lock().unwrap_or_else(|e| e.into_inner());
    if states_guard.is_none() {
        *states_guard = Some(HashMap::new());
    }
    let states = states_guard.as_mut().unwrap();

    let mut reported_guard = REPORTED.lock().unwrap_or_else(|e| e.into_inner());
    if reported_guard.is_none() {
        *reported_guard = Some(HashSet::new());
    }
    let reported = reported_guard.as_mut().unwrap();

    for w in watches {
        let key = (w.object_id, w.region_id, w.layer_id);
        if reported.contains(&key) {
            continue;
        }
        let hits = find_triples(w.object_id, w.region_id, w.layer_id);
        let entry = states.entry(key).or_default();

        let hit_set: HashSet<usize> = hits.iter().copied().collect();
        entry.retain(|a| hit_set.contains(&a.addr));

        for addr in hits {
            let Some(cur) = read_window(addr) else {
                continue;
            };
            if let Some(anchor) = entry.iter_mut().find(|a| a.addr == addr) {
                if anchor.armed && zero_to_one(&anchor.prev, &cur) {
                    reported.insert(key);
                    out.push(OpenEvent {
                        region_id: w.region_id,
                        layer_id: w.layer_id,
                        object_id: w.object_id,
                        value_key: w.value_key.clone(),
                    });
                    anchor.prev = cur;
                    break;
                }
                anchor.prev = cur;
                anchor.armed = true;
            } else if entry.len() < MAX_ANCHORS_PER_WATCH {
                entry.push(AnchorState {
                    addr,
                    prev: cur,
                    armed: false, // second sample arms 0→1 detection
                });
            }
        }
    }
    out
}
