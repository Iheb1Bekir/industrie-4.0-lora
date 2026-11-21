# Prompt — full PowerPoint presentation of the LoRa remote patient monitoring project

**Role.** Senior IoT/healthcare researcher and presentation designer.

**Purpose and audience.** A 15–20 minute live talk (project defence / technical review) for an engineering and
academic jury, followed by questions. The slides carry few words and strong visuals; the speaker notes carry the full
narrative, so the deck also works as a handout.

**Source of truth (never invent).** `report/main.tex`, `report/figures/**` (photo, OMNeT++ screenshots, dashboard
screenshots), `report/figures/data/*.dat`, `ml/models/ew-20261114/*.json`, `simulation/omnetpp/imported_results/*.json`.
Every number on a slide must exist in these sources. Keep the evidence labels: *tested*, *simulated*, *bench*,
*analytical*, *synthetic data*, *pending*. Never present synthetic or simulated values as patient data and never
claim clinical validation.

## Format
- Native PowerPoint `.pptx`, 16:9 (13.33 × 7.5 in), built inside PowerPoint so every shape, table and chart is
  editable (charts are native charts with embedded data, not pictures).
- Theme defined once: dark midnight-teal for title and closing slides, white content slides; teal primary,
  coral for alerts and gaps, green for tested, amber for pending/simulation, slate for neutral text.
  Fonts: Cambria for titles, Calibri for text. Slide numbers and a small footer on content slides; PowerPoint
  sections for the parts of the talk.
- Visual motif: a vital-sign pulse line on the dark slides; icons in coloured circles and soft rounded cards on
  content slides; rounded picture frames for photos and screenshots. No accent bars or title underlines.

## Structure (19 slides)
1. Title · 2. The problem · 3. What was built and what the evidence shows · 4. Architecture ·
5. Hardware and bench prototype · 6. The 34-byte authenticated frame · 7. LoRa airtime and contention ·
8. Raspberry Pi 5 UART troubleshooting · 9. OMNeT++/FLoRa model · 10. Simulation results ·
11. Dashboard overview · 12. Patient view and predictive warning · 13. Synthetic dataset ·
14. Model selection · 15. Early warning versus false alarms · 16. Security status ·
17. Engineering lessons · 18. Status and next steps · 19. Thank you / questions

## Design rules
- One message per slide; the title states it (short assertion, no final period, same position on every content slide).
- Every slide has a visual: photo, screenshot, native chart, native diagram, icon cards or big-number callouts.
- At most about 6 short bullet lines per slide; body text ≥ 14 pt, captions ≥ 10 pt, margins ≥ 0.5 in.
- Charts: native, data labels on, the same axis/label styling on every chart, theme colours only.
- Speaker notes on every slide (about 60–120 words) telling the story and the caveats.

## Process
Write a reproducible build script (PowerPoint COM automation) → build → export every slide to PNG → inspect each
render for overflow, overlap, contrast and alignment → fix and rebuild → also export a PDF copy.

## Deliverables
`presentation/RPM_LoRa_presentation.pptx`, `presentation/RPM_LoRa_presentation.pdf`, `presentation/build_deck.ps1`,
this prompt.
