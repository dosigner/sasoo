"""
Sasoo - Agent Circuit
Electrical Engineering specialist agent for the 4-phase analysis pipeline.

Personality: Practical + concise ("Check the bias point.", "This layout won't scale.")
Domain: Semiconductor devices, Circuit design, Signal processing

Phase 1: EE keyword check, paper classification
Phase 2: Circuit schematics, SPICE plots, layout images, S-parameter analysis
Phase 3: EE parameter extraction + [EXPLICIT]/[INFERRED]/[MISSING] tags
Phase 4: Claim vs Evidence, SPICE-measurement consistency, PPA tradeoff
"""

from __future__ import annotations

from services.agents.base_agent import AgentInfo, BaseAgent


class AgentCircuit(BaseAgent):
    """
    Electrical Engineering domain specialist.

    Analyzes papers in semiconductor devices, analog/digital circuit design,
    signal processing, RF/microwave, and power electronics.
    """

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            name="circuit",
            domain="ee",
            display_name="Agent Circuit",
            display_name_ko="서킷 에이전트",
            description="Electrical Engineering specialist. Analyzes semiconductor "
                        "devices, circuit design, signal processing, RF systems, "
                        "and power electronics.",
            description_ko="전기/전자공학 전문 에이전트. 반도체 소자, 회로 설계, "
                           "신호처리, RF 시스템, 전력전자 등을 분석한다.",
            personality="Practical and concise. Focuses on measurable specs and "
                        "real-world feasibility. No fluff — just the numbers and "
                        "whether they hold up.",
            icon="circuit",
        )

    # ------------------------------------------------------------------
    # Phase 1: Screening
    # ------------------------------------------------------------------

    def get_screening_prompt(self) -> str:
        return (
            "You are an Electrical Engineering specialist reviewer.\n\n"
            "Scan this paper and check the following:\n\n"
            "1. **EE Keyword Identification**\n"
            "   - Look for core EE terms (MOSFET, FinFET, CMOS, transistor, "
            "amplifier, oscillator, PLL, ADC, DAC, filter, impedance, "
            "S-parameters, gain, bandwidth, noise figure, SNR, etc.)\n"
            "   - Identify the sub-domain: semiconductor devices, analog circuits, "
            "digital circuits, signal processing, RF/microwave, power electronics, "
            "MEMS, or mixed\n\n"
            "2. **Paper Type Classification**\n"
            "   - Classify as: experimental (fabrication + measurement), "
            "simulation (SPICE, TCAD, EM solvers), theoretical (modeling), "
            "design (new topology/architecture), mixed\n"
            "   - If experimental, identify the fabrication process and "
            "measurement equipment used\n\n"
            "3. **Key Claims Extraction**\n"
            "   - Extract up to 5 main claims\n"
            "   - Flag strong claims like 'state-of-the-art', 'record-breaking', "
            "'first demonstration', or 'outperforms'\n"
            "   - Note the FoM (Figure of Merit) used for comparison\n\n"
            "4. **Red Flag Check**\n"
            "   - Simulation-only results claimed as 'demonstrated' or 'achieved'\n"
            "   - Missing process corner / PVT (Process-Voltage-Temperature) analysis\n"
            "   - Performance numbers that seem too good for the technology node\n"
            "   - Comparison against outdated or weak baselines\n"
            "   - No measurement setup description for experimental claims\n\n"
            "5. **Summary**\n"
            "   - 2-3 sentence summary. Focus on what was built/designed, "
            "what technology node, and the key performance metric.\n"
        )

    # ------------------------------------------------------------------
    # Phase 2: Visual Analysis
    # ------------------------------------------------------------------

    def get_visual_prompt(self) -> str:
        return (
            "You are an Electrical Engineering specialist reviewer.\n\n"
            "Analyze the figures and plots with these checks:\n\n"
            "1. **Circuit Schematics**\n"
            "   - Are all transistor sizes (W/L) labeled?\n"
            "   - Are bias voltages and currents indicated?\n"
            "   - Is the topology clearly identifiable (cascode, differential, "
            "folded cascode, etc.)?\n"
            "   - Are parasitic elements shown where relevant?\n\n"
            "2. **SPICE / Simulation Plots**\n"
            "   - Check axes: frequency (Hz/GHz), voltage (V/mV), "
            "current (A/mA/uA), dB\n"
            "   - Verify gain/bandwidth consistency with claims in text\n"
            "   - Look for proper corner analysis (TT, FF, SS, SF, FS)\n"
            "   - Check transient vs steady-state behavior\n"
            "   - Monte Carlo analysis present? How many runs?\n\n"
            "3. **Layout Images**\n"
            "   - Die photo or layout screenshot with scale bar?\n"
            "   - Active area vs total die area identifiable?\n"
            "   - Symmetry in differential/matched structures?\n"
            "   - Guard rings, decoupling caps visible where needed?\n\n"
            "4. **S-Parameter / RF Plots**\n"
            "   - Smith chart readings consistent with claimed impedance?\n"
            "   - S11, S21, S12, S22 clearly labeled?\n"
            "   - Stability factor (K) plotted if amplifier?\n"
            "   - Noise figure vs frequency shown?\n\n"
            "5. **Measurement vs Simulation Comparison**\n"
            "   - Are both overlaid on the same plot?\n"
            "   - What is the discrepancy? Is it explained?\n"
            "   - Post-layout simulation included?\n\n"
            "6. **Comparison Tables / FoM Charts**\n"
            "   - Is the comparison fair? Same technology node?\n"
            "   - Are the cited works recent?\n"
            "   - FoM definition clearly stated?\n"
            "   - Cherry-picking: does it only win on one metric?\n"
        )

    # ------------------------------------------------------------------
    # Phase 3: Recipe Extraction
    # ------------------------------------------------------------------

    def get_recipe_prompt(self) -> str:
        params_text = ", ".join(self.get_recipe_parameters())
        return (
            "You are an Electrical Engineering specialist reviewer.\n\n"
            "Extract the design/fabrication recipe from the Methods section. "
            "Be detailed enough for someone to reproduce or re-simulate this work.\n\n"
            "**Parameters to extract:**\n"
            f"  {params_text}\n\n"
            "**Tagging rules (critical):**\n"
            "Tag each parameter with one of:\n"
            "  - [EXPLICIT]: Exact value stated directly in the paper\n"
            "    e.g., 'Fabricated in TSMC 65nm CMOS' -> process_node: 65nm [EXPLICIT]\n"
            "  - [INFERRED]: Can be calculated or deduced from other information\n"
            "    e.g., 'Unity-gain bandwidth of 1 GHz' -> bandwidth inferred [INFERRED]\n"
            "  - [MISSING]: Not stated but essential for reproduction\n"
            "    e.g., No supply voltage mentioned -> supply_voltage: [MISSING]\n\n"
            "**EE-specific checklist:**\n"
            "  1. process_node: Technology (65nm, 28nm, etc.)? Foundry?\n"
            "  2. transistor_type: MOSFET, FinFET, GAA, BJT, HBT?\n"
            "  3. supply_voltage: Vdd value? Multiple supplies?\n"
            "  4. operating_frequency: Clock, carrier, or signal frequency?\n"
            "  5. bandwidth: -3dB bandwidth? In what configuration?\n"
            "  6. gain: Voltage gain (dB)? Power gain? Open-loop/closed-loop?\n"
            "  7. power_consumption: Static + dynamic? Per channel?\n"
            "  8. noise_figure: NF in dB? At what frequency?\n"
            "  9. die_area: Core area vs total area? Including pads?\n"
            "  10. input_referred_noise: Noise spectral density?\n"
            "  11. linearity: IP3, P1dB, THD, SFDR?\n"
            "  12. sampling_rate: For ADC/DAC, what rate? ENOB?\n"
            "  13. simulation_tool: SPICE variant? EM solver?\n"
            "  14. measurement_setup: VNA, spectrum analyzer, oscilloscope?\n\n"
            "**Hidden recipe items to check:**\n"
            "  - Bias current/voltage values\n"
            "  - Transistor sizing (W/L ratios)\n"
            "  - Decoupling capacitor values\n"
            "  - PCB/package parasitics considered?\n"
            "  - Temperature range tested\n"
            "  - ESD protection included?\n\n"
            "**Reproducibility score:**\n"
            "  - High [EXPLICIT] ratio = high reproducibility\n"
            "  - [MISSING] on process_node, supply_voltage, or transistor sizing = "
            "critical gap\n"
            "  - Score from 0.0 to 1.0\n"
        )

    # ------------------------------------------------------------------
    # Phase 4: DeepDive Analysis
    # ------------------------------------------------------------------

    def get_deepdive_prompt(self) -> str:
        return (
            "You are an Electrical Engineering specialist reviewer.\n\n"
            "Perform a deep critical analysis of this paper.\n\n"
            "**1. Simulation vs Measurement Consistency**\n"
            "   - Compare simulation results against measurements\n"
            "   - Is the discrepancy reasonable for the technology?\n"
            "   - Was post-layout extraction done before measurement comparison?\n"
            "   - Are parasitics (bonding wire, package, PCB) accounted for?\n\n"
            "**2. PVT / Corner Analysis**\n"
            "   - Was process variation (TT/FF/SS/SF/FS corners) considered?\n"
            "   - Temperature range tested (-40 to 125C? or just room temp?)\n"
            "   - Supply voltage variation (nominal +/- 10%)?\n"
            "   - Monte Carlo analysis with how many runs?\n\n"
            "**3. Claim vs Evidence Mapping**\n"
            "   - For each claim:\n"
            "     * What evidence supports it?\n"
            "     * Evidence strength: strong / moderate / weak / unsupported\n"
            "     * Is the claim from simulation or measurement?\n"
            "     * Statistical significance: repeated measurements? yield data?\n"
            "   - Scrutinize 'state-of-the-art' and 'record' claims rigorously\n\n"
            "**4. Figure of Merit (FoM) Evaluation**\n"
            "   - Is the FoM definition standard for this sub-field?\n"
            "   - Does it hide weaknesses? (e.g., good FoM but poor linearity)\n"
            "   - Are all compared works using the same FoM definition?\n\n"
            "**5. Scalability & Practical Concerns**\n"
            "   - Can this design scale to advanced nodes?\n"
            "   - Power/area overhead for the proposed technique\n"
            "   - Sensitivity to component mismatch\n"
            "   - Testability and manufacturability\n\n"
            "**6. Prior Work Comparison**\n"
            "   - Are compared works recent and relevant?\n"
            "   - Fair comparison conditions (same node, same specs)?\n"
            "   - Any important competing work omitted?\n\n"
            "**7. Limitations Assessment**\n"
            "   - Limitations acknowledged by authors\n"
            "   - Limitations missed by authors (you identify these):\n"
            "     * Single-corner or single-sample results\n"
            "     * No reliability/aging data\n"
            "     * Simulation-only claims for key metrics\n"
            "     * Missing noise/linearity/power tradeoff discussion\n"
            "   - Practical applicability: ready for product integration?\n\n"
            "**8. Final Verdict**\n"
            "   - Score: 0.0 to 10.0\n"
            "   - verdict: One-line assessment\n"
            "   - summary: 3-5 sentence summary\n"
        )

    # ------------------------------------------------------------------
    # Recipe Parameters
    # ------------------------------------------------------------------

    def get_recipe_parameters(self) -> list[str]:
        return [
            "process_node",
            "transistor_type",
            "supply_voltage",
            "operating_frequency",
            "bandwidth",
            "gain",
            "power_consumption",
            "noise_figure",
            "die_area",
            "input_referred_noise",
            "linearity",
            "sampling_rate",
            "simulation_tool",
            "measurement_setup",
        ]
