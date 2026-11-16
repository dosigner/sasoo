use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;

fn proof(token: &str, message: &str) -> String {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(token.as_bytes()).expect("HMAC accepts any key length");
    mac.update(message.as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
pub fn health_proof(token: &str) -> String {
    if token.is_empty() {
        String::new()
    } else {
        proof(token, "sasoo-health-v1")
    }
}
pub fn asset_proof(token: &str, decoded_path: &str) -> String {
    proof(token, &format!("sasoo-asset-v1:{decoded_path}"))
}
pub fn equal(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}
pub fn is_asset_path(path: &str) -> bool {
    path.starts_with("/static/library/")
        || path
            .strip_prefix("/api/papers/")
            .and_then(|p| p.strip_suffix("/pdf"))
            .is_some_and(|id| !id.is_empty() && id.bytes().all(|b| b.is_ascii_digit()))
}
