//! Runtime cryptographic algorithm-governance policy.
//!
//! *Algorithm isolation* shipped first: every PDF crypto operation routes
//! through [`crate::crypto::active`]. A compile-time gate was added, since
//! removed. This module is now the only mechanism, and the stronger one: it
//! adds the missing piece: a **runtime, configurable security policy** — the
//! ability to say "this process may *read* RC4 PDFs but must *never
//! write* anything weaker than AES-256", or "deny SHA-1 signing",
//! without recompiling and without writing a custom
//! [`CryptoProvider`](super::CryptoProvider).
//!
//! This file is the self-contained value-type core: [`SecurityPolicy`], [`PolicyMode`], [`Decision`],
//! [`AlgorithmId`], [`AlgorithmUse`], the mode-default matrix, the
//! decision precedence, the `FromStr`/`Display` grammar, and the audit
//! seam. The process-wide registry and the `PolicyEnforcedProvider`
//! decorator compose on top of these types in a later increment.
//!
//! Design (SOLID): the policy is **orthogonal to the provider** —
//! mirrors OpenSSL 3 `update-crypto-policies` and .NET
//! `CryptoConfig.AllowOnlyFipsAlgorithms`. The policy never widens
//! behaviour, only narrows it (Liskov-safe when used by the future
//! decorator).
//!
//! Fail-closed is the central invariant: an unknown algorithm, an
//! unparseable spec, or any ambiguity resolves to **deny**, never a
//! silent allow.

use std::collections::BTreeMap;
use std::str::FromStr;

use super::error::AlgorithmKind;

/// A cryptographic primitive `xberg-native-pdf` can be asked to perform.
///
/// `#[non_exhaustive]` so post-quantum ids (`MlKem*`, `MlDsa*`,
/// `SlhDsa*`) are an additive, non-breaking future change (CNSA 2.0
/// roadmap).
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum AlgorithmId {
    /// MD5 hash (legacy; PDF Standard Security R≤4 password KDF).
    HashMd5,
    /// SHA-1 hash (legacy; historical signatures, `adbe.pkcs7.sha1`).
    HashSha1,
    /// SHA-256 hash (FIPS approved).
    HashSha256,
    /// SHA-384 hash (FIPS approved).
    HashSha384,
    /// SHA-512 hash (FIPS approved).
    HashSha512,
    /// RC4 stream cipher (legacy; PDF R≤4).
    CipherRc4,
    /// AES-128-CBC (PDF V=4 R=4, `AESV2`).
    CipherAes128Cbc,
    /// AES-256-CBC (PDF V=5 R=5/6, `AESV3`).
    CipherAes256Cbc,
    /// RSA PKCS#1 v1.5 signature over SHA-1 (legacy).
    SigRsaPkcs1v15Sha1,
    /// RSA PKCS#1 v1.5 signature over SHA-256.
    SigRsaPkcs1v15Sha256,
    /// RSA PKCS#1 v1.5 signature over SHA-384.
    SigRsaPkcs1v15Sha384,
    /// RSA PKCS#1 v1.5 signature over SHA-512.
    SigRsaPkcs1v15Sha512,
    /// RSA-PSS signature over SHA-256.
    SigRsaPssSha256,
    /// RSA-PSS signature over SHA-384.
    SigRsaPssSha384,
    /// RSA-PSS signature over SHA-512.
    SigRsaPssSha512,
    /// ECDSA P-256 signature over SHA-256.
    SigEcdsaP256Sha256,
    /// ECDSA P-384 signature over SHA-384.
    SigEcdsaP384Sha384,
    // ── Post-quantum (FIPS 203/204, 2024) governance
    // vocabulary. The policy *recognises and governs* these ids;
    // actual ML-DSA/ML-KEM primitives are a separate provider concern
    // (a sign attempt fails closed at the provider until they land).
    // Appended last so existing `index()` / inventory-bit positions
    // stay frozen. ~keep
    /// ML-DSA-44 signature (FIPS 204; NIST security level 2).
    SigMlDsa44,
    /// ML-DSA-65 signature (FIPS 204; NIST security level 3).
    SigMlDsa65,
    /// ML-DSA-87 signature (FIPS 204; NIST security level 5).
    SigMlDsa87,
    /// ML-KEM-512 key encapsulation (FIPS 203; NIST level 1).
    KemMlKem512,
    /// ML-KEM-768 key encapsulation (FIPS 203; NIST level 3).
    KemMlKem768,
    /// ML-KEM-1024 key encapsulation (FIPS 203; NIST level 5).
    KemMlKem1024,
}

