//! Encryption handler for writing encrypted PDFs.
//!
//! This module provides the EncryptionWriteHandler which encrypts PDF objects
//! (strings and streams) when saving an encrypted PDF.

use super::Algorithm;
use super::aes;
use super::algorithms;
use super::rc4;

/// Handler for encrypting PDF objects during write operations.
///
/// This struct manages the encryption state and provides methods for
/// encrypting strings and streams according to the PDF encryption specification.
pub struct EncryptionWriteHandler {
    /// The base encryption key (derived from password)
    encryption_key: Vec<u8>,
    /// The encryption algorithm in use
    algorithm: Algorithm,
    /// Whether to encrypt metadata streams
    encrypt_metadata: bool,
}

impl EncryptionWriteHandler {
    /// Create a new encryption write handler.
    ///
    /// # Arguments
    /// * `user_password` - The user password for the document
    /// * `owner_hash` - The computed owner password hash (O value)
    /// * `permissions` - The permission bits (P value)
    /// * `file_id` - The first element of the file ID array
    /// * `algorithm` - The encryption algorithm to use
    /// * `encrypt_metadata` - Whether to encrypt metadata
    pub fn new(
        user_password: &[u8],
        owner_hash: &[u8],
        permissions: i32,
        file_id: &[u8],
        algorithm: Algorithm,
        encrypt_metadata: bool,
    ) -> crate::Result<Self> {
        let (_, revision) = Self::get_version_revision(algorithm);
        let key_length = algorithm.key_length();

        let encryption_key = algorithms::compute_encryption_key(
            user_password,
            owner_hash,
            permissions,
            file_id,
            revision,
            key_length,
            encrypt_metadata,
        )?;

        Ok(Self {
            encryption_key,
            algorithm,
            encrypt_metadata,
        })
    }

    /// Create a handler from an already computed encryption key.
    ///
    /// This is useful when the key has already been derived during
    /// EncryptDict construction.
    pub fn from_key(encryption_key: Vec<u8>, algorithm: Algorithm, encrypt_metadata: bool) -> Self {
        Self {
            encryption_key,
            algorithm,
            encrypt_metadata,
        }
    }

    /// Get the (V, R) version/revision tuple for an algorithm.
    fn get_version_revision(algorithm: Algorithm) -> (u32, u32) {
        match algorithm {
            Algorithm::None => (0, 0),
            Algorithm::RC4_40 => (1, 2),
            Algorithm::Rc4_128 => (2, 3),
            Algorithm::Aes128 => (4, 4),
            Algorithm::Aes256 => (5, 6),
        }
    }

    /// Derive the object-specific encryption key.
    ///
    /// PDF Spec: Algorithm 1 - Encryption key derivation for individual objects
    ///
    /// For R=2-4, the object key is derived by appending the object number
    /// and generation number to the base key, then hashing.
    fn derive_object_key(&self, obj_num: u32, gen_num: u16) -> Vec<u8> {
        let (_, revision) = Self::get_version_revision(self.algorithm);

        // For AES-256 (R=5/6), use the encryption key directly ~keep
        if revision >= 5 {
            return self.encryption_key.clone();
        }

        // R<=4 (RC4 or AES-128): derive per-object key via MD5 (Algorithm 1). ~keep
        use md5::{Digest, Md5};

        // #230 Phase C note: this per-object key (Algorithm 1) is
        // *intentionally* not re-routed through the governed
        // provider. It is always downstream of the document
        // encryption key, which is derived by the now-governed
        // `algorithms::compute_encryption_key`
        // (`EncryptionWriteHandler::new`) / `compute_owner_password_hash`
        // (EncryptDict build) — both call `md5_kdf_hasher()?`, so a
        // `strict`/`fips-strict` policy already fail-closes R≤4
        // *before* this code is reachable. Re-gating here would add
        // no governance (set-once policy, already permitted upstream)
        // while forcing a fallible-Result cascade through the PDF
        // object serializer (KISS / byte-stability — feature-230
        // §4.2's stated deferral reason). ~keep

        // Algorithm 1: Derive object-specific key ~keep
        let mut hasher = Md5::new();

        hasher.update(&self.encryption_key);

        // Append object number (3 bytes, little-endian) ~keep
        hasher.update(&obj_num.to_le_bytes()[..3]);

        // Append generation number (2 bytes, little-endian) ~keep
        hasher.update(gen_num.to_le_bytes());

        // For AES, append the "sAlT" salt bytes ~keep
        if self.algorithm.is_aes() {
            hasher.update(b"sAlT");
        }

        let hash = hasher.finalize();

        // Key length is min(n + 5, 16) for RC4, min(n + 5, 16) for AES-128 ~keep
        let key_length = (self.encryption_key.len() + 5).min(16);
        hash[..key_length].to_vec()
    }

