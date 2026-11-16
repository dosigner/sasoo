use sasoo_backend::pdf::{
    AffineTransform, CoordinateSpace, EngineBox, PageBox, PageGeometry, PdfUserBox,
    to_pdf_user_space, to_physical_points,
};

fn geometry(rotation_deg: u16, user_unit: f64) -> PageGeometry {
    PageGeometry {
        media_box: [0.0, 0.0, 640.0, 840.0],
        crop_box: [20.0, 40.0, 620.0, 800.0],
        rotation_deg,
        user_unit,
        engine_to_pdf_user_space: None,
    }
}

fn assert_box(actual: Option<PdfUserBox>, expected: [f64; 4]) {
    let actual = actual.expect("verified geometry").coords;
    for (actual, expected) in actual.into_iter().zip(expected) {
        assert!((actual - expected).abs() < 1e-10, "{actual} != {expected}");
    }
}

#[test]
fn analytical_crop_and_rotation_vectors_match_pdfjs_user_space() {
    // Independent inverse vectors for the PDF.js clockwise viewport convention.
    let expected = [70.0, 100.0, 170.0, 200.0];
    for (rotation, displayed) in [
        (0, [50.0, 600.0, 150.0, 700.0]),
        (90, [60.0, 50.0, 160.0, 150.0]),
        (180, [450.0, 60.0, 550.0, 160.0]),
        (270, [600.0, 450.0, 700.0, 550.0]),
    ] {
        let page = geometry(rotation, 2.0);
        assert_box(
            to_pdf_user_space(
                EngineBox {
                    coords: displayed,
                    space: CoordinateSpace::DisplayTopLeft {
                        reference: PageBox::Crop,
                    },
                },
                &page,
            )
            .unwrap(),
            expected,
        );
        // Raw PDF coordinates must not apply page rotation or UserUnit again.
        assert_box(
            to_pdf_user_space(
                EngineBox {
                    coords: expected,
                    space: CoordinateSpace::PdfUserSpace,
                },
                &page,
            )
            .unwrap(),
            expected,
        );
        assert_eq!(
            to_physical_points(PdfUserBox { coords: expected }, &page).unwrap(),
            [140.0, 200.0, 340.0, 400.0]
        );
    }
}

#[test]
fn pixel_normalized_and_top_left_frames_are_explicit() {
    let page = geometry(90, 2.0);
    assert_box(
        to_pdf_user_space(
            EngineBox {
                coords: [120.0, 100.0, 320.0, 300.0],
                space: CoordinateSpace::DisplayPixels {
                    reference: PageBox::Crop,
                    width: 1520.0,
                    height: 1200.0,
                },
            },
            &page,
        )
        .unwrap(),
        [70.0, 100.0, 170.0, 200.0],
    );
    assert_box(
        to_pdf_user_space(
            EngineBox {
                coords: [60.0 / 760.0, 50.0 / 600.0, 160.0 / 760.0, 150.0 / 600.0],
                space: CoordinateSpace::DisplayNormalized {
                    reference: PageBox::Crop,
                },
            },
            &page,
        )
        .unwrap(),
        [70.0, 100.0, 170.0, 200.0],
    );
    assert_box(
        to_pdf_user_space(
            EngineBox {
                coords: [50.0, 600.0, 150.0, 700.0],
                space: CoordinateSpace::UnrotatedTopLeft {
                    reference: PageBox::Crop,
                },
            },
            &page,
        )
        .unwrap(),
        [70.0, 100.0, 170.0, 200.0],
    );
    assert_box(
        to_pdf_user_space(
            EngineBox {
                coords: [140.0, 200.0, 340.0, 400.0],
                space: CoordinateSpace::PhysicalPoints,
            },
            &page,
        )
        .unwrap(),
        [70.0, 100.0, 170.0, 200.0],
    );
}

#[test]
fn affine_mapping_checks_all_corners_and_unknown_remains_unknown() {
    let mut page = geometry(0, 1.0);
    let input = EngineBox {
        coords: [0.0, 0.0, 2.0, 1.0],
        space: CoordinateSpace::EngineNative {
            name: "engine-native".into(),
        },
    };
    assert_eq!(to_pdf_user_space(input.clone(), &page).unwrap(), None);
    page.engine_to_pdf_user_space = Some(AffineTransform {
        a: 1.0,
        b: 1.0,
        c: -1.0,
        d: 1.0,
        e: 10.0,
        f: 20.0,
    });
    assert_box(
        to_pdf_user_space(input, &page).unwrap(),
        [9.0, 20.0, 12.0, 23.0],
    );
}