impl AlgorithmId {
    /// Every algorithm id this build knows, in declaration order.
    /// Used by the policy-matrix tests and `inventory()`.
    pub const ALL: [AlgorithmId; 23] = [
        AlgorithmId::HashMd5,
        AlgorithmId::HashSha1,
        AlgorithmId::HashSha256,
        AlgorithmId::HashSha384,
        AlgorithmId::HashSha512,
        AlgorithmId::CipherRc4,
        AlgorithmId::CipherAes128Cbc,
        AlgorithmId::CipherAes256Cbc,
        AlgorithmId::SigRsaPkcs1v15Sha1,
        AlgorithmId::SigRsaPkcs1v15Sha256,
        AlgorithmId::SigRsaPkcs1v15Sha384,
        AlgorithmId::SigRsaPkcs1v15Sha512,
        AlgorithmId::SigRsaPssSha256,
        AlgorithmId::SigRsaPssSha384,
        AlgorithmId::SigRsaPssSha512,
        AlgorithmId::SigEcdsaP256Sha256,
        AlgorithmId::SigEcdsaP384Sha384,
        // Appended; never reordered. ~keep
        AlgorithmId::SigMlDsa44,
        AlgorithmId::SigMlDsa65,
        AlgorithmId::SigMlDsa87,
        AlgorithmId::KemMlKem512,
        AlgorithmId::KemMlKem768,
        AlgorithmId::KemMlKem1024,
    ];

