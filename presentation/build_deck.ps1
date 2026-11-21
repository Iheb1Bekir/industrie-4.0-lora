# Builds presentation/RPM_LoRa_presentation.pptx (+ .pdf) natively inside Microsoft PowerPoint (COM automation):
# theme colours and fonts, editable shapes, native tables and native charts with embedded data, speaker notes, sections.
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File presentation\build_deck.ps1 [renderDir]
# Needs Microsoft PowerPoint and Excel (chart data). Numbers come from report/figures/data and ml/models (see notes).
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$assets = Join-Path $here 'assets'
$data = Join-Path $repo 'report\figures\data'
$renderDir = if ($args.Count -gt 0) { $args[0] } else { Join-Path $here 'renders' }
New-Item -ItemType Directory -Force -Path $renderDir | Out-Null
$pptxPath = Join-Path $here 'RPM_LoRa_presentation.pptx'
$pdfPath = Join-Path $here 'RPM_LoRa_presentation.pdf'
$INV = [Globalization.CultureInfo]::InvariantCulture

# ---------------------------------------------------------------- theme (indices of MsoThemeColorIndex)
$INK = 13; $WHITE = 14; $DARK = 15; $LIGHT = 16; $TEAL = 5; $CORAL = 6; $GREEN = 7; $AMBER = 8; $SLATE = 9; $AQUA = 10
$PALETTE = [ordered]@{ 1 = '1B2A33'; 2 = 'FFFFFF'; 3 = '0B2E3A'; 4 = 'EEF5F5'; 5 = '0E7C86'; 6 = 'E4572E'; 7 = '2BA84A'; 8 = 'F2A541'; 9 = '5B6B73'; 10 = '7FD1C7'; 11 = '0E7C86'; 12 = '5B6B73' }
$FOOTER = 'LoRa remote patient monitoring · research prototype, not a medical device'
function BGR([string]$hex) { return [Convert]::ToInt32($hex.Substring(0, 2), 16) + 256 * [Convert]::ToInt32($hex.Substring(2, 2), 16) + 65536 * [Convert]::ToInt32($hex.Substring(4, 2), 16) }
function Num([string]$s) { if ($s -eq 'nan') { return $null } return [double]::Parse($s, $INV) }

# ---------------------------------------------------------------- drawing helpers
function T($slide, [string]$text, [double]$l, [double]$t, [double]$w, [double]$h, [hashtable]$o = @{}) {
    $s = $slide.Shapes.AddTextbox(1, $l, $t, $w, $h)
    $tf = $s.TextFrame
    $tf.WordWrap = -1; $tf.AutoSize = 0
    $tf.MarginLeft = 0; $tf.MarginRight = 0; $tf.MarginTop = 0; $tf.MarginBottom = 0
    $tf.VerticalAnchor = $(if ($o.anchor) { $o.anchor } else { 1 })
    $tr = $tf.TextRange
    $tr.Text = $text
    $tr.Font.Name = $(if ($o.font) { $o.font } elseif ($o.head) { '+mj-lt' } else { '+mn-lt' })
    $tr.Font.Size = [single]$(if ($o.size) { $o.size } else { 16 })
    $tr.Font.Bold = $(if ($o.bold) { -1 } else { 0 })
    $tr.Font.Italic = $(if ($o.italic) { -1 } else { 0 })
    $tr.Font.Color.ObjectThemeColor = $(if ($o.color) { $o.color } else { $INK })
    $tr.ParagraphFormat.Alignment = $(if ($o.align) { $o.align } else { 1 })
    $tr.ParagraphFormat.LineRuleAfter = 0
    $tr.ParagraphFormat.SpaceAfter = [single]$(if ($o.after) { $o.after } else { 0 })
    if ($o.spacing) { $s.TextFrame2.TextRange.Font.Spacing = $o.spacing }
    if ($o.name) { $s.Name = $o.name }
    return $s
}
# paragraphs = array of @(lead, text); lead printed bold
function Paras($slide, $items, [double]$l, [double]$t, [double]$w, [double]$h, [hashtable]$o = @{}) {
    $text = ($items | ForEach-Object { $_[0] + $_[1] }) -join "`r"
    if (-not $o.after) { $o.after = 8 }
    $s = T $slide $text $l $t $w $h $o
    $tr = $s.TextFrame.TextRange
    for ($i = 1; $i -le $items.Count; $i++) {
        $p = $tr.Paragraphs($i)
        $lead = [string]$items[$i - 1][0]
        if ($lead.Length -gt 0) {
            $p.Characters(1, $lead.Length).Font.Bold = -1
            if ($o.leadColor) { $p.Characters(1, $lead.Length).Font.Color.ObjectThemeColor = $o.leadColor }
        }
        if ($o.bullet) {
            $p.ParagraphFormat.Bullet.Visible = -1
            $p.ParagraphFormat.Bullet.Character = 8226
            $p.ParagraphFormat.Bullet.Font.Color.ObjectThemeColor = $(if ($o.bulletColor) { $o.bulletColor } else { $TEAL })
        }
    }
    if ($o.bullet) { $s.TextFrame.Ruler.Levels(1).FirstMargin = [single]0; $s.TextFrame.Ruler.Levels(1).LeftMargin = [single]15 }
    return $s
}
function Box($slide, [double]$l, [double]$t, [double]$w, [double]$h, [int]$fill = 16, [hashtable]$o = @{}) {
    $s = $slide.Shapes.AddShape(5, $l, $t, $w, $h)
    $s.Adjustments.Item(1) = [single][Math]::Min(0.5, $(if ($o.radius) { $o.radius } else { 9 }) / [Math]::Min($w, $h))
    $s.Fill.Solid(); $s.Fill.ForeColor.ObjectThemeColor = $fill
    if ($o.bright) { $s.Fill.ForeColor.Brightness = [single]$o.bright }
    if ($o.line) {
        $s.Line.Visible = -1; $s.Line.ForeColor.ObjectThemeColor = $o.line; $s.Line.Weight = [single]$(if ($o.weight) { $o.weight } else { 1.25 })
        if ($o.dash) { $s.Line.DashStyle = 4 }
    } else { $s.Line.Visible = 0 }
    if ($o.shadow) { $s.Shadow.Visible = -1; $s.Shadow.Blur = [single]12; $s.Shadow.OffsetX = [single]0; $s.Shadow.OffsetY = [single]3; $s.Shadow.Transparency = [single]0.84; $s.Shadow.ForeColor.RGB = 0 }
    else { $s.Shadow.Visible = 0 }
    if ($o.name) { $s.Name = $o.name }
    return $s
}
function Shp($slide, [int]$type, [double]$l, [double]$t, [double]$w, [double]$h, [int]$fill) {
    $s = $slide.Shapes.AddShape($type, $l, $t, $w, $h)
    $s.Fill.Solid(); $s.Fill.ForeColor.ObjectThemeColor = $fill; $s.Line.Visible = 0; $s.Shadow.Visible = 0
    return $s
}
# icon = white pictogram on a coloured circle (native AutoShapes)
function Icon($slide, [string]$kind, [double]$cx, [double]$cy, [double]$d, [int]$color) {
    $null = Shp $slide 9 ($cx - $d / 2) ($cy - $d / 2) $d $d $color
    $k = $d * 0.5
    switch ($kind) {
        'heart' { $null = Shp $slide 21 ($cx - $k / 2) ($cy - $k * 0.42) $k ($k * 0.88) $WHITE }
        'bolt' { $null = Shp $slide 22 ($cx - $k * 0.45) ($cy - $k / 2) ($k * 0.9) $k $WHITE }
        'db' { $null = Shp $slide 13 ($cx - $k * 0.38) ($cy - $k / 2) ($k * 0.76) $k $WHITE }
        'gear' { $null = Shp $slide 172 ($cx - $k / 2) ($cy - $k / 2) $k $k $WHITE }
        'lock' {
            $a = Shp $slide 20 ($cx - $k * 0.34) ($cy - $k * 0.62) ($k * 0.68) ($k * 0.68) $WHITE
            $a.Adjustments.Item(1) = [single]180; $a.Adjustments.Item(2) = [single]0; $a.Adjustments.Item(3) = [single]0.2
            $b = Shp $slide 5 ($cx - $k * 0.45) ($cy - $k * 0.22) ($k * 0.9) ($k * 0.7) $WHITE
            $b.Adjustments.Item(1) = [single]0.15
        }
        'chart' {
            $bw = $k * 0.24
            $null = Shp $slide 1 ($cx - $k * 0.45) ($cy + $k * 0.05) $bw ($k * 0.45) $WHITE
            $null = Shp $slide 1 ($cx - $bw / 2) ($cy - $k * 0.2) $bw ($k * 0.7) $WHITE
            $null = Shp $slide 1 ($cx + $k * 0.45 - $bw) ($cy - $k * 0.5) $bw ($k * 1.0) $WHITE
        }
        'screen' {
            $null = Shp $slide 5 ($cx - $k / 2) ($cy - $k * 0.45) $k ($k * 0.66) $WHITE
            $null = Shp $slide 1 ($cx - $k * 0.08) ($cy + $k * 0.2) ($k * 0.16) ($k * 0.18) $WHITE
            $null = Shp $slide 1 ($cx - $k * 0.3) ($cy + $k * 0.36) ($k * 0.6) ($k * 0.1) $WHITE
        }
        'warn' {
            $null = Shp $slide 7 ($cx - $k / 2) ($cy - $k / 2) $k ($k * 0.9) $WHITE
            $null = T $slide '!' ($cx - $k / 2) ($cy - $k * 0.28) $k ($k * 0.7) @{ size = [Math]::Round($k * 0.75); bold = $true; color = $color; align = 2 }
        }
        'clock' {
            $null = Shp $slide 18 ($cx - $k / 2) ($cy - $k / 2) $k $k $WHITE
            $null = Shp $slide 1 ($cx - $k * 0.04) ($cy - $k * 0.32) ($k * 0.08) ($k * 0.34) $WHITE
            $null = Shp $slide 1 ($cx - $k * 0.04) ($cy - $k * 0.04) ($k * 0.3) ($k * 0.08) $WHITE
        }
        'people' {
            $null = Shp $slide 9 ($cx - $k * 0.18) ($cy - $k * 0.5) ($k * 0.36) ($k * 0.36) $WHITE
            $null = Shp $slide 5 ($cx - $k * 0.42) ($cy - $k * 0.06) ($k * 0.84) ($k * 0.52) $WHITE
        }
        'wave' {
            $f = $slide.Shapes.BuildFreeform(1, $cx - $k * 0.55, $cy)
            $pts = @(@(-0.25, 0), @(-0.12, -0.45), @(0.02, 0.45), @(0.14, -0.2), @(0.22, 0), @(0.55, 0))
            foreach ($p in $pts) { $f.AddNodes(0, 1, $cx + $k * $p[0], $cy + $k * $p[1]) }
            $w = $f.ConvertToShape(); $w.Fill.Visible = 0; $w.Line.ForeColor.ObjectThemeColor = $WHITE; $w.Line.Weight = [single][Math]::Max(1.5, $d / 18)
        }
    }
}
function Chip($slide, [string]$text, [double]$l, [double]$t, [int]$fill, [int]$fg = 14, [double]$size = 11) {
    $s = $slide.Shapes.AddShape(5, $l, $t, 40, $size + 9)
    $s.Adjustments.Item(1) = [single]0.5
    $s.Fill.Solid(); $s.Fill.ForeColor.ObjectThemeColor = $fill; $s.Line.Visible = 0; $s.Shadow.Visible = 0
    $tf = $s.TextFrame; $tf.MarginLeft = 7; $tf.MarginRight = 7; $tf.MarginTop = 1; $tf.MarginBottom = 1
    $tf.WordWrap = 0; $tf.AutoSize = 1; $tf.VerticalAnchor = 3
    $tr = $tf.TextRange; $tr.Text = $text; $tr.Font.Name = '+mn-lt'; $tr.Font.Size = [single]$size; $tr.Font.Bold = -1
    $tr.Font.Color.ObjectThemeColor = $fg; $tr.ParagraphFormat.Alignment = 2
    $s.Left = [single]$l; $s.Top = [single]$t
    return $s
}
function Arrow($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, [int]$color = 5, [double]$weight = 2, [switch]$dash) {
    $c = $slide.Shapes.AddConnector(1, $x1, $y1, $x2, $y2)
    $c.Line.ForeColor.ObjectThemeColor = $color; $c.Line.Weight = [single]$weight; $c.Line.EndArrowheadStyle = 2
    if ($dash) { $c.Line.DashStyle = 4 }
    return $c
}
function Line($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, [int]$color = 9, [double]$weight = 1) {
    $c = $slide.Shapes.AddLine($x1, $y1, $x2, $y2); $c.Line.ForeColor.ObjectThemeColor = $color; $c.Line.Weight = [single]$weight; return $c
}
function Pic($slide, [string]$file, [double]$l, [double]$t, [double]$w, [double]$h = 0, [switch]$frame) {
    $img = [System.Drawing.Image]::FromFile($file); $ar = $img.Height / $img.Width; $img.Dispose()
    if ($h -le 0) { $h = $w * $ar } elseif ($w -le 0) { $w = $h / $ar }
    $p = $slide.Shapes.AddPicture($file, 0, -1, $l, $t, $w, $h)
    if ($frame) {
        $p.AutoShapeType = 5; $p.Adjustments.Item(1) = [single]0.035
        $p.Line.Visible = -1; $p.Line.ForeColor.RGB = (BGR 'D5E2E4'); $p.Line.Weight = [single]0.75
        $p.Shadow.Visible = -1; $p.Shadow.Blur = [single]14; $p.Shadow.OffsetX = [single]0; $p.Shadow.OffsetY = [single]3; $p.Shadow.Transparency = [single]0.8; $p.Shadow.ForeColor.RGB = 0
    }
    return $p
}
function Stat($slide, [string]$big, [string]$label, [double]$l, [double]$t, [double]$w, [int]$color, [double]$bigSize = 44, [double]$labelSize = 14) {
    $null = T $slide $big $l $t $w ($bigSize * 1.15) @{ size = $bigSize; bold = $true; head = $true; color = $color }
    $null = T $slide $label $l ($t + $bigSize * 1.18) $w ($labelSize * 3.2) @{ size = $labelSize; color = $SLATE }
}
function Notes($slide, [string]$text) { $slide.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = $text }
function Pulse($slide, [double]$y, [int]$color, [double]$x0 = 0, [double]$x1 = 960, [double]$peak = 600) {
    $f = $slide.Shapes.BuildFreeform(1, $x0, $y)
    $pts = @(@(-110, 0), @(-88, -12), @(-70, 0), @(-40, 0), @(-24, -62), @(-6, 48), @(12, -22), @(26, 0), @(70, 0), @(88, -9), @(104, 0))
    foreach ($p in $pts) { $f.AddNodes(0, 1, $peak + $p[0], $y + $p[1]) }
    $f.AddNodes(0, 1, $x1, $y)
    $s = $f.ConvertToShape(); $s.Fill.Visible = 0; $s.Line.ForeColor.ObjectThemeColor = $color; $s.Line.Weight = [single]2.5
    $s.Name = 'Pulse line'
    return $s
}

