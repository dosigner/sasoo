# Mixed paper visualizations, 2026-10-09

Implemented the requested allocation:

| Purpose | Output | Quality with the high ceiling |
|---|---|---|
| 1, structure | gpt-image-2.5-flare image | medium |
| 2, process/state changes | gpt-image-2.5-flare image | high |
| 3, roles and time order | Mermaid sequence | text model |
| 4, baseline/proposed comparison | gpt-image-2.5-flare image | high |
| 5, parameter/output relationships | sandboxed HTML and SVG | text model |
| Additional images | At most 2, importance >= 60/100 | medium |
| Additional Mermaid diagrams | At most 2, importance >= 60/100 | text model |

The planner omits unsupported purposes. HTML requires a source equation and coefficients or suitable data. Importance is a model judgment, not a probability. The prompt scores contribution understanding out of 40, nonredundant information out of 30, and source evidence out of 30. Backend normalization enforces the limits, rejects invalid extra scores, and selects higher-scored extras first. The overall maximum is 9 items: 5 images, 3 Mermaid diagrams, and 1 HTML explainer.

Settings retain the low/medium/high ceiling control. To enable the requested quality allocation in the development workspace, changed only the persisted image_quality setting from medium to high after checking for active analysis workers. The provider and API key settings were unchanged. Existing saved visualizations still open; this policy applies when a new plan is generated. A running backend must load the changed source before using the new planning policy.

## Models and cost evidence

Official documentation checked on this date describes Flare as the fastest high-quality everyday image model and Sunburst as the most capable image model, particularly for editing precision. Both have the same token rates: text input $5/M, image input $8/M, image output $30/M. Equal token rates do not imply equal per-image cost. Kept the exact requested Flare model.

Sources: [Flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare), [Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), [image generation guide](https://developers.openai.com/api/docs/guides/image-generation).

Live synthetic sample receipts:

| Image | Quality | Image renderer cost, USD |
|---|---|---:|
| Structure | medium | 0.015300 |
| Initial process example | high | 0.045940 |
| Comparison | high | 0.046200 |
| Process example with pictorial state snapshots | high | 0.044070 |

The final three image samples total $0.105570 in image rendering. All four validation image calls total $0.151510. The HTML generation call reported $0.0028321; the live planning call reported $0.00081705. These amounts do not include the per-image text planning calls or the Mermaid text call, whose usage was not collected in this validation. Do not treat them as a complete billing ledger or fixed prices. The quality comparison used different requests and is not a controlled model/quality benchmark. Missing successful image/HTML usage now leaves the stored aggregate cost unknown instead of zero.

## Validation

- Backend: 234 tests and 10 subtests passed across services/test_synthesis.py, services/test_figure_gen.py, and api/test_analysis_routes.py.
- Frontend: 9 tests passed, TypeScript/build passed, changed-file ESLint passed, git diff --check passed.
- Live planning selected structure, process, comparison, sequence, and HTML for the synthetic teaching source. Planning database writes were mocked.
- Chrome at 1440x900 and 1024x768: three actual generated images, a generated sequence, and HTML all loaded; zero JavaScript exceptions and console errors.
- Chrome dark view at 1440x900: all nine items remained visible in their sections. The two extra images and two extra diagrams were layout copies, not additional paid generations. ZIP export contained eight PNGs, three Mermaid sources, and one sandboxed HTML document.
- HTML sandbox blocked access to the parent document and localStorage. CSP disables external connections and resources. Runtime errors get an in-frame alert. Regeneration and export preserve the HTML payload.
- Legacy block assignment tests remained green. No new package dependency or database schema migration.

The synthetic example uses an ideal RC circuit with R=1000 ohm, default C=1 microfarad, a 1 V step at t=0, initial capacitor voltage zero, and y(t)=1-exp(-t/tau) V, where tau=R*C. Both t and tau use milliseconds in the ratio. Five input combinations were checked against Python math.exp. Maximum displayed voltage error was 3.5283236613e-5 V, consistent with four-decimal rounding. SVG marker coordinates agreed with the analytic output within 1e-9 pixels. Zero tau was rejected. The SVG curve has 100 linear segments over 0-10 ms; it is an illustrative curve, not a precision numerical result.

The original generated HTML showed fixed C while allowing tau to change. The validated copy links C to tau at fixed R and labels baseline and adjusted conditions separately; the analytic equation and reference outputs were unchanged. The production prompt now requires dependent parameters to remain consistent. The original response remains in samples.json and the validation edit is separately recorded in validated_html.json.

Image review found unnecessary quantitative plots in the first structure/comparison examples and misleading time-axis placement in the first process example. Narrowed the shared prompt to components, connections, and pictorial state snapshots, with no quantitative plots unless explicitly requested. A new process sample verified that layout. The structure and comparison samples were not rerun after this prompt refinement. Generated images remain illustrations requiring source review; high quality does not certify scientific accuracy. The Mermaid prompt now also distinguishes passive measurements from active control messages.

Artifacts: [samples and scripts](assets/mixed-visualizations-2026-10-09/), [live plan](assets/mixed-visualizations-2026-10-09/live-plan.json), [GUI checks](assets/mixed-visualizations-2026-10-09/gui.json), [maximum/export checks](assets/mixed-visualizations-2026-10-09/maximum-nine.json), [ZIP](assets/mixed-visualizations-2026-10-09/visualizations.zip), [settings change](assets/mixed-visualizations-2026-10-09/settings-change.json).

No Sunburst comparison, installed-app rebuild, deployment, or reanalysis of existing user papers was performed.