    /// Stable lowercase token used in the policy grammar, audit logs,
    /// and binding strings. Round-trips with [`Self::from_token`].
    pub const fn token(self) -> &'static str {
        match self {
            AlgorithmId::HashMd5 => "md5",
            AlgorithmId::HashSha1 => "sha1",
            AlgorithmId::HashSha256 => "sha256",
            AlgorithmId::HashSha384 => "sha384",
            AlgorithmId::HashSha512 => "sha512",
            AlgorithmId::CipherRc4 => "rc4",
            AlgorithmId::CipherAes128Cbc => "aes128",
            AlgorithmId::CipherAes256Cbc => "aes256",
            AlgorithmId::SigRsaPkcs1v15Sha1 => "rsa-pkcs1-sha1",
            AlgorithmId::SigRsaPkcs1v15Sha256 => "rsa-pkcs1-sha256",
            AlgorithmId::SigRsaPkcs1v15Sha384 => "rsa-pkcs1-sha384",
            AlgorithmId::SigRsaPkcs1v15Sha512 => "rsa-pkcs1-sha512",
            AlgorithmId::SigRsaPssSha256 => "rsa-pss-sha256",
            AlgorithmId::SigRsaPssSha384 => "rsa-pss-sha384",
            AlgorithmId::SigRsaPssSha512 => "rsa-pss-sha512",
            AlgorithmId::SigEcdsaP256Sha256 => "ecdsa-p256-sha256",
            AlgorithmId::SigEcdsaP384Sha384 => "ecdsa-p384-sha384",
            AlgorithmId::SigMlDsa44 => "ml-dsa-44",
            AlgorithmId::SigMlDsa65 => "ml-dsa-65",
            AlgorithmId::SigMlDsa87 => "ml-dsa-87",
            AlgorithmId::KemMlKem512 => "ml-kem-512",
            AlgorithmId::KemMlKem768 => "ml-kem-768",
            AlgorithmId::KemMlKem1024 => "ml-kem-1024",
        }
    }

    /// Parse a grammar/binding token back to an id. `None` for an
    /// unknown token (the caller treats that as a fail-closed parse
    /// error — never a silent allow).
    pub fn from_token(s: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|a| a.token() == s)
    }

    /// Stable position in [`Self::ALL`] — the bit index used by the
    /// process-wide crypto inventory bitset. Never reordered (it is a
    /// persisted-shape-adjacent contract); new ids append.
    pub fn index(self) -> usize {
        // Linear scan over the `ALL` `Copy` values — trivially cheap
        // and keeps a single source of truth (`ALL`), DRY. ~keep
        Self::ALL
            .iter()
            .position(|&a| a == self)
            .expect("every AlgorithmId is in ALL")
    }

    /// The broad algorithm family, reusing the existing
    /// [`AlgorithmKind`] so error/audit grouping stays DRY. Signature
    /// ids report `SignatureSign` as their family; the sign-vs-verify
    /// distinction is the orthogonal [`AlgorithmUse`] axis.
    pub const fn kind(self) -> AlgorithmKind {
        match self {
            AlgorithmId::HashMd5
            | AlgorithmId::HashSha1
            | AlgorithmId::HashSha256
            | AlgorithmId::HashSha384
            | AlgorithmId::HashSha512 => AlgorithmKind::Hash,
            AlgorithmId::CipherRc4 | AlgorithmId::CipherAes128Cbc | AlgorithmId::CipherAes256Cbc => {
                AlgorithmKind::SymmetricCipher
            }
            AlgorithmId::SigRsaPkcs1v15Sha1
            | AlgorithmId::SigRsaPkcs1v15Sha256
            | AlgorithmId::SigRsaPkcs1v15Sha384
            | AlgorithmId::SigRsaPkcs1v15Sha512
            | AlgorithmId::SigRsaPssSha256
            | AlgorithmId::SigRsaPssSha384
            | AlgorithmId::SigRsaPssSha512
            | AlgorithmId::SigEcdsaP256Sha256
            | AlgorithmId::SigEcdsaP384Sha384
            | AlgorithmId::SigMlDsa44
            | AlgorithmId::SigMlDsa65
            | AlgorithmId::SigMlDsa87 => AlgorithmKind::SignatureSign,
            // ML-KEM is key *encapsulation*; classified under the
            // existing `KeyDerivation` family (it establishes a shared
            // key) so no new `AlgorithmKind` variant / match ripple. ~keep
            AlgorithmId::KemMlKem512 | AlgorithmId::KemMlKem768 | AlgorithmId::KemMlKem1024 => {
                AlgorithmKind::KeyDerivation
            }
        }
    }

    /// Whether this primitive is FIPS 140-3 / SP 800-131A approved for
    /// **new** use. MD5, SHA-1, RC4 and RSA-PKCS#1-v1.5-over-SHA-1 are
    /// not. SHA-1 *verification* of historical signatures is permitted
    /// by SP 800-131A — that exception is modelled in the mode matrix
    /// via [`AlgorithmUse::Read`], not here.
    pub const fn is_fips_approved(self) -> bool {
        matches!(
            self,
            AlgorithmId::HashSha256
                | AlgorithmId::HashSha384
                | AlgorithmId::HashSha512
                | AlgorithmId::CipherAes128Cbc
                | AlgorithmId::CipherAes256Cbc
                | AlgorithmId::SigRsaPkcs1v15Sha256
                | AlgorithmId::SigRsaPkcs1v15Sha384
                | AlgorithmId::SigRsaPkcs1v15Sha512
                | AlgorithmId::SigRsaPssSha256
                | AlgorithmId::SigRsaPssSha384
                | AlgorithmId::SigRsaPssSha512
                | AlgorithmId::SigEcdsaP256Sha256
                | AlgorithmId::SigEcdsaP384Sha384
                | AlgorithmId::SigMlDsa44
                | AlgorithmId::SigMlDsa65
                | AlgorithmId::SigMlDsa87
                | AlgorithmId::KemMlKem512
                | AlgorithmId::KemMlKem768
                | AlgorithmId::KemMlKem1024
        )
    }

    /// Coarse security strength in bits (NIST SP 800-57 ballpark).
    /// Used only by the `min_security_bits` Write floor — deliberately
    /// coarse (per-algorithm floors are roadmap).
    pub const fn min_security_bits(self) -> u16 {
        match self {
            AlgorithmId::HashMd5 | AlgorithmId::HashSha1 | AlgorithmId::CipherRc4 => 0,
            AlgorithmId::SigRsaPkcs1v15Sha1 => 0,
            AlgorithmId::HashSha256
            | AlgorithmId::CipherAes128Cbc
            | AlgorithmId::SigRsaPkcs1v15Sha256
            | AlgorithmId::SigRsaPssSha256
            | AlgorithmId::SigEcdsaP256Sha256 => 128,
            AlgorithmId::HashSha384
            | AlgorithmId::SigRsaPkcs1v15Sha384
            | AlgorithmId::SigRsaPssSha384
            | AlgorithmId::SigEcdsaP384Sha384 => 192,
            AlgorithmId::HashSha512
            | AlgorithmId::CipherAes256Cbc
            | AlgorithmId::SigRsaPkcs1v15Sha512
            | AlgorithmId::SigRsaPssSha512 => 256,
            AlgorithmId::SigMlDsa44 | AlgorithmId::KemMlKem512 => 128,
            AlgorithmId::SigMlDsa65 | AlgorithmId::KemMlKem768 => 192,
            AlgorithmId::SigMlDsa87 | AlgorithmId::KemMlKem1024 => 256,
        }
    }

    /// True for the SHA-1 hash specifically — the one primitive
    /// `FipsStrict` still permits for *read* (historical-signature
    /// verification, NIST SP 800-131A).
    const fn is_sha1_hash(self) -> bool {
        matches!(self, AlgorithmId::HashSha1)
    }
}

