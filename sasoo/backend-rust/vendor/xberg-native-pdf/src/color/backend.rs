//! ICC colour-management backend abstraction.
//!
//! `QcmsBackend` is the only backend: Firefox's pure-Rust qcms 0.3 engine.
//! Covers source-profile → sRGB conversion for every ICC class real PDFs
//! ship (CMYK / RGB / Gray inputs). Cannot do CMYK → CMYK retargeting
//! (qcms 0.3 has no CMYK output path) and silently ignores the
//! rendering-intent parameter for CMYK sources.
//!
//! The [`IccBackend`] trait shape exists so the rest of `crate::color`
//! never imports `qcms` directly: every call site goes through
//! [`Transform`](super::Transform) which is built on top of
//! `ActiveIccBackend`. This keeps `color.rs` free of backend cfg gates
//! and confines the qcms specifics to this file.

use super::{IccProfile, RenderingIntent};

/// Transform-construction flags. Mirrors the lcms2 CMM's flag set; the
/// qcms backend reads only the bits it can honour and treats the rest
/// as no-ops.
#[derive(Debug, Clone, Copy, Default)]
pub struct TransformFlags {
    /// Black Point Compensation. The spec doesn't formally require BPC
    /// but the relative-colorimetric press default in real production
    /// pipelines does; without BPC, shadow tones clip to the
    /// destination's black point and the gray balance drifts. lcms2
    /// honours this bit; qcms 0.3 ignores it.
    pub black_point_compensation: bool,
}

impl TransformFlags {
    /// Convenience constructor for the press default — relative-
    /// colorimetric intent with BPC on.
    pub const fn press_default() -> Self {
        Self {
            black_point_compensation: true,
        }
    }
}

/// The trait every ICC backend implements. Two transform classes
/// matter to xberg-native-pdf:
///
///  - **Source → sRGB** for image / vector composite rendering. Every
///    backend supports it; the qcms 0.3 baseline only supports this.
///  - **CMYK → CMYK retargeting** for DeviceN /Process /ICCBased
///    paints whose embedded profile differs from the document
///    OutputIntent profile. Only lcms2 supports this — qcms 0.3 has
///    no CMYK output side. The retargeting flows through the Lab PCS
///    (CMYK → Lab via source AToB, Lab → CMYK via destination BToA),
///    which is the canonical press path.
///
/// Builders return `None` (rather than panic) when the backend
/// cannot construct a transform for the requested shape. Call sites
/// then fall through to the ISO 32000-1 §10.3.5 additive-clamp
/// formula or the round-5 "natural-form" reading, depending on the
/// context.
pub trait IccBackend {
    /// Backend-specific opaque source-to-sRGB transform handle.
    type SrgbTransform;
    /// Backend-specific opaque CMYK-to-CMYK retargeting transform
    /// handle.
    type CmykRetarget;
    /// Backend-specific opaque sRGB-to-destination-CMYK transform
    /// handle. Used by the transparency sidecar to mirror RGB-source
    /// paints into the CMYK plane so subsequent transparent CMYK
    /// paints composite against the converted backdrop rather than
    /// paper-white per §11.3.4 + §11.4.5.1 (§11.4.5.1 defines the
    /// group's /CS as the single blend colour space; §11.3.4 is the
    /// per-pixel computation that runs inside it).
    type SrgbToCmykTransform;

    /// Build a source-profile → sRGB transform honouring `intent`.
    /// Returns `None` when the backend can't compile the profile
    /// (malformed bytes, unsupported device class, missing tags).
    fn build_srgb_transform(
        profile: &IccProfile,
        intent: RenderingIntent,
        flags: TransformFlags,
    ) -> Option<Self::SrgbTransform>;

    /// Apply a source-to-sRGB transform to one CMYK pixel. Backends
    /// that don't support CMYK source (none currently) should return
    /// `None`. The output is byte-quantised sRGB.
    fn convert_cmyk_pixel(transform: &Self::SrgbTransform, cmyk: [u8; 4]) -> Option<[u8; 3]>;

    /// Apply a source-to-sRGB transform to a packed CMYK buffer.
    /// Output buffer length is `(input.len() / 4) * 3`.
    fn convert_cmyk_buffer(transform: &Self::SrgbTransform, cmyk: &[u8]) -> Option<Vec<u8>>;

    /// Apply a source-to-sRGB transform to a packed RGB buffer.
    /// Output buffer is the same length.
    fn convert_rgb_buffer(transform: &Self::SrgbTransform, rgb: &[u8]) -> Option<Vec<u8>>;

