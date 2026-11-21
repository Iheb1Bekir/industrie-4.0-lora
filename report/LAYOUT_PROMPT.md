# Prompt — rebuild the RPM LoRa report as a single-column, 6–7-page PDF

**Role.** Senior IoT/healthcare researcher and LaTeX typesetter.

**Input.** `report/main.tex` (previous two-column IEEE version), `report/figures/**` (TikZ diagrams, pgfplots
plots, data files, photo, screenshots), `report/references.bib`, `report/tools/*`.

**Goal.** Regenerate `report/main.pdf` with the same verified content in a layout that is fast to read.

## Layout rules
1. **One column on every page** — no two-column (IEEE) page split. A4, 10 pt Times, margins about 1.8 cm.
2. **6–7 pages in total, references included; never more than 7.**
3. **No long paragraphs**: at most about 3 lines of running text; each section = one lead sentence + short bullets
   (bold lead-in words) + tables/figures.
4. Figures and tables span the page width or sit side by side in balanced pairs (figure + table, photo + notes,
   plot + plot). No half-empty pages; floats stay inside their own section.
5. Readability: diagrams as TikZ (vector), plots as pgfplots read from `figures/data`, screenshots cropped to the
   informative region, no text smaller than the caption size except inside diagrams.
6. Page 1 shows the title, a short abstract box and a **“results at a glance”** table grouped by evidence category.

## Content rules (scientific honesty unchanged)
- Keep every number and its source; add no new claims; keep the synthetic/simulated/bench/pending labels.
- Keep the mandatory items: architecture, hardware table + real photo, firmware and frame format, LoRa airtime
  analysis, Raspberry Pi 5 UART troubleshooting (overlay, GPIO2, wiring, commands, pending status), OMNeT++/INET/FLoRa
  environment, configurations, screenshots and results with the FLoRa airtime caveat, dashboard screenshots, data
  analysis, model evaluation, security status, engineering challenges, conclusion, references.

## Process
Rewrite `main.tex` → compile with Tectonic → check page count, overfull boxes, undefined references → inspect every
page visually → fix → copy the PDF to `report/main.pdf` → refresh `RPM_LoRa_report_overleaf.zip`.

## Acceptance
Single column on all pages · ≤ 7 pages · no paragraph longer than about 3 lines · no overlapping or overflowing
elements · every figure and table referenced · compiles with pdfLaTeX (Overleaf) and Tectonic (XeTeX).