/// Direction of a cryptographic operation. The spec forces an
/// asymmetry: a regulated operator must be able to *read* a legacy
/// RC4 PDF (incident response, archival) while being *forbidden* to
/// *produce* anything that weak.
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum AlgorithmUse {
    /// Decrypt / verify an existing signature / parse legacy material.
    Read,
    /// Encrypt-on-save / new key derivation / new signature creation.
    Write,
}

impl AlgorithmUse {
    /// Grammar token (`"read"` / `"write"`).
    pub const fn token(self) -> &'static str {
        match self {
            AlgorithmUse::Read => "read",
            AlgorithmUse::Write => "write",
        }
    }

    /// Parse a grammar token; `None` is a fail-closed parse error.
    pub fn from_token(s: &str) -> Option<Self> {
        match s {
            "read" => Some(AlgorithmUse::Read),
            "write" => Some(AlgorithmUse::Write),
            _ => None,
        }
    }
}

/// The outcome of a policy evaluation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    /// The operation is permitted.
    Allow,
    /// The operation is forbidden by policy (fail-closed default).
    Deny,
}

/// A first-class policy preset.
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PolicyMode {
    /// Today's behaviour. Allows everything the active provider
    /// allows. Read & write of R≤4 OK. Default.
    Compat,
    /// Read legacy OK; deny weak crypto for *writes* and new
    /// signatures. New encryption must be FIPS-grade.
    Strict,
    /// Deny every non-FIPS-approved algorithm for both directions.
    /// Pairs with `--features fips`. SHA-1 *verify* of historical
    /// signatures still allowed (SP 800-131A).
    FipsStrict,
    /// CNSA 2.0 posture: like `FipsStrict` for read,
    /// but new (`Write`) crypto must be quantum-resistant /
    /// high-strength — only FIPS-approved primitives at the **192-bit
    /// class or above** (ML-DSA-65/87, ML-KEM-768/1024, SHA-384/512,
    /// AES-256, RSA/ECDSA-384+). 128-bit-class classical is denied for
    /// write.
    Cnsa2,
    /// PQC migration posture: `Strict` semantics (read
    /// legacy OK; write must be FIPS-approved, 128-bit floor) that
    /// *additionally* recognises and permits the ML-DSA / ML-KEM ids,
    /// so deployments can dual-stack classical + post-quantum during
    /// the transition toward `Cnsa2` without yet enforcing the CNSA 2.0
    /// 192-bit-class mandate.
    PqcReady,
}

