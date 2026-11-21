# Presentation — LoRa remote patient monitoring

19-slide talk (16:9, about 15–20 minutes) built from the verified content of `report/`. The design brief is in
[PRESENTATION_PROMPT.md](PRESENTATION_PROMPT.md).

| File | Content |
|---|---|
| `RPM_LoRa_presentation.pptx` | the deck: native PowerPoint shapes, 4 native charts with embedded data, a native table, speaker notes on every slide, 5 sections |
| `RPM_LoRa_presentation.pdf` | PDF export of the same deck |
| `build_deck.ps1` | rebuilds the deck through PowerPoint COM automation (theme colours and fonts, layouts, slides, notes, sections, PDF, PNG renders) |
| `prepare_assets.ps1` | crops the report's photo and screenshots into `assets/` (System.Drawing) |
| `assets/` | cropped bench photo, dashboard screenshots, OMNeT++ screenshots |

## Rebuild (Windows with Microsoft PowerPoint and Excel)

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File presentation/prepare_assets.ps1
```

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File presentation/build_deck.ps1
```

The build opens PowerPoint (minimised) and briefly Excel for the chart data, saves the `.pptx` and `.pdf`, and writes
one PNG per slide to `presentation/renders/` for checking (pass another folder as the first argument to change it).
`build_deck.ps1` is saved as UTF-8 with BOM so Windows PowerShell 5.1 reads its special characters correctly.

## Structure

Opening (1–3: title, problem, results by evidence category) · System (4–8: architecture, bench prototype, 34-byte
frame, LoRa airtime, Raspberry Pi 5 UART troubleshooting) · Evaluation (9–15: OMNeT++/FLoRa model and results,
dashboard, synthetic data, model selection, early warning versus false alarms) · Security and lessons (16–17) ·
Outlook (18–19: status, next steps, questions).

All vital-sign values are synthetic or simulated; the slides label every result as tested, simulated, bench,
analytical, synthetic-model or pending.