    /// Apply a source-to-sRGB transform to a packed grayscale buffer.
    /// Output buffer is `input.len() * 3` bytes.
    fn convert_gray_buffer(transform: &Self::SrgbTransform, gray: &[u8]) -> Option<Vec<u8>>;

    /// Build a CMYK→CMYK retargeting transform from `src_profile`
    /// (the embedded /ICCBased CMYK profile) to `dst_profile` (the
    /// document `/OutputIntents` CMYK profile) honouring `intent` and
    /// `flags`. Returns `None` when the backend can't do CMYK→CMYK
    /// (the qcms 0.3 baseline) or when profile compilation fails.
    fn build_cmyk_retarget(
        src_profile: &IccProfile,
        dst_profile: &IccProfile,
        intent: RenderingIntent,
        flags: TransformFlags,
    ) -> Option<Self::CmykRetarget>;

    /// Apply a CMYK retargeting transform to a single normalised
    /// CMYK pixel. Inputs and outputs are unit-interval f32 in the
    /// channel order C, M, Y, K. Round-tripping through 8-bit is the
    /// caller's responsibility — the trait operates in f32 so
    /// quantisation only happens at the storage boundary.
    fn retarget_cmyk_pixel(transform: &Self::CmykRetarget, cmyk: [f32; 4]) -> [f32; 4];

    /// Build an sRGB → destination-CMYK transform honouring `intent`
    /// and `flags`. The destination is a printer-class CMYK profile
    /// (typically the document `/OutputIntents` profile). Returns
    /// `None` when the backend can't build the transform — qcms 0.3
    /// has no CMYK output path so it always returns None. lcms2 builds
    /// the transform through sRGB → Lab PCS → destination CMYK.
    fn build_srgb_to_cmyk(
        dst_profile: &IccProfile,
        intent: RenderingIntent,
        flags: TransformFlags,
    ) -> Option<Self::SrgbToCmykTransform>;

    /// Apply an sRGB→destination-CMYK transform to a single sRGB
    /// pixel. Inputs are unit-interval f32 (R, G, B); outputs are
    /// unit-interval f32 (C, M, Y, K). Round-trips through 8-bit at
    /// the lcms2 boundary for the same reason as `retarget_cmyk_pixel`
    /// — the press pipeline serialises plate values as 8-bit.
    fn convert_srgb_to_cmyk_pixel(transform: &Self::SrgbToCmykTransform, rgb: [f32; 3]) -> [f32; 4];
}

// ============================================================================
// QcmsBackend — pure-Rust default. Mirrors the surface qcms 0.3 exposes.
// ============================================================================ ~keep

/// qcms-backed [`IccBackend`]. Only the source-to-sRGB methods do real
/// work; CMYK retargeting is unconditionally unsupported in qcms 0.3
/// (no CMYK output path), and that's documented as
/// `HONEST_GAP_DEVICEN_PROCESS_ICC_PROFILE_MISMATCH`.
pub struct QcmsBackend;

mod qcms_impl {
    use super::*;

    /// Holder so the public trait can stay backend-agnostic. The
    /// inner `qcms::Transform` is the compiled CLUT.
    pub struct SrgbTransform {
        pub(super) inner: qcms::Transform,
        pub(super) source_components: u8,
    }

    /// qcms has no CMYK→CMYK path, so the retarget transform is a
    /// permanent never-constructed marker. We use `core::convert::Infallible`
    /// as the type so it can't be instantiated at runtime — every
    /// `build_cmyk_retarget` call on `QcmsBackend` returns `None`.
    pub struct CmykRetarget(pub(super) core::convert::Infallible);

    /// qcms has no CMYK output path so RGB → CMYK is also unsupported.
    /// `core::convert::Infallible` makes the type uninhabited so the
    /// `convert_srgb_to_cmyk_pixel` arm is unreachable at runtime.
    pub struct SrgbToCmykTransform(pub(super) core::convert::Infallible);

    fn qcms_intent(intent: RenderingIntent) -> qcms::Intent {
        match intent {
            RenderingIntent::Perceptual => qcms::Intent::Perceptual,
            RenderingIntent::RelativeColorimetric => qcms::Intent::RelativeColorimetric,
            RenderingIntent::Saturation => qcms::Intent::Saturation,
            RenderingIntent::AbsoluteColorimetric => qcms::Intent::AbsoluteColorimetric,
        }
    }