impl PolicyMode {
    /// Grammar token.
    pub const fn token(self) -> &'static str {
        match self {
            PolicyMode::Compat => "compat",
            PolicyMode::Strict => "strict",
            PolicyMode::FipsStrict => "fips-strict",
            PolicyMode::Cnsa2 => "cnsa2",
            PolicyMode::PqcReady => "pqc-ready",
        }
    }

    /// Default `min_security_bits` Write floor for this mode.
    const fn default_min_bits(self) -> u16 {
        match self {
            PolicyMode::Compat => 0,
            PolicyMode::Strict | PolicyMode::FipsStrict | PolicyMode::PqcReady => 128,
            PolicyMode::Cnsa2 => 192,
        }
    }

    /// Default minimum RSA *modulus* size (bits) this mode permits for
    /// signing. `0` = no floor (Compat). NIST SP
    /// 800-131A sets the floor at 2048; CNSA 2.0 mandates RSA-3072 as
    /// the transitional classical minimum.
    const fn default_min_rsa_bits(self) -> u16 {
        match self {
            PolicyMode::Compat => 0,
            PolicyMode::Strict | PolicyMode::PqcReady => 2048,
            PolicyMode::FipsStrict | PolicyMode::Cnsa2 => 3072,
        }
    }

    /// The mode's built-in decision for `(alg, use_)`, *before*
    /// explicit overrides and the `min_security_bits` floor. This is
    /// the §3.4 matrix encoded verbatim.
    fn default_decision(self, alg: AlgorithmId, use_: AlgorithmUse) -> Decision {
        match self {
            // Compat allows everything; the active provider's
            // `is_legacy_allowed()` is the remaining guard. ~keep
            PolicyMode::Compat => Decision::Allow,
            PolicyMode::Strict => match use_ {
                AlgorithmUse::Read => Decision::Allow,
                AlgorithmUse::Write => {
                    if alg.is_fips_approved() {
                        Decision::Allow
                    } else {
                        Decision::Deny
                    }
                }
            },
            PolicyMode::FipsStrict => {
                if alg.is_fips_approved() {
                    Decision::Allow
                } else {
                    match use_ {
                        // Historical-signature verification: SHA-1
                        // hash only (NIST SP 800-131A). ~keep
                        AlgorithmUse::Read if alg.is_sha1_hash() => Decision::Allow,
                        _ => Decision::Deny,
                    }
                }
            }
            // `PqcReady` == `Strict`'s matrix (read
            // legacy OK; write must be FIPS-approved — which now
            // includes ML-DSA/ML-KEM, enabling classical+PQC
            // dual-stacking during migration). Strength tightening to
            // CNSA-2.0 levels is `Cnsa2`'s job, not this transitional
            // mode's. ~keep
            PolicyMode::PqcReady => match use_ {
                AlgorithmUse::Read => Decision::Allow,
                AlgorithmUse::Write => {
                    if alg.is_fips_approved() {
                        Decision::Allow
                    } else {
                        Decision::Deny
                    }
                }
            },
            // CNSA 2.0: read legacy OK, but new crypto must be
            // FIPS-approved **and** 192-bit-class or stronger — denies
            // 128-bit classical (SHA-256/AES-128/RSA|ECDSA-256) and the
            // L1/L2 PQC params for write. ~keep
            PolicyMode::Cnsa2 => match use_ {
                AlgorithmUse::Read => Decision::Allow,
                AlgorithmUse::Write => {
                    if alg.is_fips_approved() && alg.min_security_bits() >= 192 {
                        Decision::Allow
                    } else {
                        Decision::Deny
                    }
                }
            },
        }
    }
}

/// Error parsing a [`SecurityPolicy`] from its string grammar.
/// Surfaced to the caller; the caller must treat a parse failure as
/// fatal (fail-closed — the policy is *not* installed).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyParseError(String);

impl PolicyParseError {
    /// The human-readable parse failure detail.
    pub fn detail(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for PolicyParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "invalid crypto policy spec: {}", self.0)
    }
}

impl std::error::Error for PolicyParseError {}

