"""Report generation: CSV (stdlib csv) and PDF (small dependency-free writer, Helvetica/Courier, Latin-1).

Every report states the patient identifier, the reporting period, the data source (hardware / SIMULATION),
the generation timestamp (UTC) and a disclaimer. Reports never contain data the requesting user may not see:
the API layer scopes the rows before calling these functions.
"""
import csv
import io
from datetime import datetime, timezone

DISCLAIMER = ("Research prototype - not a medical device. Thresholds are configurable engineering values, not clinical "
              "rules. Predictions come from a model trained on synthetic data and are decision support only.")


def iso(ts):
    return "" if ts is None else datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z"


def _safe_cell(v):
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_csv(header_lines, columns, rows):
    buf = io.StringIO()
    for line in header_lines:
        buf.write("# " + line.replace("\n", " ") + "\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([_safe_cell(r.get(c)) if not c.endswith("_utc") else iso(r.get(c[:-4])) for c in columns])
    return buf.getvalue().encode("utf-8")


class Pdf:
    """Minimal multi-page text PDF (A4). add(text, style) with style in: h1, h2, body, mono, small."""
    W, H, MARGIN = 595, 842, 50
    STYLES = {"h1": ("F2", 16, 24), "h2": ("F2", 12, 20), "body": ("F1", 10, 14), "mono": ("F3", 8, 11), "small": ("F1", 8, 11)}

    def __init__(self, footer=""):
        self.pages, self.cur, self.y, self.footer = [], [], self.H - self.MARGIN, footer

    @staticmethod
    def _esc(s):
        s = str(s).encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _newpage(self):
        if self.cur:
            self.pages.append(self.cur)
        self.cur, self.y = [], self.H - self.MARGIN

    def add(self, text="", style="body"):
        font, size, lead = self.STYLES[style]
        width = int((self.W - 2 * self.MARGIN) / (size * (0.6 if font == "F3" else 0.5)))
        for para in str(text).split("\n"):
            words, line, lines = para.split(" "), "", []
            for w in words:
                if len(line) + len(w) + 1 > width and line:
                    lines.append(line); line = w
                else:
                    line = (line + " " + w) if line else w
            lines.append(line)
            for ln in lines:
                if self.y < self.MARGIN + 30:
                    self._newpage()
                self.cur.append(f"BT /{font} {size} Tf {self.MARGIN} {self.y:.0f} Td ({self._esc(ln)}) Tj ET")
                self.y -= lead

    def table(self, columns, rows, widths):
        fmt = lambda cells: " ".join(str("" if c is None else c)[:w].ljust(w) for c, w in zip(cells, widths))  # noqa: E731
        self.add(fmt(columns), "mono")
        self.add("-" * (sum(widths) + len(widths) - 1), "mono")
        for r in rows:
            self.add(fmt(r), "mono")

    def render(self):
        self._newpage()
        objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
                "<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"]
        kids = []
        for i, page in enumerate(self.pages):
            foot = f"BT /F1 7 Tf {self.MARGIN} 28 Td ({self._esc(self.footer)} - page {i + 1}/{len(self.pages)}) Tj ET"
            stream = "\n".join(page + [foot]).encode("latin-1", "replace")
            objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            content_id = len(objs)
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.W} {self.H}] /Contents {content_id} 0 R "
                        f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> >>")
            kids.append(f"{len(objs)} 0 R")
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
        out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
        for i, o in enumerate(objs):
            offsets.append(len(out))
            out += f"{i + 1} 0 obj\n".encode() + (o if isinstance(o, bytes) else o.encode("latin-1")) + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def _stats(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return ("no data", "", "", 0)
    return (f"{min(vals):.1f}", f"{sum(vals) / len(vals):.1f}", f"{max(vals):.1f}", len(vals))


def patient_pdf(patient, source, t_from, t_to, measurements, alerts, predictions, generated_at, generated_by):
    label = "SIMULATION (synthetic data - not a real patient)" if source == "simulation" else "Hardware measurements"
    pdf = Pdf(footer=f"RPM patient report {patient['code']} - generated {iso(generated_at)} - {label}")
    pdf.add("Remote Patient Monitoring - Patient report", "h1")
    pdf.add(f"Patient: {patient['full_name']}   Identifier: {patient['code']} (patientId {patient['id']})")
    pdf.add(f"Reporting period (UTC): {iso(t_from)}  to  {iso(t_to)}")
    pdf.add(f"Data source: {label}")
    pdf.add(f"Generated: {iso(generated_at)} by {generated_by}")
    pdf.add("")
    pdf.add("Measurement summary", "h2")
    pdf.table(["Vital sign", "Min", "Mean", "Max", "Samples"],
              [["Heart rate (bpm)", *_stats(measurements, "heart_rate")], ["SpO2 (%)", *_stats(measurements, "spo2")],
               ["Temperature (C)", *_stats(measurements, "temperature")]], [22, 9, 9, 9, 8])
    falls = sum(1 for m in measurements if m.get("fall_detected"))
    faulty = sum(1 for m in measurements if m.get("quality") != "ok")
    pdf.add(f"Measurements received: {len(measurements)}; fall flags: {falls}; records with sensor/data-quality issues: {faulty}.")
    pdf.add("Missing values are reported as missing; they are never counted as normal readings.", "small")
    pdf.add("")
    pdf.add(f"Alerts in period ({len(alerts)})", "h2")
    if alerts:
        pdf.table(["Created (UTC)", "Type", "Severity", "Status", "Message"],
                  [[iso(a["created_at"])[:19], a["type"], a["severity"], a["status"], a["message"]] for a in alerts[:200]],
                  [19, 24, 8, 14, 40])
    else:
        pdf.add("No alert was recorded in this period.")
    pdf.add("")
    ok = [p for p in predictions if p["status"] == "ok"]
    pdf.add("Prediction information", "h2")
    if ok:
        high = sum(1 for p in ok if p["risk_category"] == "high")
        med = sum(1 for p in ok if p["risk_category"] == "medium")
        pdf.add(f"Model: {ok[-1]['model_name']} version {ok[-1]['model_version']}; type: {ok[-1]['prediction_type']}.")
        pdf.add(f"Predictions computed: {len(ok)} (high risk: {high}, medium: {med}, low: {len(ok) - high - med}). "
                f"Not computed (insufficient data / model unavailable): {len(predictions) - len(ok)}.")
    else:
        pdf.add(f"No prediction was computed in this period ({len(predictions)} attempts without sufficient data or model).")
    pdf.add("")
    pdf.add("Disclaimer", "h2")
    pdf.add(DISCLAIMER, "small")
    return pdf.render()


def model_pdf(meta, metrics, generated_at):
    pdf = Pdf(footer=f"RPM model evaluation report - generated {iso(generated_at)}")
    pdf.add("Model evaluation report", "h1")
    pdf.add(f"Model: {meta['model_name']}   Version: {meta['version']}   Trained: {meta['trained_at']}")
    ds = meta["dataset"]
    pdf.add(f"Dataset: {ds['version']} (SYNTHETIC, seed {ds['seed']}), patients train/val/test: "
            f"{ds['patients']['train']}/{ds['patients']['val']}/{ds['patients']['test']}, "
            f"samples train/val/test: {ds['samples']['train']}/{ds['samples']['val']}/{ds['samples']['test']}")
    pdf.add(f"Prediction target: {meta['target']}")
    pdf.add("")
    pdf.add("Held-out test set results (all compared models)", "h2")
    cols = ["Model", "Acc", "Prec", "Recall", "Spec", "F1", "ROC-AUC", "PR-AUC", "FPR", "FNR"]
    rows = [[n, *[f"{m['test'][k]:.3f}" for k in ("accuracy", "precision", "recall", "specificity", "f1", "roc_auc", "pr_auc", "fpr", "fnr")]]
            for n, m in metrics["models"].items()]
    pdf.table(cols, rows, [22, 6, 6, 6, 6, 6, 7, 7, 6, 6])
    sel = metrics["models"][meta["model_name"]]["test"]
    cm = sel["confusion_matrix"]
    pdf.add("")
    pdf.add(f"Selected model confusion matrix (test): TN={cm['tn']}  FP={cm['fp']}  FN={cm['fn']}  TP={cm['tp']}")
    if "events" in sel:
        e = sel["events"]
        pdf.add(f"Event level (test): {e['detected']}/{e['events']} threshold-crossing episodes warned in advance; "
                f"median lead time {e['median_lead_s']} s; false alarms per patient-day {e['false_alarms_per_patient_day']}.")
    pdf.add("")
    pdf.add("Limitations", "h2")
    pdf.add("All figures are computed by ml/train.py on synthetic data split by patient. They measure how well the model "
            "recovers the generator's patterns; they say nothing about performance on real patients. " + DISCLAIMER, "small")
    return pdf.render()
