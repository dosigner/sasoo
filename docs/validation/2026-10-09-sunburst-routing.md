# Sunburst for one difficult core image

Implemented gpt-image-2.5-sunburst for at most one core image per newly generated paper visualization plan. Other image requests continue to use gpt-image-2.5-flare. Mermaid and HTML routing are unchanged.

## Selection policy

The planner reports difficulty separately from importance, both as integer judgments from 0 to 100. Difficulty rubric: cross-panel consistency 40 points, spatial/connectivity complexity 40, and label/detail constraints 20. These are model judgments, not calibrated probabilities.

Eligible purposes are structure, process, and comparison. Eligibility requires importance >= 60 and difficulty >= 70. Among eligible images, choose maximum difficulty, breaking ties by importance and then stable plan order. Additional images never receive Sunburst. If no core image qualifies, all images use Flare. Backend normalization owns this decision and discards invalid difficulty scores from eligibility.

The selected image uses the configured quality ceiling, currently high in the development workspace. A selected structure image gets high instead of the usual medium. Lower user ceilings are respected. No settings were changed in this turn.

## Integration

- Added the exact model constant and the Sunburst token pricing entry.
- OpenAI renderer sends the selected model ID and charges reported usage using that model's rates. It retains the existing typography instructions, 1536x1024 resolution, PNG output, concurrency protection, and timeout handling.
- Persisted image_model and difficulty in each generated item and exposed them in the response types. Regeneration keeps the selected model.
- Added Sunburst to the visualization cache key and changed the visualization policy version. The planning prompt/schema changed, so old plans with no difficulty score do not masquerade as newly scored plans.
- Explicit model renders include model and quality in their filenames, preventing a model switch from overwriting the earlier asset or reusing its browser URL. Long UTF-8 titles leave room for this prefix. Legacy requests with no model override keep their previous naming.
- Cards show Flare/Sunburst, quality, importance, and difficulty. Failed renders can still show their requested model. Settings explain the one-image policy and the quality ceiling.
- No automatic Flare retry if a selected Sunburst render fails. No package dependency or database migration.

## Price and live render verification

Official prices checked on 2026-10-09: both models use text input $5/M, image input $8/M, and image output $30/M for standard direct API requests. Equal rates do not guarantee equal image costs.

[Sunburst model](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), [pricing](https://developers.openai.com/api/docs/pricing).

One live call per model used the identical synthetic optical-architecture description, high quality, 1536x1024, PNG, and identical typography instructions. The text planner was stubbed to that saved description to remove planning variation and extra text charges. No retries were made.

| Model | Render cost USD | End-to-end generation seconds |
|---|---:|---:|
| gpt-image-2.5-flare | 0.043200 | 17.6 |
| gpt-image-2.5-sunburst | 0.043200 | 39.2 |

The observed additional cost was zero for this pair. Total renderer cost was $0.086400. This is one example, not a latency distribution or a quality benchmark. The two generated illustrations were visually inspected. Neither image is evidence of a physically validated optical system. The paid samples predate the final filename-prefix change; the final naming behavior was covered by filesystem regression tests rather than paid rerenders.

## Checks

- Backend: 278 tests and 73 subtests passed across services/test_synthesis.py, services/test_figure_gen.py, services/test_pricing_images.py, services/test_model_registry.py, and api/test_analysis_routes.py.
- Frontend: TypeScript/build and changed-file ESLint passed; the existing synthesis/lightbox checks passed, 9 tests.
- Regression coverage: one-image limit, difficulty versus importance, excluded additional images, invalid scores, quality ceilings, exact Images API model ID, token usage requirements, no fallback retry, cache identity, preserved model on regeneration, distinct assets after a model switch, and long Korean filenames.
- Chrome: 1440x900 light and 1024x768 dark, with frozen API responses and real generated image files. Verified one Sunburst card and two Flare cards, model/difficulty labels, image loading, enlargement, and the settings model description. Zero JavaScript exceptions, console errors, or API write requests. The fixture combines illustrative assets to exercise presentation; it is not an analysis of the paper shown in the PDF fixture.

Artifacts: [receipts](assets/sunburst-routing-2026-10-09/receipts.json), [fixed description](assets/sunburst-routing-2026-10-09/description.txt), [selected plan](assets/sunburst-routing-2026-10-09/selected-plan.json), [GUI report](assets/sunburst-routing-2026-10-09/gui.json), [Flare sample](assets/sunburst-routing-2026-10-09/paperbanana/1_gpt_image_25_flare.png), [Sunburst sample](assets/sunburst-routing-2026-10-09/paperbanana/2_gpt_image_25_sunburst.png).

Existing user papers were not reanalyzed, the installed app was not rebuilt, and no deployment was performed. A running backend needs to load the changed source. Existing images acquire new model assignments only when their visualization plan is generated again.