/// A runtime cryptographic governance policy.
///
/// Construct via [`Self::compat`], [`Self::strict`],
/// [`Self::fips_strict`], the [`SecurityPolicyBuilder`], or
/// [`str::parse`]. Evaluate a `(AlgorithmId, AlgorithmUse)` pair with
/// [`Self::evaluate`].
///
/// Decision precedence (documented and tested):
/// 1. An explicit `deny` override is **terminal** (fail-closed).
/// 2. An explicit `allow` override wins over the mode default —
///    *except* `FipsStrict` ignores `allow` overrides for
///    non-FIPS-approved primitives (the .NET `AllowOnlyFipsAlgorithms`
///    precedent).
/// 3. Otherwise the [`PolicyMode`] default matrix applies, then the
///    `min_security_bits` Write floor.
#[derive(Debug, Clone)]
pub struct SecurityPolicy {
    mode: PolicyMode,
    overrides: BTreeMap<(AlgorithmId, AlgorithmUse), Decision>,
    /// Decision for an algorithm id this build does not know. Always
    /// `Deny` (fail-closed); a field so the forward-shaped
    /// API can relax it deliberately later.
    unknown_algorithm: Decision,
    min_security_bits: u16,
    /// Minimum RSA modulus (bits) permitted for signing.
    /// `0` = no floor.
    min_rsa_modulus_bits: u16,
}

impl SecurityPolicy {
    /// The default, behaviour-preserving policy (`Compat`). Allows
    /// everything the provider + compile gates allow — byte-for-byte
    /// identical to pre-policy behaviour.
    pub fn compat() -> Self {
        Self::builder(PolicyMode::Compat).build()
    }

    /// `Strict`: read legacy OK, deny weak crypto on write / new
    /// signatures.
    pub fn strict() -> Self {
        Self::builder(PolicyMode::Strict).build()
    }

    /// `FipsStrict`: deny all non-FIPS-approved primitives both
    /// directions (SHA-1 historical-verify excepted).
    pub fn fips_strict() -> Self {
        Self::builder(PolicyMode::FipsStrict).build()
    }

    /// Start building a policy from `mode`.
    pub fn builder(mode: PolicyMode) -> SecurityPolicyBuilder {
        SecurityPolicyBuilder {
            mode,
            overrides: BTreeMap::new(),
            unknown_algorithm: Decision::Deny,
            min_security_bits: mode.default_min_bits(),
            min_rsa_modulus_bits: mode.default_min_rsa_bits(),
        }
    }

    /// The policy's base mode.
    pub fn mode(&self) -> PolicyMode {
        self.mode
    }

    /// The `min_security_bits` Write floor in effect.
    pub fn min_security_bits(&self) -> u16 {
        self.min_security_bits
    }

    /// The minimum RSA modulus size (bits) permitted for signing
    /// `0` = no floor.
    pub fn min_rsa_modulus_bits(&self) -> u16 {
        self.min_rsa_modulus_bits
    }

    /// Whether an RSA signing key with a `modulus_bits`-bit modulus is
    /// permitted. `Allow` when there is no floor
    /// (`min_rsa_modulus_bits == 0`) or the modulus meets it; else
    /// `Deny` (fail-closed — a weak key must not sign under a
    /// hardened policy).
    pub fn rsa_modulus_allowed(&self, modulus_bits: u32) -> Decision {
        if self.min_rsa_modulus_bits == 0 || modulus_bits >= u32::from(self.min_rsa_modulus_bits) {
            Decision::Allow
        } else {
            Decision::Deny
        }
    }

    /// Decide whether `alg` may be used for `use_`.
    ///
    /// Pure, allocation-free, and total (every input yields a
    /// `Decision`; fail-closed on any ambiguity).
    pub fn evaluate(&self, alg: AlgorithmId, use_: AlgorithmUse) -> Decision {
        if let Some(&d) = self.overrides.get(&(alg, use_)) {
            match d {
                Decision::Deny => return Decision::Deny,
                // FipsStrict refuses to let an allow-override
                // re-enable a non-approved primitive. ~keep
                Decision::Allow => {
                    if self.mode == PolicyMode::FipsStrict && !alg.is_fips_approved() {
                        // fall through to mode default (will Deny) ~keep
                    } else {
                        return Decision::Allow;
                    }
                }
            }
        }

        match self.mode.default_decision(alg, use_) {
            Decision::Deny => Decision::Deny,
            // 3. min_security_bits Write floor (defence in depth). ~keep
            Decision::Allow => {
                if use_ == AlgorithmUse::Write && alg.min_security_bits() < self.min_security_bits {
                    Decision::Deny
                } else {
                    Decision::Allow
                }
            }
        }
    }