# ---------------------------------------------------------------- native charts
function Fill-ChartData($ch, $rows) {
    $wb = $null; $ws = $null
    for ($i = 0; $i -lt 60 -and -not $ws; $i++) {
        try { $ch.ChartData.Activate() } catch {}
        Start-Sleep -Milliseconds 250
        try { $wb = $ch.ChartData.Workbook; if ($wb) { $ws = $wb.Worksheets.Item(1) } } catch {}
    }
    if (-not $ws) { throw 'chart data workbook not available' }
    try { $wb.Application.WindowState = -4140 } catch {}
    $null = $ws.UsedRange.ClearContents()
    $r = $rows.Count; $c = $rows[0].Count
    $arr = New-Object 'object[,]' $r, $c
    for ($i = 0; $i -lt $r; $i++) { for ($j = 0; $j -lt $c; $j++) { $arr[$i, $j] = $rows[$i][$j] } }
    $endCol = [string][char](64 + $c)
    $ws.Range("A1:$endCol$r").Value2 = $arr
    $ch.SetSourceData("='" + $ws.Name + "'!`$A`$1:`$$endCol`$$r", 2)
    $wb.Close()
}
function New-Chart($slide, [int]$type, [double]$l, [double]$t, [double]$w, [double]$h, $rows) {
    $cs = $slide.Shapes.AddChart2(-1, $type, $l, $t, $w, $h, $true)
    $ch = $cs.Chart
    Fill-ChartData $ch $rows
    $ch.HasTitle = $false
    $tf = $ch.ChartArea.Format.TextFrame2.TextRange.Font
    $tf.Size = 12; $tf.Fill.ForeColor.RGB = (BGR '5B6B73')
    try { $tf.Name = '+mn-lt' } catch {}
    $ch.ChartArea.Format.Fill.Visible = 0; $ch.ChartArea.Format.Line.Visible = 0
    try { $ch.PlotArea.Format.Fill.Visible = 0 } catch {}
    $va = $ch.Axes(2)
    $va.HasMajorGridlines = $true; $va.MajorGridlines.Format.Line.ForeColor.RGB = (BGR 'DCE6E8'); $va.MajorGridlines.Format.Line.Weight = [single]0.75
    $va.Format.Line.Visible = 0
    $ca = $ch.Axes(1); $ca.Format.Line.ForeColor.RGB = (BGR 'AFC0C4')
    $cs.Name = 'Chart'
    return $cs
}
function Label-Points($ser, $labels, [int]$position, [int]$color = 13, [double]$size = 12, [switch]$bold) {
    $ser.HasDataLabels = $true
    for ($k = 1; $k -le $labels.Count; $k++) {
        $dl = $ser.Points($k).DataLabel
        $dl.Text = [string]$labels[$k - 1]
        if ($position) { $dl.Position = $position }
        $f = $dl.Format.TextFrame2.TextRange.Font
        $f.Size = $size; $f.Fill.ForeColor.ObjectThemeColor = $color
        if ($bold) { $f.Bold = -1 }
    }
}

# ---------------------------------------------------------------- data read from the repository
$delay = Import-Csv -Delimiter ' ' -Path (Join-Path $data 'sim_delay_summary.dat')   # hop n sim_ms analytic34_ms
$traj = Import-Csv -Delimiter ' ' -Path (Join-Path $data 'example_patient.dat')        # tmin hr spo2 temp score

