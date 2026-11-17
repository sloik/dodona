use crate::json::{self, Value};

pub fn answer(input: &[u8]) -> Value {
    match json::parse(input) {
        Ok(v) => {
            let text = json::encode(&v);
            json::object(vec![
                ("canonical", json::string(&text)),
                ("sha256", json::string(&sha256(text.as_bytes()))),
            ])
        }
        Err(reason) => json::object(vec![("refused", json::string(reason))]),
    }
}
/// The identity of a value: the hash of its canonical encoding.
pub fn identity(v: &Value) -> String {
    format!("sha256:{}", sha256(json::encode(v).as_bytes()))
}
/// Bytes from hexadecimal digits, two per byte. Signs and odd lengths are refused.
pub fn unhex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 || !s.bytes().all(|b| b.is_ascii_hexdigit()) {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok())
        .collect()
}
pub fn sha256(input: &[u8]) -> String {
    digest(input).iter().map(|b| format!("{b:02x}")).collect()
}
pub fn digest(input: &[u8]) -> [u8; 32] {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut data = input.to_vec();
    let bits = (data.len() as u64).wrapping_mul(8);
    data.push(0x80);
    while data.len() % 64 != 56 {
        data.push(0)
    }
    data.extend(bits.to_be_bytes());
    for chunk in data.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, part) in chunk.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes([part[0], part[1], part[2], part[3]])
        }
        for i in 16..64 {
            let a = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let b = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(a)
                .wrapping_add(w[i - 7])
                .wrapping_add(b);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut z] = h;
        for i in 0..64 {
            let s = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t = z
                .wrapping_add(s)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            z = g;
            g = f;
            f = e;
            e = d.wrapping_add(t);
            d = c;
            c = b;
            b = a;
            a = t.wrapping_add(s0).wrapping_add(maj);
        }
        for (x, y) in h.iter_mut().zip([a, b, c, d, e, f, g, z]) {
            *x = x.wrapping_add(y)
        }
    }
    let mut out = [0u8; 32];
    for (i, v) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&v.to_be_bytes());
    }
    out
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn hashes() {
        assert_eq!(
            sha256(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}

/// The core key of an evidence record from its preimage, or why it has none.
/// The named arrays are sets: sorted by their UTF-8 bytes, with no repeats.
pub fn core_key(v: &Value) -> Result<String, &'static str> {
    let inputs = v.opt("inputs");
    if v.opt("platform").is_some() || inputs.is_some_and(|i| i.opt("platform").is_some()) {
        return Err("platform-in-core-key");
    }
    for name in ["specified_by", "targets", "closure", "declared", "mapping"] {
        if let Some(Value::Array(a)) = inputs.and_then(|i| i.opt(name)) {
            let sorted = a.windows(2).all(|w| match (&w[0], &w[1]) {
                (Value::String(x), Value::String(y)) => x.as_bytes() < y.as_bytes(),
                _ => false,
            });
            if !sorted {
                return Err("unsorted-set");
            }
        }
    }
    Ok(identity(v))
}
pub fn key(v: &Value) -> Value {
    match core_key(v) {
        Ok(k) => json::object(vec![("core_key", json::string(&k))]),
        Err(reason) => json::object(vec![("refused", json::string(reason))]),
    }
}
#[cfg(test)]
mod key_tests {
    use super::*;
    #[test]
    fn rejects_non_sets_and_platform() {
        let v = json::parse(br#"{"inputs":{"targets":["b","a"]}}"#).unwrap();
        assert_eq!(key(&v).get("refused").str(), "unsorted-set");
        let v = json::parse(br#"{"inputs":{"targets":["a","a"]}}"#).unwrap();
        assert_eq!(core_key(&v), Err("unsorted-set"));
        let v = json::parse(br#"{"inputs":{"platform":{}}}"#).unwrap();
        assert_eq!(key(&v).get("refused").str(), "platform-in-core-key");
        let v = json::parse(br#"{"platform":"p"}"#).unwrap();
        assert_eq!(core_key(&v), Err("platform-in-core-key"));
    }
    #[test]
    fn keys_what_it_accepts() {
        let v = json::parse(br#"{"inputs":{"targets":["a","b"]}}"#).unwrap();
        assert_eq!(core_key(&v), Ok(identity(&v)));
        assert_eq!(
            identity(&json::parse(b"{}").unwrap()),
            "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        );
        // Sets are ordered by UTF-8 bytes, not UTF-16 units.
        let v = json::parse("{\"inputs\":{\"closure\":[\"\u{ff5e}\",\"\u{1f600}\"]}}".as_bytes())
            .unwrap();
        assert!(core_key(&v).is_ok());
    }
    #[test]
    fn hexadecimal() {
        assert_eq!(unhex("00ff1A"), Some(vec![0, 255, 26]));
        assert_eq!(unhex(""), Some(vec![]));
        assert_eq!(unhex("abc"), None);
        assert_eq!(unhex("+a"), None);
        assert_eq!(unhex("zz"), None);
        assert_eq!(unhex("\u{e9}"), None);
    }
}