    /// Convenience: `evaluate(..) == Decision::Allow`.
    pub fn allows(&self, alg: AlgorithmId, use_: AlgorithmUse) -> bool {
        self.evaluate(alg, use_) == Decision::Allow
    }

    /// The fail-closed decision for an algorithm id this build does
    /// not recognise (always `Deny`).
    pub fn unknown_algorithm_decision(&self) -> Decision {
        self.unknown_algorithm
    }

    /// Evaluate by string token (the shape the language bindings pass).
    /// An unrecognised algorithm token resolves to
    /// [`Self::unknown_algorithm_decision`] — **fail-closed**, never a
    /// silent allow.
    pub fn evaluate_token(&self, alg_token: &str, use_: AlgorithmUse) -> Decision {
        match AlgorithmId::from_token(alg_token) {
            Some(a) => self.evaluate(a, use_),
            None => self.unknown_algorithm,
        }
    }
}

impl Default for SecurityPolicy {
    fn default() -> Self {
        Self::compat()
    }
}

/// Builder for [`SecurityPolicy`]. `#[non_exhaustive]`-friendly: new
/// knobs are added as methods without breaking callers.
#[derive(Debug, Clone)]
pub struct SecurityPolicyBuilder {
    mode: PolicyMode,
    overrides: BTreeMap<(AlgorithmId, AlgorithmUse), Decision>,
    unknown_algorithm: Decision,
    min_security_bits: u16,
    min_rsa_modulus_bits: u16,
}

impl SecurityPolicyBuilder {
    /// Explicitly allow `(alg, use_)` (subject to the FipsStrict
    /// non-approved exception — see [`SecurityPolicy`] precedence).
    pub fn allow(mut self, alg: AlgorithmId, use_: AlgorithmUse) -> Self {
        self.overrides.insert((alg, use_), Decision::Allow);
        self
    }

    /// Explicitly deny `(alg, use_)` (terminal — deny always wins).
    pub fn deny(mut self, alg: AlgorithmId, use_: AlgorithmUse) -> Self {
        self.overrides.insert((alg, use_), Decision::Deny);
        self
    }

    /// Set the `min_security_bits` Write floor (e.g. `256` to force
    /// AES-256-only writes under `Strict`).
    pub fn min_security_bits(mut self, bits: u16) -> Self {
        self.min_security_bits = bits;
        self
    }

    /// Set the minimum RSA modulus size (bits) permitted for signing
    /// (e.g. `3072` for CNSA-2.0-class). `0` disables
    /// the floor.
    pub fn min_rsa_modulus_bits(mut self, bits: u16) -> Self {
        self.min_rsa_modulus_bits = bits;
        self
    }

    /// Decision for an algorithm id this build does not recognise.
    /// Defaults to `Deny` (fail-closed) and callers should not
    /// relax it; exposed so the forward-shaped API can do so
    /// deliberately later.
    pub fn unknown_algorithm(mut self, decision: Decision) -> Self {
        self.unknown_algorithm = decision;
        self
    }

    /// Finalize the policy.
    pub fn build(self) -> SecurityPolicy {
        SecurityPolicy {
            mode: self.mode,
            overrides: self.overrides,
            unknown_algorithm: self.unknown_algorithm,
            min_security_bits: self.min_security_bits,
            min_rsa_modulus_bits: self.min_rsa_modulus_bits,
        }
    }
}