#[test]
fn nonfinite_singular_or_invalid_units_never_produce_a_verified_bbox() {
    let mut page = geometry(0, 1.0);
    let input = EngineBox {
        coords: [0.0, 0.0, 10.0, 10.0],
        space: CoordinateSpace::PdfUserSpace,
    };
    for user_unit in [0.0, -1.0, f64::NAN, f64::INFINITY] {
        page.user_unit = user_unit;
        assert!(to_pdf_user_space(input.clone(), &page).is_err());
    }
    page = geometry(45, 1.0);
    assert!(to_pdf_user_space(input.clone(), &page).is_err());
    page = geometry(0, 1.0);
    let mut invalid = input.clone();
    invalid.coords[0] = f64::NAN;
    assert!(to_pdf_user_space(invalid, &page).is_err());
    let mut zero = input;
    zero.coords[2] = 0.0;
    assert_eq!(to_pdf_user_space(zero, &page).unwrap(), None);
    page.engine_to_pdf_user_space = Some(AffineTransform {
        a: 0.0,
        b: 0.0,
        c: 0.0,
        d: 0.0,
        e: 0.0,
        f: 0.0,
    });
    assert!(
        to_pdf_user_space(
            EngineBox {
                coords: [0.0, 0.0, 1.0, 1.0],
                space: CoordinateSpace::EngineNative {
                    name: "singular".into()
                },
            },
            &page
        )
        .is_err()
    );
}

#[test]
fn frozen_geometry_fixture_is_analytical_and_source_tagged() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../contract-fixtures/rust-backend-v2/pdf/geometry.json"
    ))
    .unwrap();
    assert_eq!(fixture["evidence_kind"], "analytical_vectors");
    for case in fixture["cases"].as_array().unwrap() {
        let page: PageGeometry = serde_json::from_value(case["page"].clone()).unwrap();
        let input: EngineBox = serde_json::from_value(case["input"].clone()).unwrap();
        let expected: [f64; 4] =
            serde_json::from_value(case["expected_pdf_user_space"].clone()).unwrap();
        assert_box(to_pdf_user_space(input, &page).unwrap(), expected);
    }
}

#[test]
fn pdfjs_effective_crop_is_separate_from_the_engines_raw_crop_frame() {
    let mut page = geometry(0, 1.0);
    page.crop_box = [-20.0, -40.0, 620.0, 800.0];
    let raw_crop = EngineBox {
        coords: [10.0, 10.0, 20.0, 20.0],
        space: CoordinateSpace::DisplayTopLeft {
            reference: PageBox::Crop,
        },
    };
    assert_box(
        to_pdf_user_space(raw_crop, &page).unwrap(),
        [-10.0, 780.0, 0.0, 790.0],
    );
    let viewport = EngineBox {
        coords: [10.0, 10.0, 20.0, 20.0],
        space: CoordinateSpace::DisplayTopLeft {
            reference: PageBox::EffectiveCrop,
        },
    };
    assert_box(
        to_pdf_user_space(viewport.clone(), &page).unwrap(),
        [10.0, 780.0, 20.0, 790.0],
    );
    page.crop_box = [700.0, 900.0, 800.0, 1000.0];
    assert_box(
        to_pdf_user_space(viewport, &page).unwrap(),
        [10.0, 820.0, 20.0, 830.0],
    );
}

#[test]
fn finite_values_with_overflow_or_precision_loss_are_rejected() {
    let mut page = geometry(0, 1.0);
    page.engine_to_pdf_user_space = Some(AffineTransform {
        a: 1e308,
        b: 1e308,
        c: 1e308,
        d: 1e308,
        e: 0.0,
        f: 0.0,
    });
    let input = EngineBox {
        coords: [0.0, 0.0, 1.0, 1.0],
        space: CoordinateSpace::EngineNative {
            name: "overflow".into(),
        },
    };
    assert!(to_pdf_user_space(input.clone(), &page).is_err());
    page.engine_to_pdf_user_space = Some(AffineTransform {
        a: 1.0,
        b: 0.0,
        c: 0.0,
        d: 1.0,
        e: 1e20,
        f: 1e20,
    });
    assert!(to_pdf_user_space(input, &page).is_err());
}
