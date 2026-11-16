// Generated from services/analysis_execution.py `_run_recipe`; tests/stage_recipe.rs checks the bytes.
pub const HINT_OPTICS: &str = r#"
DOMAIN-SPECIFIC PARAMETERS (Optics/Photonics) — extract ALL of these if mentioned:
wavelength (nm), laser_power (W/mW), pulse_duration (fs/ps/ns), repetition_rate (Hz/MHz),
beam_diameter (mm/um), numerical_aperture (NA), focal_length (mm), magnification,
cavity_finesse, cavity_Q_factor, fiber_type (SMF/MMF), coupling_efficiency (%),
beam_quality_M2, polarization, modulation_frequency, detection_method,
signal_to_noise_ratio (dB), dark_count_rate, BER (bit error rate),
turbulence_strength (Cn2), propagation_distance (m/km), aperture_diameter,
pixel_pitch, resolution, phase_mask_levels, diffraction_efficiency"#;
pub const HINT_BIO: &str = r#"
DOMAIN-SPECIFIC PARAMETERS (Biology/Biomedical) — extract ALL of these if mentioned:
cell_type, passage_number, seeding_density (cells/cm2), culture_medium,
incubation_temperature (C), incubation_duration (h/days), CO2_concentration (%),
assay_type, antibody_primary, antibody_secondary, staining_protocol,
detection_method, sample_size_n, cell_viability (%), drug_concentration,
exposure_time, imaging_modality, magnification, resolution"#;
pub const HINT_AI_ML: &str = r#"
DOMAIN-SPECIFIC PARAMETERS (AI/ML) — extract ALL of these if mentioned:
architecture, num_layers, hidden_units, activation_function, optimizer,
learning_rate, batch_size, epochs, training_time, regularization,
dropout_rate, weight_initialization, training_data_size, test_data_split,
loss_function, evaluation_metric, GPU_type, precision (fp16/fp32),
augmentation_method, pretrained_model, fine_tuning_strategy"#;
pub const HINT_EE: &str = r#"
DOMAIN-SPECIFIC PARAMETERS (Electrical/Electronics) — extract ALL of these if mentioned:
technology_node (nm), supply_voltage (V), threshold_voltage (V), bias_current (uA/mA),
power_consumption (mW/uW), clock_frequency (Hz/MHz/GHz), gain (dB), bandwidth (Hz),
transistor_count, channel_length/width (nm/um), load_capacitance (fF/pF),
input_impedance (ohm), output_impedance (ohm), noise_figure (dB), SNR/SNDR (dB),
ENOB (bits), sampling_rate (S/s), slew_rate (V/us), phase_margin (deg),
figure_of_merit (FoM), die_area (mm2), efficiency (%)"#;
pub const HINT_GENERAL: &str = r#"
Look for ALL quantitative parameters: temperatures, pressures, durations, concentrations,
voltages, currents, frequencies, distances, speeds, sizes, ratios, percentages, etc."#;
pub const INSTRUCTION_HEAD: &str = r#"이 연구 논문에서 재현 가능한 실험 레시피를 추출해줘.

핵심 지시사항:
1. 재현에 필요한 정량 파라미터를 논문 전체(Methods뿐 아니라 Results·Discussion·그림 캡션·표·부록)에서 빠짐없이 찾아.
2. 각 파라미터마다 name, value, unit, notes(출처 섹션/문맥), source_tag를 포함해.
3. source_tag 규칙:
   - "explicit": 논문에 값이 직접 명시됨.
   - "inferred": 논문에 명시된 다른 값에서 계산·추론 가능 — notes에 근거와 계산을 적어.
4. 개수 목표는 없어. 논문에 실제로 있는 항목만 추출하고, 통상 기본값·상식·장비 기본 설정을 논문 값처럼 보충하지 마.
5. 재현에 필요한데 논문에 없는 항목은 parameters에 넣지 말고 missing_info에 기록해.
6. reproducibility_score는 explicit 핵심 파라미터의 충족도와 missing_info를 근거로 매겨.
7. 각 파라미터마다 그 값의 근거가 되는 논문 원문을 그대로(축자) evidence_quote에 옮겨.
   번역·요약·재작성·말줄임표·떨어져 있는 문장 결합은 금지야. 원문 언어 그대로 써.
8. evidence_quote는 그 파라미터를 뒷받침하는 가장 짧은 연속 스팬 하나로 해(1~2문장, 최대 300자).
   source_tag="explicit"이면 그 value가 인용 안에 실제로 들어 있어야 해.
9. evidence_page는 PDF 파일 기준 1-based 페이지 번호야(표지 포함). 논문에 인쇄된 페이지 번호가 아니야.
   논문 텍스트만 받은 경우에는 "--- Page N ---" 마커의 N을 써.
10. 축자로 옮길 수 없으면 evidence_quote를 빈 문자열로 두고 페이지도 추측하지 마.
    빈 근거가 지어낸 근거보다 나아 — 근거 없음은 화면에 그대로 표시돼.
11. 인용은 논문 PDF(또는 제공된 논문 텍스트)에서만 가져와. 앞선 단계(스크리닝·시각·인용 분석)
    결과는 인용 출처가 아니야.
12. name은 아래 DOMAIN-SPECIFIC PARAMETERS 목록에 있는 항목이면 그 표기를 그대로 쓰고,
    목록에 없으면 축약 없는 소문자 snake_case 전체 명칭으로 써(예: aperture가 아니라
    aperture_diameter). 같은 물리량에 임의의 다른 이름을 만들지 마.
13. 논문 유형에 적용되는 재현 조건을 steps에도 연결해: 전처리/정규화, 입력 분포와 sampling,
    학습 target/loss, 평가식과 단위/Jacobian 보정, solver/허용오차. 적용되지 않는 조건은 강제하지 마.
    원문에 좌표 변환이 있으면 입력 변환과 역변환, 밀도를 평가하는 좌표를 구분해.
    '보정 적용'이라는 지시만 쓰지 말고 원문에 보고된 보정식의 부호, 차원, 상수항을
    평가식에 명시해. 원문에 없는 보정값은 만들지 마.
14. missing_info는 '제공된 원문에서 확인하지 못함'이라고 쓰고 저자의 미보고를 단정하지 마.
    부록과 식의 보고값이 steps 또는 missing_info의 부재 주장과 충돌하지 않는지 확인해.
    seed, 작은 안정화 상수나 장비 설정은 확인한 실제 값만 써. 평가 표본 seed와 학습 seed를 구분해.
"#;
pub const INSTRUCTION_TAIL: &str = r#"

출력 필드: title(레시피 제목, 한국어), objective(실험 목적), materials(재료 리스트, 규격 포함),
equipment(장비 리스트, 모델번호 포함), parameters(각 항목 name/value/unit/notes/source_tag/evidence_quote/evidence_page),
steps(단계별 상세 설명, 온도·시간·속도 등 포함), critical_notes(재현 중요 참고사항),
expected_results(예상 결과), safety_notes(안전 주의사항), confidence(0.0~1.0),
missing_info(논문에 없어 재현에 걸림돌이 되는 항목), reproducibility_score(0.0~1.0)."#;
