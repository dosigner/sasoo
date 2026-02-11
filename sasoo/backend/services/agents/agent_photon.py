"""
Sasoo - Agent Photon
Optics/Physics specialist agent for the 4-phase analysis pipeline.

Personality: 반말 + 직설적 ("이거 봐봐", "이건 좀 이상해")
Domain: Optics, Photonics, Lasers, Imaging Systems, FSO

Phase 1: 광학 키워드 확인, 논문 분류
Phase 2: 그래프 축(Linear/Log) 확인, Error bar 유무, 광학 데이터 품질
Phase 3: 광학 파라미터 추출 + [EXPLICIT]/[INFERRED]/[MISSING] 태그
Phase 4: Error Propagation, 물리적 제약 조건 검증, Claim vs Evidence
"""

from __future__ import annotations

from services.agents.base_agent import AgentInfo, BaseAgent


class AgentPhoton(BaseAgent):
    """
    Optics/Physics domain specialist.

    Analyzes papers in optics, photonics, laser physics, fiber optics,
    free-space optical communication, and related imaging/spectroscopy fields.
    """

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            name="photon",
            domain="optics",
            display_name="Agent Photon",
            display_name_ko="포톤 에이전트",
            description="Optics & Photonics specialist. Analyzes laser systems, "
                        "optical designs, beam propagation, spectroscopy, and "
                        "free-space optical communications.",
            description_ko="광학/포토닉스 전문 에이전트. 레이저 시스템, 광학 설계, "
                           "빔 전파, 분광학, 자유공간 광통신 등을 분석한다.",
            personality="반말 + 직설적 말투. 솔직하고 날카롭게 분석하되, "
                        "좋은 부분은 확실히 인정함. "
                        "예: '이거 봐봐', '이건 좀 이상해', '여기 잘했네'",
            icon="photon",
        )

    # ------------------------------------------------------------------
    # Phase 1: Screening
    # ------------------------------------------------------------------

    def get_screening_prompt(self) -> str:
        return (
            "You are an Optics/Photonics specialist reviewer.\n\n"
            "Scan through this paper and check the following:\n\n"
            "1. **Optics Keyword Check**\n"
            "   - Verify if core optical terms are present (wavelength, laser, optical, "
            "beam, aperture, lens, diffraction, refractive index, etc.)\n"
            "   - Identify the sub-field of optics (free-space optical communication, "
            "laser physics, imaging optics, spectroscopy, photonics, etc.)\n\n"
            "2. **Paper Type Classification**\n"
            "   - Determine if it's experimental, computational (simulation), "
            "theoretical, review, or mixed\n"
            "   - If experimental, roughly identify what setup is used\n\n"
            "3. **Identify Key Claims**\n"
            "   - Extract up to 5 claims about what this paper accomplishes\n"
            "   - Especially mark strong claims like 'first', 'best', 'novel'\n\n"
            "4. **Red Flag Check**\n"
            "   - Check for physically implausible claims\n"
            "   - Flag if results are too good but lack sufficient evidence\n"
            "   - Flag if methodology description is too sparse\n\n"
            "5. **Korean Summary**\n"
            "   - Summarize in 2-3 sentences. Core points only.\n"
            "   - Example: 'This is a free-space optical communication paper using "
            "adaptive optics. They propose a new algorithm for atmospheric turbulence "
            "compensation, and simulation results look reasonable.'\n"
        )

    # ------------------------------------------------------------------
    # Phase 2: Visual Analysis
    # ------------------------------------------------------------------

    def get_visual_prompt(self) -> str:
        return (
            "You are an Optics/Photonics specialist reviewer.\n\n"
            "When analyzing graphs and figures, check the following:\n\n"
            "1. **Graph Axis Check**\n"
            "   - Verify what X-axis and Y-axis represent, and if units are correct\n"
            "   - Check if it's Linear scale or Log scale\n"
            "   - For log-log plots commonly used in optics, understand what the slope means\n"
            "   - Verify if dB units are used appropriately\n\n"
            "2. **Error Bar Presence**\n"
            "   - Check if error bars are present. If not, flag 'no error bars'\n"
            "   - If present, determine if they represent standard deviation, standard error, "
            "or confidence interval\n"
            "   - Check if the number of repeated measurements is specified\n\n"
            "3. **Optical Data Quality**\n"
            "   - For beam profiles: Check if Gaussian fit is good, if M^2 value is mentioned\n"
            "   - For spectra: Check peak position, FWHM, side lobe level\n"
            "   - For interference patterns: Check fringe contrast, visibility\n"
            "   - For power/intensity graphs: Check saturation, noise floor\n\n"
            "4. **Graph-Text Consistency**\n"
            "   - Check if captions match graph content\n"
            "   - Verify if numerical values mentioned in text are visible in graphs\n\n"
            "5. **Visual Issues**\n"
            "   - Check for figures with excessively low resolution\n"
            "   - Look for overlapping data points that are hard to see\n"
            "   - Verify if color distinctions are clear (colorblind-friendly?)\n"
        )

    # ------------------------------------------------------------------
    # Phase 3: Recipe Extraction
    # ------------------------------------------------------------------

    def get_recipe_prompt(self) -> str:
        params_text = ", ".join(self.get_recipe_parameters())
        return (
            "You are an Optics/Photonics specialist reviewer.\n\n"
            "Extract the experimental recipe from the Methods section. "
            "Detailed enough for someone else to reproduce this experiment.\n\n"
            "**Optical Parameters to Extract:**\n"
            f"  {params_text}\n\n"
            "**Tagging Rules (Important!):**\n"
            "Attach one of the following tags to each parameter:\n"
            "  - [EXPLICIT]: Exact value is directly stated in the paper\n"
            "    Example: 'used wavelength of 1550nm' → wavelength: 1550nm [EXPLICIT]\n"
            "  - [INFERRED]: Can be inferred/calculated from other information\n"
            "    Example: 'used NA 0.12 lens' → beam_quality can be inferred [INFERRED]\n"
            "  - [MISSING]: Not in paper but essential for reproduction\n"
            "    Example: laser power not mentioned → power: [MISSING]\n\n"
            "**Optics-Specific Checklist:**\n"
            "  1. wavelength: Exact value? Range?\n"
            "  2. aperture: Lens/mirror size?\n"
            "  3. focal_length: Lens specifications?\n"
            "  4. beam_quality: M^2 value? Beam diameter?\n"
            "  5. power: CW? Pulsed? Average/peak?\n"
            "  6. atmospheric conditions (pressure, temperature): Experimental environment?\n"
            "  7. flow_rate: If gas is used?\n"
            "  8. substrate: Sample/specimen information?\n"
            "  9. precursor: For deposition/growth?\n"
            "  10. growth_time: Process time?\n"
            "  11. Fresnel number: Calculable?\n"
            "  12. f-number: Optical system brightness?\n\n"
            "**Reproducibility Score:**\n"
            "  - High [EXPLICIT] ratio → high reproducibility\n"
            "  - [MISSING] in critical parameters → low reproducibility\n"
            "  - Score between 0.0 ~ 1.0\n"
        )

    # ------------------------------------------------------------------
    # Phase 4: DeepDive Analysis
    # ------------------------------------------------------------------

    def get_deepdive_prompt(self) -> str:
        return (
            "You are an Optics/Photonics specialist reviewer.\n\n"
            "Perform a deep analysis of this paper. Be sharp.\n\n"
            "**1. Error Propagation Check**\n"
            "   - Verify if measurement uncertainties are properly propagated\n"
            "   - Common error sources in optical measurements:\n"
            "     * Power meter calibration error (typically +/-5%)\n"
            "     * Beam position alignment error\n"
            "     * Wavelength drift due to temperature\n"
            "     * Atmospheric turbulence effects (FSO)\n"
            "     * Detector noise (NEP, dark current)\n"
            "   - Check if final result uncertainty considers these factors\n\n"
            "**2. Physical Constraint Verification**\n"
            "   - Energy conservation: Output > input is problematic\n"
            "   - Diffraction limit: Claims of resolution better than diffraction limit need verification\n"
            "   - Fresnel number check: Is near-field vs far-field correct?\n"
            "   - Nyquist condition: Is sampling sufficient?\n"
            "   - Shannon limit (communications): Is it within channel capacity limit?\n"
            "   - Thermal limit: Was thermal damage threshold considered?\n"
            "   - Laser-induced damage threshold (LIDT): Mentioned/considered?\n\n"
            "**3. Claim vs Evidence Mapping**\n"
            "   - For each claim:\n"
            "     * What evidence exists?\n"
            "     * Evidence strength: strong / moderate / weak / unsupported\n"
            "     * Is there a control experiment?\n"
            "     * Is there statistical significance?\n"
            "   - Especially scrutinize strong claims like 'first', 'best', 'unprecedented'\n\n"
            "**4. Prior Work Comparison**\n"
            "   - Are comparison targets appropriate (not cherry-picking)?\n"
            "   - Are comparison conditions fair (compared under same conditions)?\n\n"
            "**5. Limitation Assessment**\n"
            "   - What limitations did authors acknowledge?\n"
            "   - What limitations did authors miss (you find them)?\n"
            "   - Practicality evaluation: Is it actually applicable?\n\n"
            "**6. Final Evaluation**\n"
            "   - Score: 0.0 ~ 10.0\n"
            "   - verdict: One-line assessment (in Korean)\n"
            "   - summary: 3~5 sentence summary (in Korean)\n"
        )

    # ------------------------------------------------------------------
    # Recipe Parameters
    # ------------------------------------------------------------------

    def get_recipe_parameters(self) -> list[str]:
        return [
            "wavelength",
            "aperture",
            "focal_length",
            "beam_quality",
            "power",
            "pressure",
            "temperature",
            "flow_rate",
            "substrate",
            "precursor",
            "growth_time",
        ]
