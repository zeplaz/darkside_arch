//! Line-delimited JSON over TCP to the Python host.

use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Deserialize;
use serde_json::json;

use crate::scan::{self, Watch};
use crate::poke;

const HOST: &str = "127.0.0.1:27111";

#[derive(Debug, Deserialize)]
struct HostMsg {
    op: String,
    #[serde(default)]
    items: Vec<Watch>,
    #[serde(default)]
    address: Option<u64>,
    #[serde(default)]
    bytes: String,
    #[serde(default)]
    label: String,
}

pub fn run_session() -> Result<(), String> {
    let stream = TcpStream::connect(HOST).map_err(|e| e.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_millis(500)))
        .ok();
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .ok();

    let stream = Arc::new(Mutex::new(stream.try_clone().map_err(|e| e.to_string())?));
    {
        let mut s = stream.lock().map_err(|e| e.to_string())?;
        writeln!(
            s,
            "{}",
            json!({"op":"hello","msg":"darkside_arch","ver":1})
        )
        .map_err(|e| e.to_string())?;
        s.flush().ok();
    }

    let watches = Arc::new(Mutex::new(Vec::<Watch>::new()));
    let reader_stream = stream
        .lock()
        .map_err(|e| e.to_string())?
        .try_clone()
        .map_err(|e| e.to_string())?;
    let watches_reader = Arc::clone(&watches);
    let stream_for_scan = Arc::clone(&stream);

    // Reader thread: host → DLL (watches).
    let reader = std::thread::spawn(move || {
        let mut buf = BufReader::new(reader_stream);
        let mut line = String::new();
        loop {
            line.clear();
            match buf.read_line(&mut line) {
                Ok(0) => break,
                Ok(_) => {
                    let text = line.trim();
                    if text.is_empty() {
                        continue;
                    }
                    if let Ok(msg) = serde_json::from_str::<HostMsg>(text) {
                        if msg.op == "watches" {
                            if let Ok(mut w) = watches_reader.lock() {
                                *w = msg.items;
                            }
                            let _ = send_log(
                                &stream_for_scan,
                                &format!("watches={}", watches_reader.lock().map(|w| w.len()).unwrap_or(0)),
                            );
                        } else if msg.op == "poke" {
                            handle_poke(&stream_for_scan, &msg);
                        }
                    }
                }
                Err(err) if err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut =>
                {
                    continue;
                }
                Err(_) => break,
            }
        }
    });

    // Scanner loop: DLL → host (opens).
    let mut last_len = 0usize;
    loop {
        let list = watches.lock().map_err(|e| e.to_string())?.clone();
        if list.len() != last_len {
            last_len = list.len();
            let _ = send_log(&stream, &format!("scanning {} identities", list.len()));
        }
        if !list.is_empty() {
            let opens = scan::poll_opens(&list);
            for open in opens {
                let line = json!({
                    "op": "open",
                    "region_id": open.region_id,
                    "layer_id": open.layer_id,
                    "object_id": open.object_id,
                    "value_key": open.value_key,
                });
                let mut s = stream.lock().map_err(|e| e.to_string())?;
                writeln!(s, "{line}").map_err(|e| e.to_string())?;
                s.flush().ok();
            }
        }
        if reader.is_finished() {
            break;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Ok(())
}

fn send_log(stream: &Arc<Mutex<TcpStream>>, msg: &str) -> Result<(), String> {
    let mut s = stream.lock().map_err(|e| e.to_string())?;
    writeln!(s, "{}", json!({"op":"log","msg": msg})).map_err(|e| e.to_string())?;
    s.flush().ok();
    Ok(())
}

fn decode_hex(s: &str) -> Result<Vec<u8>, ()> {
    if s.len() % 2 != 0 {
        return Err(());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|_| ()))
        .collect()
}

fn handle_poke(stream: &Arc<Mutex<TcpStream>>, msg: &HostMsg) {
    let label = msg.label.as_str();
    let result = match (msg.address, decode_hex(&msg.bytes)) {
        (Some(addr), Ok(data)) => {
            let ok = poke::write_bytes(addr as usize, &data);
            json!({"op":"poke_result","ok":ok,"address":addr,"label":label,"n":data.len()})
        }
        (None, _) => json!({"op":"poke_result","ok":false,"error":"missing address","label":label}),
        (_, Err(_)) => json!({"op":"poke_result","ok":false,"error":"bad hex bytes","label":label}),
    };
    let mut s = match stream.lock() {
        Ok(s) => s,
        Err(_) => return,
    };
    let _ = writeln!(s, "{result}");
    let _ = s.flush();
}