# ---------------------------------------------------------------- presentation, theme, layouts
foreach ($p in @($pptxPath, $pdfPath)) { if (Test-Path $p) { Remove-Item $p -Force } }
$pp = New-Object -ComObject PowerPoint.Application
try {
    $pres = $pp.Presentations.Add(-1)                 # a window is required for native chart data
    try { $pp.WindowState = 2 } catch {}
    $pres.PageSetup.SlideWidth = 960; $pres.PageSetup.SlideHeight = 540
    $master = $pres.SlideMaster
    $theme = $master.Theme
    foreach ($e in $PALETTE.GetEnumerator()) { $theme.ThemeColorScheme.Colors([int]$e.Key).RGB = (BGR $e.Value) }
    $theme.ThemeFontScheme.MajorFont.Item(1).Name = 'Cambria'
    $theme.ThemeFontScheme.MinorFont.Item(1).Name = 'Calibri'
    $master.Background.Fill.Solid(); $master.Background.Fill.ForeColor.ObjectThemeColor = $WHITE
    $layoutContent = $master.CustomLayouts.Item(6)    # "Title Only"
    $layoutBlank = $master.CustomLayouts.Item(7)      # "Blank"
    $layoutContent.Name = 'RPM content'
    $toDelete = @()
    foreach ($sh in $layoutContent.Shapes) {
        if ($sh.Type -ne 14) { continue }
        switch ($sh.PlaceholderFormat.Type) {
            1 {
                $sh.Left = 36; $sh.Top = 20; $sh.Width = 888; $sh.Height = 58
                $sh.TextFrame.VerticalAnchor = 3; $sh.TextFrame.MarginLeft = 0; $sh.TextFrame.MarginRight = 0
                $r = $sh.TextFrame.TextRange; $r.Font.Size = [single]30; $r.Font.Bold = -1; $r.Font.Color.ObjectThemeColor = $DARK; $r.ParagraphFormat.Alignment = 1
            }
            15 { $sh.Left = 36; $sh.Top = 508; $sh.Width = 640; $sh.Height = 18; $sh.TextFrame.MarginLeft = 0; $r = $sh.TextFrame.TextRange; $r.Font.Size = [single]10; $r.Font.Color.ObjectThemeColor = $SLATE; $r.ParagraphFormat.Alignment = 1 }
            13 { $sh.Left = 824; $sh.Top = 508; $sh.Width = 100; $sh.Height = 18; $sh.TextFrame.MarginRight = 0; $r = $sh.TextFrame.TextRange; $r.Font.Size = [single]10; $r.Font.Color.ObjectThemeColor = $SLATE; $r.ParagraphFormat.Alignment = 3 }
            16 { $toDelete += $sh }
        }
    }
    foreach ($sh in $toDelete) { $sh.Delete() }

    $script:n = 0
    function New-Content([string]$title) {
        $script:n++
        $s = $pres.Slides.AddSlide($script:n, $layoutContent)
        $s.Shapes.Placeholders.Item(1).TextFrame.TextRange.Text = $title
        $s.HeadersFooters.Footer.Visible = -1; $s.HeadersFooters.Footer.Text = $FOOTER
        $s.HeadersFooters.SlideNumber.Visible = -1
        Write-Host ("slide {0}: {1}" -f $script:n, $title)
        return $s
    }
    function New-Dark() {
        $script:n++
        $s = $pres.Slides.AddSlide($script:n, $layoutBlank)
        $s.FollowMasterBackground = 0; $s.Background.Fill.Solid(); $s.Background.Fill.ForeColor.ObjectThemeColor = $DARK
        Write-Host ("slide {0}: dark" -f $script:n)
        return $s
    }

    # ============================================================ 1 Title
    $s = New-Dark
    $null = Pulse $s 452 $AQUA 0 960 640
    $null = T $s 'INDUSTRY 4.0  ·  IoT FOR HEALTHCARE' 60 92 820 20 @{ size = 14; bold = $true; color = $AQUA; spacing = 2 }
    $null = T $s 'LoRa-Enabled Remote Patient Monitoring' 60 122 840 120 @{ size = 46; bold = $true; head = $true; color = $WHITE }
    $null = T $s 'Raspberry Pi 5 edge processing  ·  OMNeT++/FLoRa network simulation  ·  early-warning analytics' 60 250 820 56 @{ size = 20; color = $LIGHT }
    $null = T $s 'Iheb Bekir' 60 326 600 26 @{ size = 20; bold = $true; color = $WHITE }
    $null = T $s 'Industry 4.0 LoRa remote patient monitoring project  ·  November 2026' 60 354 700 22 @{ size = 14; color = $AQUA }
    $null = Chip $s 'Research prototype, not a medical device' 60 486 $AMBER $DARK 12
    Notes $s "Good morning. This talk presents a remote patient monitoring prototype built on LoRa radio, with a Raspberry Pi 5 as edge gateway, an OMNeT++/FLoRa network simulation and an early-warning model.`rThroughout the talk I separate what is tested in software, what is simulated, what was observed on the bench and what is still pending. All vital-sign values shown are synthetic or simulated: no patient data were used, and the system is a research prototype, not a medical device."

    # ============================================================ 2 Problem
    $s = New-Content 'Many patients, tiny frames, and data that must be trusted'
    $cards = @(
        @('heart', $CORAL, 'Vital signs change in minutes', 'Heart rate, SpO₂, temperature and falls for tens of patients, one sample every 30 s.'),
        @('bolt', $TEAL, 'The radio must be frugal', 'Battery nodes behind walls, no Wi-Fi or cellular dependency, frames of a few tens of bytes.'),
        @('lock', $GREEN, 'Every frame must be trusted', 'A forged or replayed vital-sign frame is a safety issue, not only a privacy one.')
    )
    for ($i = 0; $i -lt 3; $i++) {
        $x = 36 + $i * 304
        $null = Box $s $x 104 280 262 $LIGHT
        Icon $s $cards[$i][0] ($x + 52) 156 60 $cards[$i][1]
        $null = T $s $cards[$i][2] ($x + 24) 202 236 54 @{ size = 20; bold = $true; head = $true; color = $DARK }
        $null = T $s $cards[$i][3] ($x + 24) 262 236 96 @{ size = 16 }
    }
    $null = Box $s 36 388 888 96 $DARK
    $null = Chip $s 'Approach' 60 404 $AQUA $DARK 12
    $null = T $s 'Raw LoRa with a 34-byte authenticated frame and application-level relays, processed on a Raspberry Pi 5 edge gateway: no LoRaWAN network server, works offline, keeps patient data local.' 60 432 840 44 @{ size = 16; color = $WHITE }
    Notes $s "The engineering problem: follow tens of patients whose vital signs can change within minutes. Each observation is tiny, but the link must be low-power, reach through walls, tolerate losses and stay trustworthy, because a forged or replayed vital-sign frame is a safety problem.`rLoRa gives roughly minus 124 dBm sensitivity at SF7 and long range at milliwatt power, at the price of low data rate, duty-cycle limits and collisions. I chose raw LoRa with a custom authenticated frame instead of LoRaWAN, so a single gateway works offline without a network server."

    # ============================================================ 3 Summary
    $s = New-Content 'What was built, and what the evidence shows'
    $stats = @(
        @('Tested', $GREEN, $WHITE, '233/233', $GREEN, 'automated software tests pass, including the C++ vs Python frame check'),
        @('Simulated', $TEAL, $WHITE, '98.75 %', $TEAL, 'frames delivered in OMNeT++/FLoRa (79 of 80), 20 patients and 3 relays'),
        @('Analytical', $SLATE, $WHITE, '77 ms', $DARK, 'time on air of the 34-byte frame at SF7, 0.26 % duty cycle at 30 s'),
        @('Synthetic data', $AQUA, $DARK, '92/97', $CORAL, 'threshold-crossing episodes flagged in advance, median lead 8.5 min')
    )
    for ($i = 0; $i -lt 4; $i++) {
        $x = 36 + $i * 226
        $null = Box $s $x 104 210 236 $WHITE @{ shadow = $true; line = $LIGHT; weight = 1 }
        $null = Chip $s $stats[$i][0] ($x + 18) 122 $stats[$i][1] $stats[$i][2] 11
        $null = T $s $stats[$i][3] ($x + 18) 158 180 60 @{ size = 44; bold = $true; head = $true; color = $stats[$i][4] }
        $null = T $s $stats[$i][5] ($x + 18) 226 178 100 @{ size = 15; color = $INK }
    }
    $null = Box $s 36 360 888 124 $LIGHT
    $null = Chip $s 'Bench' 60 378 $DARK $WHITE 11
    $null = T $s 'A point-to-point LoRa link with a Heltec V3 receiver operates; the Raspberry Pi 5 UART link is configured but reception is not yet confirmed.' 150 376 750 44 @{ size = 15 }
    $null = Chip $s 'Pending' 60 432 $AMBER $DARK 11
    $null = T $s 'Physiological sensor node, ESP32 flashing, UART/SPI reception, deployment on the Pi 5, payload encryption and TLS.' 150 430 750 44 @{ size = 15 }
    Notes $s "This is the whole talk on one slide, organised by type of evidence. Tested: all 233 automated software tests pass, including a check that the C++ firmware encoder produces exactly the same bytes as the Python reference. Simulated: 79 of 80 frames delivered in the OMNeT++ model. Analytical: the frame needs about 77 milliseconds on air. Model: on a synthetic test set, 92 of 97 threshold-crossing episodes were flagged in advance.`rOn the bench a LoRa link works. Still pending: the physiological sensor node, radio reception on the Pi, deployment on the Pi, and encryption."

    # ============================================================ 4 Architecture
    $s = New-Content 'Three tiers from bedside sensor to clinician screen'
    $null = Box $s 36 108 196 248 $LIGHT @{ line = $AMBER; dash = $true; weight = 1.5 }
    Icon $s 'heart' 70 142 44 $CORAL
    $null = T $s 'Patient node' 100 130 130 26 @{ size = 18; bold = $true; head = $true; color = $DARK }
    $null = Paras $s @(@('', 'ESP32-S3 + LoRa radio'), @('', 'MAX30102 · DS18B20 · MPU-6050'), @('', 'sample every 30 s'), @('', '34-byte frame + HMAC tag')) 52 178 168 170 @{ size = 14; bullet = $true; after = 6 }
    $null = Box $s 262 108 152 92 $LIGHT
    $null = T $s 'Heltec V3 receiver' 274 120 130 22 @{ size = 15; bold = $true; color = $DARK }
    $null = T $s 'bench, UART to the Pi' 274 146 130 40 @{ size = 13; color = $SLATE }
    $null = Box $s 262 264 152 92 $LIGHT @{ line = $AMBER; dash = $true; weight = 1.5 }
    $null = T $s 'Relay node' 274 276 130 22 @{ size = 15; bold = $true; color = $DARK }
    $null = T $s 'hopCount + 1, at most 4 hops' 274 302 130 40 @{ size = 13; color = $SLATE }
    $null = Arrow $s 232 154 262 154 $GREEN 2 -dash
    $null = Arrow $s 232 310 262 310 $GREEN 2
    $null = Arrow $s 232 232 444 232 $GREEN 2
    $null = T $s 'raw LoRa SF7 · 125 kHz' 252 214 170 16 @{ size = 11; color = $GREEN; bold = $true }
    $null = Arrow $s 414 154 444 176 $GREEN 2 -dash
    $null = Arrow $s 414 310 444 286 $GREEN 2
    $null = Box $s 444 100 480 266 $WHITE @{ line = $DARK; weight = 1.25; shadow = $true }
    $null = T $s 'Raspberry Pi 5 edge gateway' 462 108 300 22 @{ size = 15; bold = $true; color = $DARK }
    $gw = @(
        @(462, 'Radio input', 'SPI SX127x or UART'), @(614, 'Spool', 'store and forward'), @(766, 'Ingestion', 'CRC, key, HMAC, replay, plausibility'),
        @(766, 'SQLite stores', 'system, hardware, simulation'), @(614, 'Alerts + ML', 'thresholds, early warning'), @(462, 'API + SSE', 'roles, CSRF, audit chain')
    )
    for ($i = 0; $i -lt 6; $i++) {
        $y = $(if ($i -lt 3) { 140 } else { 260 })
        $null = Box $s $gw[$i][0] $y 142 92 $TEAL
        $null = T $s $gw[$i][1] ($gw[$i][0] + 12) ($y + 12) 120 22 @{ size = 15; bold = $true; color = $WHITE }
        $null = T $s $gw[$i][2] ($gw[$i][0] + 12) ($y + 38) 122 48 @{ size = 12; color = $LIGHT }
    }
    $null = Arrow $s 604 186 614 186 $DARK 1.75
    $null = Arrow $s 756 186 766 186 $DARK 1.75
    $null = Arrow $s 837 232 837 260 $DARK 1.75
    $null = Arrow $s 766 306 756 306 $DARK 1.75
    $null = Arrow $s 614 306 604 306 $DARK 1.75
    $null = Box $s 444 392 220 92 $LIGHT
    Icon $s 'screen' 476 438 40 $DARK
    $null = T $s 'Web dashboard' 506 408 150 22 @{ size = 15; bold = $true; color = $DARK }
    $null = T $s 'doctor · assistant · caregiver' 506 432 152 40 @{ size = 13; color = $SLATE }
    $null = Arrow $s 533 352 533 392 $DARK 1.75
    $null = Box $s 690 392 234 92 $LIGHT @{ line = $SLATE; dash = $true; weight = 1 }
    $null = T $s 'Simulation sources' 704 404 210 22 @{ size = 15; bold = $true; color = $SLATE }
    $null = T $s 'web engine (virtual nodes ≥ 60001) and OMNeT++ results, kept in the simulation store' 704 428 210 52 @{ size = 12; color = $SLATE }
    $null = Arrow $s 837 392 837 352 $SLATE 1.5 -dash
    $null = Chip $s 'dashed = hardware validation pending' 36 380 $WHITE $SLATE 11
    $null = T $s 'Physical and simulated data never share a table.' 36 412 380 60 @{ size = 14; italic = $true; color = $SLATE }
    Notes $s "Three tiers. Patient nodes sample every 30 seconds and send directly, or through up to four relays when out of range. Dashed outlines mark hardware whose validation is pending.`rThe Raspberry Pi 5 gateway receives frames from an SPI radio driver or, on the bench, from a Heltec receiver over UART. A store-and-forward spool decouples reception from the platform. Ingestion checks the CRC, looks up the device key, verifies the HMAC tag, applies a replay window and plausibility limits, then stores data. Alerts and the model feed a role-based dashboard over server-sent events. Simulated data use a separate store."

    # ============================================================ 5 Hardware
    $s = New-Content 'Bench prototype: the LoRa link works, sensors come next'
    $null = Pic $s (Join-Path $assets 'bench_photo.jpg') 36 100 480 -frame
    $null = T $s 'Bench: Heltec WiFi LoRa 32 V3 receiver (OLED: packet 161, 23.7 °C, 64.2 % RH, RSSI, SNR), DHT-type sensor, status LEDs and the Raspberry Pi 5.' 36 392 480 50 @{ size = 12; color = $SLATE; italic = $true }
    $rows = @(
        @('bolt', $TEAL, 'ESP32-S3', 'patient and relay MCU, SHA/AES accelerators', 'not flashed', $AMBER, $DARK),
        @('bolt', $TEAL, 'SX1276/78 or SX1262', 'raw LoRa PHY, SF7-12, up to +22 dBm', 'pending', $AMBER, $DARK),
        @('screen', $GREEN, 'Heltec WiFi LoRa 32 V3', 'ESP32-S3 + SX1262 + OLED receiver', 'operating', $GREEN, $WHITE),
        @('heart', $CORAL, 'MAX30102 · DS18B20 · MPU-6050', 'HR/SpO₂, temperature, fall IMU', 'pending', $AMBER, $DARK),
        @('gear', $DARK, 'Raspberry Pi 5', '4x Cortex-A76, UART0 + SPI0 header', 'UART configured', $TEAL, $WHITE)
    )
    for ($i = 0; $i -lt 5; $i++) {
        $y = 104 + $i * 66
        $null = Box $s 540 $y 384 56 $LIGHT
        Icon $s $rows[$i][0] 566 ($y + 28) 32 $rows[$i][1]
        $null = T $s $rows[$i][2] 592 ($y + 8) 220 20 @{ size = 15; bold = $true; color = $DARK }
        $null = T $s $rows[$i][3] 592 ($y + 30) 230 20 @{ size = 12; color = $SLATE }
        $c = Chip $s $rows[$i][4] 820 ($y + 17) $rows[$i][5] $rows[$i][6] 11
        $c.Left = 912 - $c.Width
    }
    $null = Box $s 540 444 384 40 $CORAL @{ bright = 0.82 }
    $null = T $s 'All vital-sign values in this talk are synthetic or simulated.' 556 452 360 26 @{ size = 14; bold = $true; color = $CORAL; anchor = 3 }
    Notes $s "On the bench, the Heltec WiFi LoRa 32 V3 on the left receives LoRa packets; its display shows the packet counter, temperature, humidity, RSSI and SNR, so the point-to-point link works. That bench firmware sends temperature and humidity, not yet the physiological frame.`rThe patient firmware supports the MAX30102 pulse oximeter, the DS18B20 thermometer and the MPU-6050 for falls, but this sensor chain has not been assembled, so every vital sign in this talk is synthetic or simulated. The ESP32-S3 was chosen for its hardware SHA engine, the Pi 5 because the gateway runs a database, a web server and a model at once."

    # ============================================================ 6 Frame
    $s = New-Content 'A 34-byte frame carries the whole measurement, signed'
    $cw = 46
    $row1 = @(@('ver', 1, $LIGHT, 0), @('type', 1, $LIGHT, 0), @('patientId', 2, $TEAL, 0.75), @('sourceId', 2, $TEAL, 0.75), @('destId', 2, $TEAL, 0.75), @('seqNo (u32)', 4, $GREEN, 0.75), @('timestamp (u32)', 4, $GREEN, 0.75))
    $row2 = @(@('HR', 1, $CORAL, 0.72), @('SpO₂', 1, $CORAL, 0.72), @('temp', 2, $CORAL, 0.72), @('flags', 1, $AMBER, 0.6), @('AL|RM', 1, $AMBER, 0.6), @('HC|MH', 1, $AMBER, 0.6), @('batt', 1, $AMBER, 0.6), @('HMAC-SHA256 tag (64 bit)', 8, $DARK, 0), @('CRC-16', 2, $SLATE, 0.55))
    $x0 = 66
    foreach ($spec in @(@($row1, 118, 0), @($row2, 200, 16))) {
        $x = $x0; $off = $spec[2]
        foreach ($f in $spec[0]) {
            $w = $f[1] * $cw
            $b = Box $s $x $spec[1] ($w - 2) 44 $f[2] @{ radius = 4 }
            if ($f[3] -ne 0) { $b.Fill.ForeColor.Brightness = [single]$f[3] }
            $fg = $(if ($f[2] -eq $DARK -or ($f[2] -eq $SLATE -and $f[3] -eq 0)) { $WHITE } else { $DARK })
            $null = T $s $f[0] $x ($spec[1] + 4) ($w - 2) 36 @{ size = $(if ($f[1] -eq 1) { 11 } else { 13 }); bold = $true; color = $fg; align = 2; anchor = 3 }
            $null = T $s ([string]$off) ($x - 6) ($spec[1] - 15) 20 12 @{ size = 9; color = $SLATE }
            $x += $w; $off += $f[1]
        }
        $null = T $s ([string]$off) ($x - 6) ($spec[1] - 15) 20 12 @{ size = 9; color = $SLATE }
    }
    $null = T $s 'over bytes 0-23, hopCount nibble zeroed' (66 + 8 * $cw) 250 (8 * $cw) 16 @{ size = 11; color = $SLATE; align = 2 }
    $null = T $s 'per hop' (66 + 16 * $cw) 250 (2 * $cw) 16 @{ size = 11; color = $SLATE; align = 2 }
    $null = T $s 'AL|RM: alertLevel | routingMode   ·   HC|MH: hopCount | maxHopCount' 66 270 600 16 @{ size = 11; color = $SLATE }
    $feat = @(
        @('lock', $GREEN, 'Authenticated', 'Per-device key; the tag covers the first 24 bytes, so relays need no key and cannot change other fields unnoticed.'),
        @('bolt', $TEAL, 'Relay-friendly', 'Relays check the CRC, drop duplicates, enforce at most 4 hops and increment hopCount.'),
        @('clock', $AMBER, 'Replay-safe', 'The 32-bit seqNo survives reboots; the gateway keeps a 62-frame replay window per device.')
    )
    for ($i = 0; $i -lt 3; $i++) {
        $x = 36 + $i * 304
        $null = Box $s $x 304 280 180 $LIGHT
        Icon $s $feat[$i][0] ($x + 40) 344 46 $feat[$i][1]
        $null = T $s $feat[$i][2] ($x + 76) 332 190 26 @{ size = 18; bold = $true; head = $true; color = $DARK }
        $null = T $s $feat[$i][3] ($x + 22) 378 240 100 @{ size = 15 }
    }
    Notes $s "The version 2 frame is 34 bytes, big-endian. The first row carries identity, routing, a 32-bit sequence number and the timestamp; the second row carries heart rate, SpO2, temperature, status flags, alert level and routing nibbles, then an 8-byte HMAC-SHA256 tag and a CRC-16.`rThe tag is computed with a per-device key over bytes 0 to 23 with the hop counter zeroed, so a relay can increment the hop count without knowing any key, but cannot alter anything else unnoticed. The sequence number survives reboots, and the gateway keeps a 62-frame replay window per device. The C++ encoder matches the Python reference byte for byte."

    # ============================================================ 7 Airtime
    $s = New-Content 'Binary framing keeps airtime and contention low'
    $rows = @(@('', 'Time on air (ms)'), @('JSON, same 15 fields (241 B)', 379.1), @('v2 binary frame (34 B)', 77.1))
    $cs = New-Chart $s 57 36 104 540 250 $rows
    $ch = $cs.Chart
    $ch.HasLegend = $false
    $ch.ChartGroups(1).GapWidth = 55
    $ser = $ch.SeriesCollection(1)
    $ser.Points(1).Format.Fill.ForeColor.ObjectThemeColor = $CORAL
    $ser.Points(2).Format.Fill.ForeColor.ObjectThemeColor = $TEAL
    Label-Points $ser @('379.1 ms', '77.1 ms') 2 $DARK 14 -bold
    $va = $ch.Axes(2); $va.MinimumScale = [single]0; $va.MaximumScale = [single]450; $va.MajorUnit = [single]100
    $va.HasTitle = $true; $va.AxisTitle.Text = 'time on air at SF7, 125 kHz, CR 4/5 (ms)'; $va.AxisTitle.Format.TextFrame2.TextRange.Font.Size = [single]12
    $ch.Axes(1).TickLabels.Font.Size = [single]13
    $null = T $s 'Semtech AN1200.13: T = (n_pre + 4.25 + N_s) · 2^SF / BW; 34 B gives 63 payload symbols.' 36 362 540 20 @{ size = 11; color = $SLATE; italic = $true }
    Stat $s '0.26 %' 'duty cycle at one frame per 30 s (1 % SRD sub-band limit)' 620 104 300 $TEAL 40
    Stat $s '0.90' 'frame success for 20 nodes on one channel (pure ALOHA, theory)' 620 214 300 $DARK 40
    Stat $s 'SF7 · 14 dBm' 'sync word 0x12: private raw LoRa, not LoRaWAN' 620 324 300 $SLATE 30
    $null = Box $s 36 410 888 74 $LIGHT
    Icon $s 'warn' 74 447 40 $AMBER
    $null = T $s 'Scaling beyond a few tens of patients per channel needs more channels or spreading factors, or scheduled transmissions.' 108 424 790 46 @{ size = 16; anchor = 3 }
    Notes $s "Why binary? With the Semtech formula, the 34-byte frame needs 63 payload symbols, about 77 milliseconds on air at SF7 and 125 kHz. A compact JSON with the same 15 fields is 241 bytes, about 379 milliseconds, almost five times more airtime, energy and collision exposure.`rAt one frame every 30 seconds the duty cycle is 0.26 percent, below the usual 1 percent limit. The binding constraint is contention: under a pure-ALOHA approximation, 20 nodes on one channel succeed about 90 percent of the time. Beyond a few tens of patients per channel we need more channels or spreading factors, or scheduling. These are theoretical estimates."

    # ============================================================ 8 UART
    $s = New-Content 'Two configuration faults blocked the Heltec to Pi 5 UART'
    $faults = @(
        @('Raspberry Pi 5 UART routing', '/dev/serial0 pointed to ttyAMA10, the debug UART; UART0 was not on GPIO14/15.', 'dtoverlay=uart0-pi5   ->  /dev/ttyAMA0', 'pinctrl get 14-15   ->  TXD0 / RXD0'),
        @('Heltec V3 transmit pin', 'GPIO43 is UART0 TX of the CP2102 USB bridge (console and flashing).', 'HardwareSerial PiSerial(1);', 'PiSerial.begin(115200, SERIAL_8N1, -1, 2);')
    )
    for ($i = 0; $i -lt 2; $i++) {
        $x = 36 + $i * 458
        $null = Box $s $x 100 430 196 $LIGHT
        Icon $s 'warn' ($x + 36) 134 42 $CORAL
        $null = T $s $faults[$i][0] ($x + 68) 122 260 26 @{ size = 18; bold = $true; head = $true; color = $DARK }
        $c = Chip $s $(if ($i -eq 0) { 'fixed' } else { 'applied' }) ($x + 350) 125 $GREEN $WHITE 11; $c.Left = $x + 412 - $c.Width
        $null = Paras $s (,@('Cause: ', $faults[$i][1])) ($x + 22) 166 386 44 @{ size = 14 }
        $null = Box $s ($x + 22) 218 386 64 $DARK @{ radius = 6 }
        $null = T $s ($faults[$i][2] + "`r" + $faults[$i][3]) ($x + 36) 226 364 50 @{ size = 13; font = 'Consolas'; color = $AQUA; anchor = 3 }
    }
    $null = Box $s 36 314 232 130 $LIGHT
    $null = T $s 'Heltec WiFi LoRa 32 V3' 50 326 210 20 @{ size = 14; bold = $true; color = $DARK }
    $null = T $s 'GPIO2  TX' 120 366 132 18 @{ size = 13; align = 3 }
    $null = T $s 'GND' 120 406 132 18 @{ size = 13; align = 3 }
    $null = Box $s 408 314 232 130 $LIGHT
    $null = T $s 'Raspberry Pi 5 header' 422 326 210 20 @{ size = 14; bold = $true; color = $DARK }
    $null = T $s 'pin 10  GPIO15 RXD0' 424 366 200 18 @{ size = 13 }
    $null = T $s 'pin 6  GND' 424 406 200 18 @{ size = 13 }
    foreach ($y in @(375, 415)) { $null = Shp $s 1 262 ($y - 5) 10 10 $DARK; $null = Shp $s 1 403 ($y - 5) 10 10 $DARK }
    $null = Arrow $s 272 375 403 375 $GREEN 2.5
    $null = Line $s 272 415 403 415 $DARK 2.5
    $null = T $s '115200 8N1 · 3.3 V both sides' 272 344 131 30 @{ size = 11; color = $GREEN; bold = $true; align = 2 }
    $null = T $s 'One-way link: Heltec TX to Pi RX; the Pi transmit line is unused.' 36 452 604 30 @{ size = 13; italic = $true; color = $SLATE }
    $null = Box $s 664 314 260 170 $WHITE @{ line = $AMBER; weight = 1.5 }
    $null = Chip $s 'pending' 680 328 $AMBER $DARK 11
    $null = T $s 'Packets arriving on /dev/ttyAMA0 are not yet confirmed.' 680 358 230 44 @{ size = 15; bold = $true; color = $DARK }
    $null = T $s 'Next: forward raw v2 frames as hex lines; the gateway stdin adapter reads them unchanged and the HMAC protects the UART hop.' 680 404 232 76 @{ size = 13 }
    Notes $s "On the bench, nothing arrived on /dev/serial0. Two independent faults.`rFirst, on the Raspberry Pi 5, serial0 pointed to ttyAMA10, the debug UART on its dedicated connector, and UART0 was not routed to GPIO 14 and 15. The uart0-pi5 overlay fixes the routing; the header UART is then ttyAMA0, and pinctrl must show TXD0 and RXD0. So it was routing, not a damaged pin.`rSecond, on the Heltec, GPIO43 belongs to the USB bridge, so UART1 was remapped to GPIO2 with RX disabled. Wiring: Heltec TX to Pi RX, common ground, 3.3 volts on both sides. Final reception is still to be confirmed."

    # ============================================================ 9 OMNeT model
    $s = New-Content 'OMNeT++/FLoRa model: 20 patients, 3 relays, one gateway'
    $null = Pic $s (Join-Path $assets 'omnet_topology.png') 36 100 470 -frame
    $null = T $s 'Qtenv view of DistributedRPMNetwork. OMNeT++ 6.5.0, INET 4.6.0, FLoRa 1.3.2 (opp_env, WSL).' 36 420 470 36 @{ size = 12; italic = $true; color = $SLATE }
    $null = Paras $s @(
        @('Geometry: ', 'gateway at the centre; patients on 25, 45 and 80 m rings; relays on a 30 m ring.'),
        @('Routing: ', 'patients 1-16 direct; 17-20 through an ordered relay chain.'),
        @('Propagation: ', 'log-normal shadowing, median range about 129 m at 14 dBm.'),
        @('Radio: ', 'SF7, 125 kHz, 14 dBm, one frame per 30 s, at most 4 hops.')
    ) 530 104 394 220 @{ size = 15; bullet = $true; after = 8 }
    $null = T $s 'FLoRa example configurations' 530 330 394 22 @{ size = 15; bold = $true; color = $DARK }
    $cfg = @(@('n100-gw1 (100 nodes, ADR)', 'started, not evaluated', $AMBER, $DARK), @('n1000 ADR / no-ADR / 2 GW', 'examined, not run', $SLATE, $WHITE), @('DistributedRPM (this work)', 'run 120 s, evaluated', $GREEN, $WHITE))
    for ($i = 0; $i -lt 3; $i++) {
        $y = 358 + $i * 42
        $null = Box $s 530 $y 394 36 $LIGHT @{ radius = 6 }
        $null = T $s $cfg[$i][0] 544 ($y + 9) 220 20 @{ size = 13 }
        $c = Chip $s $cfg[$i][1] 760 ($y + 8) $cfg[$i][2] $cfg[$i][3] 10; $c.Left = 914 - $c.Width
    }
    Notes $s "The bench validates interfaces, not network behaviour, so the network was modelled in OMNeT++ 6.5 with INET 4.6 and FLoRa 1.3.2. The doctor gateway sits in the centre, 20 patients on three rings, three relays on an inner ring. Patients 1 to 16 send directly, the four outer patients go through an ordered relay chain.`rPropagation uses FLoRa's log-normal shadowing. Of the FLoRa examples, the 100-node one was started but never produced scalar results, and the three 1000-node configurations were only examined, so no numbers are claimed from them."

    # ============================================================ 10 Simulation results
    $s = New-Content '79 of 80 frames delivered; each relay hop adds delay'
    $null = T $s '98.75 %' 36 100 360 70 @{ size = 60; bold = $true; head = $true; color = $TEAL }
    $null = T $s 'packet delivery ratio in the evaluated 120 s run (79 of 80)' 36 172 360 40 @{ size = 15; color = $SLATE }
    $mini = @(@('64', 'direct'), @('15', 'via relays'), @('0', 'collisions'), @('0', 'duplicates'))
    for ($i = 0; $i -lt 4; $i++) {
        $x = 36 + ($i % 2) * 182; $y = 220 + [Math]::Floor($i / 2) * 76
        $null = Box $s $x $y 170 64 $LIGHT
        $null = T $s $mini[$i][0] ($x + 16) ($y + 8) 60 44 @{ size = 30; bold = $true; head = $true; color = $DARK; anchor = 3 }
        $null = T $s $mini[$i][1] ($x + 74) ($y + 8) 90 44 @{ size = 15; color = $SLATE; anchor = 3 }
    }
    $rows = @(, @('', 'Simulated (FLoRa model)', 'Analytical, real 34-B frame'))
    $cat = @('direct', '1 hop', '2 hops', '3 hops')
    for ($i = 0; $i -lt 4; $i++) { $rows += , @($cat[$i], (Num $delay[$i].sim_ms), (Num $delay[$i].analytic34_ms)) }
    $cs = New-Chart $s 51 410 100 514 290 $rows
    $ch = $cs.Chart
    $ch.HasLegend = $true; $ch.Legend.Position = -4107; $ch.Legend.Format.TextFrame2.TextRange.Font.Size = [single]12
    $ch.ChartGroups(1).GapWidth = 70; $ch.ChartGroups(1).Overlap = -5
    $ch.SeriesCollection(1).Format.Fill.ForeColor.ObjectThemeColor = $TEAL
    $ch.SeriesCollection(2).Format.Fill.ForeColor.ObjectThemeColor = $AMBER
    Label-Points $ch.SeriesCollection(1) @($delay | ForEach-Object { (Num $_.sim_ms).ToString('0', $INV) }) 2 $DARK 12
    Label-Points $ch.SeriesCollection(2) @($delay | ForEach-Object { (Num $_.analytic34_ms).ToString('0', $INV) }) 2 $DARK 12
    $va = $ch.Axes(2); $va.MinimumScale = [single]0; $va.MaximumScale = [single]350; $va.MajorUnit = [single]100
    $va.HasTitle = $true; $va.AxisTitle.Text = 'end-to-end delay (ms)'; $va.AxisTitle.Format.TextFrame2.TextRange.Font.Size = [single]12
    $ch.Axes(1).TickLabels.Font.Size = [single]13
    $null = Box $s 36 408 888 76 $AMBER @{ bright = 0.78 }
    Icon $s 'warn' 74 446 40 $AMBER
    $null = T $s 'Caveat: FLoRa 1.3.2 computes airtime from a fixed 20-byte payload, so simulated delays ignore the real frame; patients transmit 1.5 s apart, so no collisions can occur in this run.' 108 418 796 58 @{ size = 15; anchor = 3 }
    Notes $s "In the evaluated run, 80 measurements were generated and 79 reached the doctor valid: 98.75 percent, 64 direct and 15 via relays, with no collisions and no duplicates. The single loss was patient 18's first frame, received by relay 1 at about minus 124.8 dBm, just below sensitivity: shadowing on the outer ring, not a protocol error.`rDelay is 78 milliseconds direct and grows by about 62 milliseconds per relay hop. Two caveats: FLoRa computes airtime from a fixed 20-byte payload, so the real 34-byte frame would cost at least 77 milliseconds per hop; and transmissions are staggered, so this run cannot show collisions."

    # ============================================================ 11 Dashboard overview
    $s = New-Content 'One screen shows every patient, alert and radio loss'
    $null = Pic $s (Join-Path $assets 'dash_overview.png') 36 100 0 392 -frame
    $call = @(
        @('people', $TEAL, 'Roles enforced on the server', 'Doctor sees all patients; assistant only assigned ones; caregiver one patient, with recorded consent.'),
        @('wave', $GREEN, 'Data-flow strip', 'Frames sent, validated, inferred, alerted and handled: radio losses become visible.'),
        @('db', $AMBER, 'Simulation is labelled', 'Banner on every page; simulated data live in a separate database.')
    )
    for ($i = 0; $i -lt 3; $i++) {
        $y = 100 + $i * 130
        Icon $s $call[$i][0] 610 ($y + 24) 44 $call[$i][1]
        $null = T $s $call[$i][2] 644 ($y + 10) 280 28 @{ size = 17; bold = $true; head = $true; color = $DARK }
        $null = T $s $call[$i][3] 644 ($y + 42) 280 76 @{ size = 15 }
    }
    Notes $s "This is the real dashboard, in simulation mode, so all patients are synthetic and the yellow banner says so. Access control is enforced on the server: a doctor sees everything, a medical assistant only the assigned patients, and a family caregiver a single patient, and only after a consent record exists.`rThe data-flow strip counts frames sent, validated, inferred, alerted and handled, so clinicians can see radio losses instead of silently missing data. Updates arrive through server-sent events."

    # ============================================================ 12 Patient view
    $s = New-Content 'The predictive warning arrived before the threshold alert'
    $null = Pic $s (Join-Path $assets 'dash_patient.png') 36 100 0 392 -frame
    $null = Line $s 640 140 640 300 $SLATE 2
    $ev = @(@(140, '07:46', 'Predictive warning', 'model: elevated risk of a threshold breach within about 10 min, with its main contributing features', $AMBER), @(250, '07:47', 'Threshold alert', 'heart rate 122 bpm above the 120 bpm limit', $CORAL))
    foreach ($e in $ev) {
        $null = Shp $s 9 632 ($e[0] - 8) 16 16 $e[4]
        $null = T $s $e[1] 656 ($e[0] - 12) 60 24 @{ size = 18; bold = $true; head = $true; color = $DARK }
        $null = T $s $e[2] 716 ($e[0] - 11) 210 24 @{ size = 16; bold = $true; color = $e[4] }
        $null = T $s $e[3] 656 ($e[0] + 16) 266 66 @{ size = 14 }
    }
    $null = Box $s 620 344 304 140 $LIGHT
    $null = T $s 'Four layers, kept apart' 636 356 280 22 @{ size = 15; bold = $true; color = $DARK }
    $null = T $s 'measurements · threshold alerts · statistics · model predictions' 636 380 276 40 @{ size = 14 }
    $null = T $s 'Web simulation, scenario G: shows the workflow, not clinical performance.' 636 428 276 48 @{ size = 13; italic = $true; color = $SLATE }
    Notes $s "The patient view of the same platform, during simulation scenario G, a slowly developing trend. The charts show heart rate, SpO2 and temperature with their limits; gaps are never interpolated as normal.`rThe interesting part is the alert list: the model's predictive warning was raised at 07:46, one minute before the deterministic heart-rate alert at 07:47. The warning lists its main contributing features. This illustrates the workflow in simulation only; it is not evidence of clinical performance."

    # ============================================================ 13 Synthetic data
    $s = New-Content 'No patient data: the model learns from a synthetic cohort'
    $ds = @(@('600', 'profiles of 8 hours each'), @('627,099', 'samples, every 15, 30 or 60 s'), @('0.15 %', 'HR and SpO₂ samples missing'), @('< 2 %', 'samples beyond each alert limit'))
    for ($i = 0; $i -lt 4; $i++) {
        $y = 100 + $i * 96
        $null = Box $s 36 $y 330 84 $LIGHT
        $null = T $s $ds[$i][0] 54 ($y + 10) 150 64 @{ size = 32; bold = $true; head = $true; color = $(if ($i -eq 3) { $CORAL } else { $TEAL }); anchor = 3 }
        $null = T $s $ds[$i][1] 196 ($y + 10) 160 64 @{ size = 15; color = $SLATE; anchor = 3 }
    }
    $null = T $s 'Episodes injected into the 600 profiles' 400 100 524 24 @{ size = 16; bold = $true; color = $DARK }
    # counts printed by report/tools/make_figure_data.py from ml/data/synth-v2/patients.csv
    $ep = @(@('fall', 29), @('abrupt change', 44), @('benign SpO₂ dip', 71), @('fever', 94), @('combined', 102), @('benign HR rise', 138), @('SpO₂ decline', 152), @('HR rise', 157))
    $rows = @(, @('', 'episodes')); foreach ($e in $ep) { $rows += , @($e[0], $e[1]) }
    $cs = New-Chart $s 57 400 128 524 300 $rows
    $ch = $cs.Chart; $ch.HasLegend = $false; $ch.ChartGroups(1).GapWidth = 45
    $ser = $ch.SeriesCollection(1)
    for ($k = 1; $k -le $ep.Count; $k++) { $ser.Points($k).Format.Fill.ForeColor.ObjectThemeColor = $(if ($ep[$k - 1][0] -like 'benign*') { $SLATE } else { $TEAL }) }
    Label-Points $ser @($ep | ForEach-Object { [string]$_[1] }) 2 $DARK 12
    $va = $ch.Axes(2); $va.MinimumScale = [single]0; $va.MaximumScale = [single]180; $va.MajorUnit = [single]50
    $ch.Axes(1).TickLabels.Font.Size = [single]13
    $null = T $s 'Teal: deterioration patterns. Slate: benign confounders that must not raise alarms.' 400 432 524 20 @{ size = 12; italic = $true; color = $SLATE }
    $null = T $s 'Seed 20261114, generator ml/generate_dataset.py; values are synthetic, not clinical observations.' 400 460 524 18 @{ size = 11; color = $SLATE }
    Notes $s "No real patient data were used. The model was developed on a documented synthetic cohort: 600 profiles of 8 hours, sampled every 15, 30 or 60 seconds, 627 thousand samples. Deterioration patterns such as heart-rate rise, SpO2 decline, fever, combined and abrupt changes, and falls, are injected together with benign confounders that must not trigger alarms, plus missing samples, outages, sensor faults and artifacts.`rOnly 1.2 to 2 percent of samples are beyond an alert limit, so the classes are strongly imbalanced, and a single value near a limit says very little."

    # ============================================================ 14 Model selection
    $s = New-Content 'Gradient boosting: best PR-AUC at the lowest latency'
    $null = Box $s 36 96 888 52 $LIGHT
    $null = Paras $s (,@('Target: ', 'a sustained breach (HR > 120 bpm, SpO₂ < 92 % or T ≥ 38.0 °C on two consecutive samples) within 10 min, from the last 15 min; 38 features; split by patient.')) 52 102 860 42 @{ size = 14; anchor = 3 }
    $tbl = @(
        @('Model', 'PR-AUC', 'ROC-AUC', 'Precision', 'Recall', 'F1', 'Episodes', 'False alarms / day'),
        @('Gradient boosting (deployed)', '0.543', '0.886', '0.433', '0.666', '0.525', '92/97', '7.06'),
        @('Random forest', '0.543', '0.897', '0.420', '0.689', '0.522', '92/97', '7.06'),
        @('Logistic regression', '0.413', '0.892', '0.307', '0.604', '0.407', '91/97', '10.49'),
        @('Isolation forest (baseline)', '0.259', '0.858', '0.277', '0.599', '0.379', '92/97', '8.89'),
        @('Trend rule (baseline)', '0.372', '0.877', '0.241', '0.595', '0.343', '94/97', '21.58')
    )
    $colW = @(232, 84, 88, 88, 80, 72, 92, 152)
    $ts = $s.Shapes.AddTable(6, 8, 36, 160, 888, 210)
    $tb = $ts.Table
    try { $tb.ApplyStyle('{2D5ABB26-0587-4C30-8999-92F81FD0307C}', $false) } catch {}
    for ($j = 1; $j -le 8; $j++) { $tb.Columns.Item($j).Width = $colW[$j - 1] }
    for ($i = 1; $i -le 6; $i++) {
        $tb.Rows.Item($i).Height = 34
        for ($j = 1; $j -le 8; $j++) {
            $cell = $tb.Cell($i, $j); $sh = $cell.Shape
            $sh.TextFrame.MarginLeft = 8; $sh.TextFrame.MarginRight = 8; $sh.TextFrame.MarginTop = 2; $sh.TextFrame.MarginBottom = 2; $sh.TextFrame.VerticalAnchor = 3
            $r = $sh.TextFrame.TextRange; $r.Text = $tbl[$i - 1][$j - 1]
            $r.Font.Name = '+mn-lt'; $r.Font.Size = [single]14; $r.ParagraphFormat.Alignment = $(if ($j -eq 1) { 1 } else { 2 })
            $sh.Fill.Visible = -1; $sh.Fill.Solid()
            if ($i -eq 1) { $sh.Fill.ForeColor.ObjectThemeColor = $DARK; $r.Font.Bold = -1; $r.Font.Color.ObjectThemeColor = $WHITE; $r.Font.Size = [single]13 }
            elseif ($i -eq 2) { $sh.Fill.ForeColor.ObjectThemeColor = $TEAL; $sh.Fill.ForeColor.Brightness = [single]0.78; $r.Font.Bold = -1; $r.Font.Color.ObjectThemeColor = $DARK }
            else { $sh.Fill.ForeColor.ObjectThemeColor = $(if ($i % 2 -eq 1) { $WHITE } else { $LIGHT }); $r.Font.Color.ObjectThemeColor = $INK }
        }
    }
    $ms = @(@('0.645', 'high-risk threshold, max F2 on validation'), @('0.0008', 'calibration error after isotonic fit'), @('450 KiB', 'model artifact on the gateway'), @('6.1 ms', 'per prediction with explanation, on the PC'))
    for ($i = 0; $i -lt 4; $i++) {
        $x = 36 + $i * 226
        $null = T $s $ms[$i][0] $x 392 210 40 @{ size = 30; bold = $true; head = $true; color = $(if ($i -eq 0) { $TEAL } else { $DARK }) }
        $null = T $s $ms[$i][1] $x 434 200 44 @{ size = 13; color = $SLATE }
    }
    Notes $s "The task: predict a sustained threshold breach in the next 10 minutes from the last 15 minutes, using 38 features such as levels, slopes, change versus the patient's own baseline and time to reach each limit. Data are split by patient, so the test patients are never seen in training.`rGradient boosting and random forest tie on PR-AUC, 0.543, but boosting is about ten times faster, so the rule picked it. The threshold maximises F2, which weights recall above precision. Calibration error is 0.0008, the model is 450 kilobytes and one prediction with explanation takes about 6 milliseconds on the PC; Pi 5 latency is not yet measured."

    # ============================================================ 15 Early warning vs false alarms
    $s = New-Content 'Early warnings work; false alarms remain the open problem'
    $null = T $s 'Synthetic test profile 265: model score, sample by sample' 36 98 560 22 @{ size = 15; bold = $true; color = $DARK }
    $rows = @(, @('', 'Model score', 'High-risk threshold (0.645)', 'Medium threshold (0.231)'))
    foreach ($r in $traj) {
        $tm = Num $r.tmin; $sc = Num $r.score
        if ($null -ne $tm -and $null -ne $sc -and $tm -ge -40 -and $tm -le 15) { $rows += , @($tm, $sc, 0.645, 0.231) }
    }
    $cs = New-Chart $s 75 36 122 570 288 $rows
    $ch = $cs.Chart
    $ch.HasLegend = $true; $ch.Legend.Position = -4107; $ch.Legend.Format.TextFrame2.TextRange.Font.Size = [single]12
    $sc = $ch.SeriesCollection(1); $sc.Format.Line.ForeColor.ObjectThemeColor = $CORAL; $sc.Format.Line.Weight = [single]2.25
    $hi = $ch.SeriesCollection(2); $hi.Format.Line.ForeColor.ObjectThemeColor = $DARK; $hi.Format.Line.Weight = [single]1.5; $hi.Format.Line.DashStyle = 4
    $md = $ch.SeriesCollection(3); $md.Format.Line.ForeColor.ObjectThemeColor = $SLATE; $md.Format.Line.Weight = [single]1.25; $md.Format.Line.DashStyle = 3
    foreach ($ser in @($sc, $hi, $md)) { try { $ser.MarkerStyle = -4142 } catch {} }
    $xa = $ch.Axes(1); $xa.MinimumScale = [single]-40; $xa.MaximumScale = [single]15; $xa.MajorUnit = [single]10
    $xa.HasTitle = $true; $xa.AxisTitle.Text = 'minutes relative to the simulated episode onset (breach at +7.3)'; $xa.AxisTitle.Format.TextFrame2.TextRange.Font.Size = [single]12
    $va = $ch.Axes(2); $va.MinimumScale = [single]0; $va.MaximumScale = [single]1; $va.MajorUnit = [single]1
    $xa.CrossesAt = -40
    Stat $s '92 / 97' 'test episodes warned in advance' 640 100 284 $TEAL 40
    Stat $s '8.5 min' 'median lead time (25th percentile 6.0 min)' 640 204 284 $DARK 40
    Stat $s '7.06' 'false-alarm episodes per patient-day: too many for unattended use' 640 308 284 $CORAL 40
    $null = Box $s 36 420 888 64 $LIGHT
    $null = T $s 'The score crosses the high level 3.5 min before the sustained breach; isolated heart-rate artifacts at -31 and -8 min cause transient spikes. Decision support only, evaluated on synthetic data.' 52 428 860 50 @{ size = 15; anchor = 3 }
    Notes $s "Here the model runs sample by sample on one synthetic test profile, chosen by a fixed rule before looking at scores. After the onset of an SpO2 decline, the score crosses the high level 3.5 minutes before the sustained breach. But two isolated heart-rate artifacts, at minus 31 and minus 8 minutes, produce short spikes: that is the typical false alarm.`rOver the whole test set, 92 of 97 episodes were warned in advance, with a median lead of 8.5 minutes, but at 7.06 false-alarm episodes per patient-day. That is too many for unattended use: alert aggregation and clinician-tuned thresholds are the next step. Accuracy, 0.98, would be misleading at 1.6 percent prevalence."

    # ============================================================ 16 Security
    $s = New-Content 'Frames are authenticated; the radio payload is not yet encrypted'
    $sec = @(
        @('Frame integrity', 'HMAC-SHA256 64-bit tag and CRC-16', 'tested', $GREEN, $WHITE), @('Replay protection', 'persisted seqNo, 62-frame window', 'tested', $GREEN, $WHITE), @('Radio confidentiality', 'payload sent in clear', 'gap', $CORAL, $WHITE),
        @('Keys at rest', 'AES-256-GCM key wrapping', 'tested', $GREEN, $WHITE), @('User login', 'scrypt, lockout, rate limit, TOTP', 'tested', $GREEN, $WHITE), @('Sessions', 'HttpOnly cookie, idle timeout, CSRF', 'tested', $GREEN, $WHITE),
        @('Access control', '3 roles, patient scope, consent', 'tested', $GREEN, $WHITE), @('Audit', 'SHA-256 hash-chained log', 'tested', $GREEN, $WHITE), @('Transport', 'HTTP only; TLS proxy needed', 'pending', $AMBER, $DARK)
    )
    for ($i = 0; $i -lt 9; $i++) {
        $x = 36 + ($i % 3) * 302; $y = 98 + [Math]::Floor($i / 3) * 112
        $fill = $(if ($sec[$i][2] -eq 'gap') { $CORAL } elseif ($sec[$i][2] -eq 'pending') { $AMBER } else { $LIGHT })
        $b = Box $s $x $y 284 98 $fill
        if ($fill -ne $LIGHT) { $b.Fill.ForeColor.Brightness = [single]0.82 }
        $null = T $s $sec[$i][0] ($x + 18) ($y + 16) 180 24 @{ size = 17; bold = $true; head = $true; color = $DARK }
        $c = Chip $s $sec[$i][2] ($x + 200) ($y + 17) $sec[$i][3] $sec[$i][4] 11; $c.Left = $x + 266 - $c.Width
        $null = T $s $sec[$i][1] ($x + 18) ($y + 52) 250 40 @{ size = 15 }
    }
    $null = T $s 'Proposed: AES-CCM with a nonce from the persisted seqNo; its 8-byte tag can replace the HMAC tag, so the frame stays 34 bytes.' 36 440 888 44 @{ size = 16; bold = $true; color = $TEAL; anchor = 3 }
    Notes $s "Security status, honestly. Implemented and covered by tests: frame integrity with a truncated HMAC-SHA256 tag and CRC, replay protection, device keys wrapped with AES-256-GCM, scrypt passwords with lockout and optional TOTP, hardened sessions with CSRF tokens, server-side role-based access with patient scoping and caregiver consent, and a hash-chained audit log.`rTwo gaps: the radio payload is sent in clear, so anyone on the channel can read vital signs, and the web server speaks plain HTTP, so a TLS reverse proxy is required. The proposed fix keeps the frame at 34 bytes."

    # ============================================================ 17 Lessons
    $s = New-Content 'Engineering lessons from the integration'
    $les = @(
        @('warn', $CORAL, 'Check routing before hardware', 'Pi 5: serial0 pointed to the debug UART; the uart0-pi5 overlay fixed it. No pin was damaged.'),
        @('bolt', $TEAL, 'Respect the board''s reserved pins', 'Heltec V3: GPIO43 belongs to the USB bridge; UART1 was remapped to GPIO2.'),
        @('gear', $DARK, 'Know the simulator''s simplifications', 'FLoRa: relay forwarding and TX power needed project modules; airtime uses a fixed 20-byte payload.'),
        @('db', $GREEN, 'Never mix simulated and real data', 'Separate databases, virtual device IDs from 60001 and a banner on every page.')
    )
    for ($i = 0; $i -lt 4; $i++) {
        $x = 36 + ($i % 2) * 456; $y = 100 + [Math]::Floor($i / 2) * 196
        $null = Box $s $x $y 432 180 $LIGHT
        Icon $s $les[$i][0] ($x + 44) ($y + 48) 52 $les[$i][1]
        $null = T $s $les[$i][2] ($x + 84) ($y + 34) 330 30 @{ size = 19; bold = $true; head = $true; color = $DARK }
        $null = T $s $les[$i][3] ($x + 24) ($y + 90) 384 80 @{ size = 16 }
    }
    Notes $s "Four lessons. First, check routing and configuration before suspecting hardware: the Pi 5 problem was a device alias and a missing overlay, not a broken pin. Second, read the board schematic: on the Heltec, GPIO43 is wired to the USB bridge, so the external UART had to move to GPIO2.`rThird, know your simulator: FLoRa needed a custom relay MAC and radio module for our forwarding, and its airtime model ignores the real payload size. Fourth, never mix simulated and real data: separate databases, separate identifiers and a visible banner."

    # ============================================================ 18 Status and next steps
    $s = New-Content 'Status today, and the road to a physical pilot'
    $lad = @(@('Tested', $GREEN, $WHITE, '233/233 software tests'), @('Simulated', $TEAL, $WHITE, 'PDR 98.75 %, 20 patients'), @('Analytical', $SLATE, $WHITE, '77 ms on air, 0.26 % duty'), @('Synthetic model', $AQUA, $DARK, 'PR-AUC 0.543, 92/97 warned'), @('Bench', $DARK, $WHITE, 'LoRa link with Heltec V3'), @('Pending', $AMBER, $DARK, 'sensors, radio RX, Pi 5, crypto'))
    for ($i = 0; $i -lt 6; $i++) {
        $y = 102 + $i * 64
        $null = Box $s 36 $y 380 54 $LIGHT
        $c = Chip $s $lad[$i][0] 50 ($y + 16) $lad[$i][1] $lad[$i][2] 11
        $null = T $s $lad[$i][3] 182 ($y + 15) 228 26 @{ size = 15; anchor = 3 }
    }
    $steps = @(
        @('1', 'Assemble and flash the physiological node', 'MAX30102, DS18B20, MPU-6050 on the ESP32-S3'),
        @('2', 'Validate radio reception on the Pi 5', 'UART and SPI paths; PDR, RSSI and delay on site'),
        @('3', 'Stress the network model', 'FLoRa n1000 ADR / no-ADR / two gateways, random traffic'),
        @('4', 'Harden before any pilot', 'AES-CCM payload, TLS, Pi 5 latency, ethics-approved data')
    )
    $null = Line $s 476 128 476 452 $TEAL 2
    for ($i = 0; $i -lt 4; $i++) {
        $y = 104 + $i * 100
        $null = Shp $s 9 456 ($y + 4) 40 40 $TEAL
        $null = T $s $steps[$i][0] 456 ($y + 4) 40 40 @{ size = 18; bold = $true; head = $true; color = $WHITE; align = 2; anchor = 3 }
        $null = T $s $steps[$i][1] 512 ($y + 2) 410 26 @{ size = 18; bold = $true; color = $DARK }
        $null = T $s $steps[$i][2] 512 ($y + 30) 410 40 @{ size = 15; color = $SLATE }
    }
    Notes $s "Where the project stands: a complete, tested software path from an authenticated LoRa frame to clinical views and an on-gateway model; a simulated multi-hop network with honest caveats; and a working bench radio link.`rThe road to a pilot is physical: assemble and flash the sensor node, validate reception on the Pi and measure delivery, RSSI and delay on site. Then stress the network model with the 1000-node FLoRa configurations and random traffic. Before any pilot: payload encryption, TLS, latency on the Pi 5 and, for clinical use, real data under ethical approval."

    # ============================================================ 19 Closing
    $s = New-Dark
    $null = Pulse $s 300 $CORAL 0 960 700
    $null = T $s 'Thank you' 60 118 600 70 @{ size = 54; bold = $true; head = $true; color = $WHITE }
    $null = T $s 'Questions and discussion' 60 196 600 36 @{ size = 26; color = $AQUA }
    $null = T $s 'Authenticated LoRa telemetry  ·  edge analytics on a Raspberry Pi 5  ·  evidence reported by category' 60 372 840 30 @{ size = 18; color = $LIGHT }
    $null = T $s 'Iheb Bekir  ·  Industry 4.0 LoRa remote patient monitoring project' 60 410 840 24 @{ size = 14; color = $AQUA }
    $null = Chip $s 'Research prototype, not a medical device' 60 486 $AMBER $DARK 12
    Notes $s "Thank you. To summarise: authenticated LoRa telemetry, edge processing and analytics on a Raspberry Pi 5, and every result labelled with the kind of evidence behind it. I am happy to take questions, for example on the frame design, the UART diagnosis, the simulation caveats or the false-alarm trade-off."

    # ---------------------------------------------------------------- sections, save, export
    $sp = $pres.SectionProperties
    $null = $sp.AddBeforeSlide(1, 'Opening')
    $null = $sp.AddBeforeSlide(4, 'System')
    $null = $sp.AddBeforeSlide(9, 'Evaluation')
    $null = $sp.AddBeforeSlide(16, 'Security and lessons')
    $null = $sp.AddBeforeSlide(18, 'Outlook')
    try { $pres.BuiltInDocumentProperties.Item('Title').Value = 'LoRa-Enabled Remote Patient Monitoring'; $pres.BuiltInDocumentProperties.Item('Author').Value = 'Iheb Bekir' } catch { Write-Host 'document properties not set' }
    $pres.SaveAs($pptxPath, 24)
    $pres.SaveCopyAs($pdfPath, 32)
    Get-ChildItem $renderDir -Filter 'slide-*.png' -ErrorAction SilentlyContinue | Remove-Item -Force
    for ($i = 1; $i -le $pres.Slides.Count; $i++) { $pres.Slides.Item($i).Export((Join-Path $renderDir ('slide-{0:D2}.png' -f $i)), 'PNG', 1600, 900) }
    Write-Host ("saved {0} slides -> {1}" -f $pres.Slides.Count, $pptxPath)
    $pres.Close()
} finally {
    $pp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
    [GC]::Collect()
}