/// Grammar: `mode[;clause]*` where `mode ∈ {compat,strict,fips-strict}`
/// and `clause = (allow|deny):<alg-token>@<read|write>`. Whitespace
/// around separators is tolerated. Any unknown token is a fail-closed
/// parse error.
impl FromStr for SecurityPolicy {
    type Err = PolicyParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let mut parts = s.split(';');
        let mode_tok = parts
            .next()
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .ok_or_else(|| PolicyParseError("empty policy spec".to_string()))?;
        let mode = match mode_tok {
            "compat" => PolicyMode::Compat,
            "strict" => PolicyMode::Strict,
            "fips-strict" => PolicyMode::FipsStrict,
            "cnsa2" => PolicyMode::Cnsa2,
            "pqc-ready" => PolicyMode::PqcReady,
            other => {
                return Err(PolicyParseError(format!(
                    "unknown mode '{other}' (expected compat|strict|fips-strict|cnsa2|pqc-ready)"
                )));
            }
        };
        let mut b = SecurityPolicy::builder(mode);
        for raw in parts {
            let clause = raw.trim();
            if clause.is_empty() {
                continue;
            }
            let (verb, rest) = clause
                .split_once(':')
                .ok_or_else(|| PolicyParseError(format!("clause '{clause}' must be '<allow|deny>:<alg>@<use>'")))?;
            let (alg_tok, use_tok) = rest
                .split_once('@')
                .ok_or_else(|| PolicyParseError(format!("clause '{clause}' missing '@<read|write>'")))?;
            let alg = AlgorithmId::from_token(alg_tok.trim())
                .ok_or_else(|| PolicyParseError(format!("unknown algorithm token '{alg_tok}'")))?;
            let use_ = AlgorithmUse::from_token(use_tok.trim())
                .ok_or_else(|| PolicyParseError(format!("unknown use token '{use_tok}' (expected read|write)")))?;
            b = match verb.trim() {
                "allow" => b.allow(alg, use_),
                "deny" => b.deny(alg, use_),
                other => {
                    return Err(PolicyParseError(format!(
                        "unknown verb '{other}' (expected allow|deny)"
                    )));
                }
            };
        }
        Ok(b.build())
    }
}

impl std::fmt::Display for SecurityPolicy {
    /// Renders back to the canonical grammar (round-trips with
    /// [`FromStr`]). Overrides are emitted in deterministic
    /// `BTreeMap` order.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.mode.token())?;
        for ((alg, use_), d) in &self.overrides {
            let verb = match d {
                Decision::Allow => "allow",
                Decision::Deny => "deny",
            };
            write!(f, ";{verb}:{}@{}", alg.token(), use_.token())?;
        }
        Ok(())
    }
}

/// One policy evaluation, for the audit seam (governance /
/// CBOM-adjacent observability).
#[derive(Debug, Clone, Copy)]
pub struct AuditEvent {
    /// The primitive evaluated.
    pub algorithm: AlgorithmId,
    /// The direction.
    pub use_: AlgorithmUse,
    /// The outcome.
    pub decision: Decision,
    /// The policy mode in effect.
    pub mode: PolicyMode,
}

/// Receives [`AuditEvent`]s. The default is a no-op; a `tracing`-backed
/// sink ships; consumers inject SIEM/OpenTelemetry sinks without
/// `xberg-native-pdf` depending on them (Dependency Inversion).
///
/// A sink panic must never turn a deny into an allow or abort the
/// process — the decorator (later increment) calls sinks defensively.
pub trait AuditSink: Send + Sync {
    /// Record one evaluation.
    fn record(&self, event: &AuditEvent);
}

/// The default sink: drops every event.
#[derive(Debug, Clone, Copy, Default)]
pub struct NoopAuditSink;

impl AuditSink for NoopAuditSink {
    fn record(&self, _event: &AuditEvent) {}
}

/// A sink that emits via `tracing` — `debug!` for allow, `warn!` for
/// deny. No new dependency (`tracing` is already pervasive).
#[derive(Debug, Clone, Copy, Default)]
pub struct LogAuditSink;

impl AuditSink for LogAuditSink {
    fn record(&self, e: &AuditEvent) {
        match e.decision {
            Decision::Allow => tracing::debug!(
                algorithm = e.algorithm.token(),
                r#use = e.use_.token(),
                mode = e.mode.token(),
                "crypto-policy allow"
            ),
            Decision::Deny => tracing::warn!(
                algorithm = e.algorithm.token(),
                r#use = e.use_.token(),
                mode = e.mode.token(),
                "crypto-policy deny"
            ),
        }
    }
}

#[cfg(test)]
mod tests;