    impl IccBackend for QcmsBackend {
        type SrgbTransform = SrgbTransform;
        type CmykRetarget = CmykRetarget;
        type SrgbToCmykTransform = SrgbToCmykTransform;

        fn build_srgb_transform(
            profile: &IccProfile,
            intent: RenderingIntent,
            _flags: TransformFlags,
        ) -> Option<Self::SrgbTransform> {
            let src = qcms::Profile::new_from_slice(profile.bytes(), false)?;
            let dst = qcms::Profile::new_sRGB();
            let src_ty = match profile.n_components() {
                1 => qcms::DataType::Gray8,
                3 => qcms::DataType::RGB8,
                4 => qcms::DataType::CMYK,
                _ => return None,
            };
            qcms::Transform::new_to(&src, &dst, src_ty, qcms::DataType::RGB8, qcms_intent(intent)).map(|inner| {
                SrgbTransform {
                    inner,
                    source_components: profile.n_components(),
                }
            })
        }

        fn convert_cmyk_pixel(transform: &Self::SrgbTransform, cmyk: [u8; 4]) -> Option<[u8; 3]> {
            if transform.source_components != 4 {
                return None;
            }
            let mut dst = [0u8; 3];
            transform.inner.convert(&cmyk, &mut dst);
            Some(dst)
        }

        fn convert_cmyk_buffer(transform: &Self::SrgbTransform, cmyk: &[u8]) -> Option<Vec<u8>> {
            if transform.source_components != 4 {
                return None;
            }
            let pixels = cmyk.len() / 4;
            let mut out = vec![0u8; pixels * 3];
            transform.inner.convert(cmyk, &mut out);
            Some(out)
        }

        fn convert_rgb_buffer(transform: &Self::SrgbTransform, rgb: &[u8]) -> Option<Vec<u8>> {
            if transform.source_components != 3 {
                return None;
            }
            let mut out = vec![0u8; rgb.len()];
            transform.inner.convert(rgb, &mut out);
            Some(out)
        }

        fn convert_gray_buffer(transform: &Self::SrgbTransform, gray: &[u8]) -> Option<Vec<u8>> {
            if transform.source_components != 1 {
                return None;
            }
            let mut out = vec![0u8; gray.len() * 3];
            transform.inner.convert(gray, &mut out);
            Some(out)
        }

        fn build_cmyk_retarget(
            _src_profile: &IccProfile,
            _dst_profile: &IccProfile,
            _intent: RenderingIntent,
            _flags: TransformFlags,
        ) -> Option<Self::CmykRetarget> {
            // qcms 0.3 has no CMYK output path. This is the canonical
            // "no" answer that HONEST_GAP_DEVICEN_PROCESS_ICC_PROFILE
            // _MISMATCH documents under the icc-qcms-only build. Call
            // sites fall through to the round-5 "natural form" reading
            // or the §10.3.5 additive-clamp formula. ~keep
            None
        }

        fn retarget_cmyk_pixel(transform: &Self::CmykRetarget, _cmyk: [f32; 4]) -> [f32; 4] {
            // Uninhabited: `build_cmyk_retarget` always returns None
            // on QcmsBackend, so this branch is unreachable. We match
            // on the Infallible inhabitant to teach the compiler that. ~keep
            match transform.0 {}
        }

        fn build_srgb_to_cmyk(
            _dst_profile: &IccProfile,
            _intent: RenderingIntent,
            _flags: TransformFlags,
        ) -> Option<Self::SrgbToCmykTransform> {
            // qcms 0.3 has no CMYK output path. Call sites fall through
            // to the §10.3.5 inverse `(C, M, Y) = (1-R, 1-G, 1-B)`,
            // `K = 0` formula at the caller. ~keep
            None
        }

        fn convert_srgb_to_cmyk_pixel(transform: &Self::SrgbToCmykTransform, _rgb: [f32; 3]) -> [f32; 4] {
            // Uninhabited under qcms — `build_srgb_to_cmyk` always
            // returns None. ~keep
            match transform.0 {}
        }
    }
}

pub use qcms_impl::{
    CmykRetarget as QcmsCmykRetarget, SrgbToCmykTransform as QcmsSrgbToCmykTransform,
    SrgbTransform as QcmsSrgbTransform,
};

/// Active ICC backend — qcms is the only backend this crate ships.
pub type ActiveIccBackend = QcmsBackend;

/// Backend-name diagnostic for `Debug` output and the
/// `BACKEND_NAME` reporting hook the round-7 probes consume.
pub const fn active_backend_name() -> &'static str {
    "qcms"
}