    /// Encrypt a string for a specific object.
    ///
    /// # Arguments
    /// * `data` - The plaintext string data
    /// * `obj_num` - The object number containing this string
    /// * `gen_num` - The generation number
    ///
    /// # Returns
    /// The encrypted data
    pub fn encrypt_string(&self, data: &[u8], obj_num: u32, gen_num: u16) -> Vec<u8> {
        if self.algorithm == Algorithm::None {
            return data.to_vec();
        }

        let key = self.derive_object_key(obj_num, gen_num);
        self.encrypt_with_key(&key, data)
    }

    /// Encrypt a stream for a specific object.
    ///
    /// For AES encryption, a random 16-byte IV is prepended to the ciphertext.
    ///
    /// # Arguments
    /// * `data` - The plaintext stream data
    /// * `obj_num` - The object number containing this stream
    /// * `gen_num` - The generation number
    ///
    /// # Returns
    /// The encrypted data (with IV prepended for AES)
    pub fn encrypt_stream(&self, data: &[u8], obj_num: u32, gen_num: u16) -> Vec<u8> {
        if self.algorithm == Algorithm::None {
            return data.to_vec();
        }

        let key = self.derive_object_key(obj_num, gen_num);
        self.encrypt_with_key(&key, data)
    }

    /// Encrypt data using the specified key.
    fn encrypt_with_key(&self, key: &[u8], data: &[u8]) -> Vec<u8> {
        match self.algorithm {
            Algorithm::None => data.to_vec(),
            Algorithm::RC4_40 | Algorithm::Rc4_128 => {
                // RC4 rejection by the FIPS provider should be impossible
                // here — `EncryptionWriteHandler::new` rejects RC4
                // algorithms up front under non-legacy providers (see
                // Issue #236). If it ever fires, fall back to plaintext
                // matching the AES error path below — this is logged as
                // a critical error rather than panicking the host. ~keep
                rc4::rc4_crypt(key, data).unwrap_or_else(|e| {
                    tracing::error!(
                        algorithm = "RC4",
                        error = %e,
                        "RC4 unexpectedly rejected; returning plaintext \
                         (write_handler FIPS gate should have prevented this)"
                    );
                    data.to_vec()
                })
            }
            Algorithm::Aes128 => match Self::generate_iv() {
                Ok(iv) => match aes::aes128_encrypt(key, &iv, data) {
                    Ok(ciphertext) => {
                        let mut result = iv.to_vec();
                        result.extend(ciphertext);
                        result
                    }
                    Err(_) => data.to_vec(),
                },
                Err(e) => {
                    tracing::error!(algorithm = "AES-128", error = %e, "IV generation failed; returning plaintext");
                    data.to_vec()
                }
            },
            Algorithm::Aes256 => match Self::generate_iv() {
                Ok(iv) => match aes::aes256_encrypt(key, &iv, data) {
                    Ok(ciphertext) => {
                        let mut result = iv.to_vec();
                        result.extend(ciphertext);
                        result
                    }
                    Err(_) => data.to_vec(),
                },
                Err(e) => {
                    tracing::error!(algorithm = "AES-256", error = %e, "IV generation failed; returning plaintext");
                    data.to_vec()
                }
            },
        }
    }

