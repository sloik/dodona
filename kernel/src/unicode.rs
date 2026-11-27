use crate::unicode_tables::{ASSIGNED, CCC, COMPOSE, DECOMP, FOLD};
fn ccc(c: u32) -> u8 {
    CCC.binary_search_by_key(&c, |x| x.0)
        .map_or(0, |i| CCC[i].1)
}
fn decompose(c: u32, out: &mut Vec<u32>) {
    if (0xAC00..0xD7A4).contains(&c) {
        let s = c - 0xAC00;
        out.push(0x1100 + s / 588);
        out.push(0x1161 + (s % 588) / 28);
        if !s.is_multiple_of(28) {
            out.push(0x11A7 + s % 28);
        }
    } else if let Ok(i) = DECOMP.binary_search_by_key(&c, |x| x.0) {
        for &d in DECOMP[i].1 {
            decompose(d, out);
        }
    } else {
        out.push(c);
    }
}
pub fn nfd(s: &str) -> String {
    let mut v = Vec::new();
    for c in s.chars() {
        decompose(c as u32, &mut v);
    }
    for i in 1..v.len() {
        let mut j = i;
        while j > 0 && ccc(v[j]) != 0 && ccc(v[j - 1]) > ccc(v[j]) {
            v.swap(j - 1, j);
            j -= 1;
        }
    }
    v.into_iter().map(|c| char::from_u32(c).unwrap()).collect()
}
fn composition(a: u32, b: u32) -> Option<u32> {
    if (0x1100..0x1113).contains(&a) && (0x1161..0x1176).contains(&b) {
        return Some(0xAC00 + (a - 0x1100) * 588 + (b - 0x1161) * 28);
    }
    if (0xAC00..0xD7A4).contains(&a) && (a - 0xAC00).is_multiple_of(28) && (0x11A8..0x11C3).contains(&b) {
        return Some(a + b - 0x11A7);
    }
    COMPOSE
        .binary_search_by_key(&(a, b), |x| (x.0, x.1))
        .ok()
        .map(|i| COMPOSE[i].2)
}
pub fn nfc(s: &str) -> String {
    let decomposed = nfd(s);
    let mut out: Vec<u32> = Vec::new();
    let mut starter = 0;
    let mut last = 0;
    for c in decomposed.chars().map(|c| c as u32) {
        let class = ccc(c);
        if !out.is_empty() && (last < class || last == 0) {
            if let Some(composed) = composition(out[starter], c) {
                out[starter] = composed;
                continue;
            }
        }
        if class == 0 {
            starter = out.len();
        }
        out.push(c);
        last = class;
    }
    out.into_iter()
        .map(|c| char::from_u32(c).unwrap())
        .collect()
}
pub fn fold(s: &str) -> String {
    let mut out = String::new();
    for c in nfd(s).chars() {
        if let Ok(i) = FOLD.binary_search_by_key(&(c as u32), |x| x.0) {
            for &v in FOLD[i].1 {
                out.push(char::from_u32(v).unwrap());
            }
        } else {
            out.push(c);
        }
    }
    nfd(&out)
}
pub fn assigned(c: char) -> bool {
    let n = c as u32;
    if (0xFDD0..=0xFDEF).contains(&n) || n & 0xFFFF >= 0xFFFE {
        return false;
    }
    let i = ASSIGNED.partition_point(|x| x.0 <= n);
    i > 0 && n <= ASSIGNED[i - 1].1
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore]
    fn normalization_conformance() {
        let path = std::path::Path::new(&std::env::var("DODONA_UCD_DIR").unwrap())
            .join("NormalizationTest.txt");
        let data = std::fs::read_to_string(path).unwrap();
        for line in data.lines() {
            let line = line.split('#').next().unwrap().trim();
            if line.is_empty() || line.starts_with('@') {
                continue;
            }
            let cols: Vec<String> = line
                .split(';')
                .take(5)
                .map(|s| {
                    s.split_whitespace()
                        .map(|x| char::from_u32(u32::from_str_radix(x, 16).unwrap()).unwrap())
                        .collect()
                })
                .collect();
            for i in 0..5 {
                assert_eq!(nfc(&cols[i]), cols[if i < 3 { 1 } else { 3 }], "{line}");
                assert_eq!(nfd(&cols[i]), cols[if i < 3 { 2 } else { 4 }], "{line}");
            }
        }
    }
}