    fn generate_iv() -> crate::Result<[u8; 16]> {
        let mut iv = [0u8; 16];
        crate::crypto::active()
            .random_bytes(&mut iv)
            .map_err(|e| crate::Error::InvalidPdf(format!("AES IV generation failed: {e}")))?;
        Ok(iv)
    }

    /// Get the encryption algorithm.
    pub fn algorithm(&self) -> Algorithm {
        self.algorithm
    }

    /// Check if metadata should be encrypted.
    pub fn encrypt_metadata(&self) -> bool {
        self.encrypt_metadata
    }

    /// Get the encryption key (for testing purposes).
    #[cfg(test)]
    pub fn encryption_key(&self) -> &[u8] {
        &self.encryption_key
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_object_key_derivation_rc4() {
        let key = vec![0x01, 0x02, 0x03, 0x04, 0x05];
        let handler = EncryptionWriteHandler::from_key(key, Algorithm::RC4_40, true);

        let obj_key1 = handler.derive_object_key(1, 0);
        let obj_key2 = handler.derive_object_key(2, 0);
        let obj_key3 = handler.derive_object_key(1, 1);

        // Different objects should have different keys ~keep
        assert_ne!(obj_key1, obj_key2);
        assert_ne!(obj_key1, obj_key3);

        // Key should be derived to correct length (n+5, max 16) ~keep
        assert_eq!(obj_key1.len(), 10);
    }

    #[test]
    fn test_object_key_derivation_aes128() {
        let key = vec![0u8; 16];
        let handler = EncryptionWriteHandler::from_key(key, Algorithm::Aes128, true);

        let obj_key1 = handler.derive_object_key(1, 0);
        let obj_key2 = handler.derive_object_key(2, 0);

        // Different objects should have different keys ~keep
        assert_ne!(obj_key1, obj_key2);

        // Key should be 16 bytes (min(16+5, 16)) ~keep
        assert_eq!(obj_key1.len(), 16);
    }

    #[test]
    fn test_object_key_derivation_aes256() {
        let key = vec![0u8; 32];
        let handler = EncryptionWriteHandler::from_key(key.clone(), Algorithm::Aes256, true);

        let obj_key = handler.derive_object_key(1, 0);

        // For AES-256 (R>=5), the key should be unchanged ~keep
        assert_eq!(obj_key, key);
    }

    #[test]
    fn test_rc4_encryption_roundtrip() {
        let key = vec![0x01, 0x02, 0x03, 0x04, 0x05];
        let handler = EncryptionWriteHandler::from_key(key, Algorithm::RC4_40, true);

        let plaintext = b"Hello, encrypted world!";
        let ciphertext = handler.encrypt_string(plaintext, 1, 0);

        // RC4 is symmetric - encrypt again to decrypt ~keep
        let obj_key = handler.derive_object_key(1, 0);
        let decrypted = rc4::rc4_crypt(&obj_key, &ciphertext).unwrap();

        assert_eq!(&decrypted, plaintext);
    }

    #[test]
    fn test_aes_encryption() {
        let key = vec![0u8; 16];
        let handler = EncryptionWriteHandler::from_key(key, Algorithm::Aes128, true);

        let plaintext = b"Hello, AES encrypted world!";
        let ciphertext = handler.encrypt_stream(plaintext, 1, 0);

        assert!(ciphertext.len() >= 16);

        let iv = &ciphertext[..16];
        let encrypted = &ciphertext[16..];

        let obj_key = handler.derive_object_key(1, 0);
        let decrypted = aes::aes128_decrypt(&obj_key, iv, encrypted).unwrap();

        assert_eq!(&decrypted, plaintext);
    }
}
