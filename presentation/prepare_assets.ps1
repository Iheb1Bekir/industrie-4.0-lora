# Crops the report images into presentation/assets (System.Drawing, no extra software).
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File presentation\prepare_assets.ps1
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$fig = Join-Path (Split-Path -Parent $here) 'report\figures'
$out = Join-Path $here 'assets'
New-Item -ItemType Directory -Force -Path $out | Out-Null

function Save-Crop([string]$src, [string]$dst, [int]$x, [int]$y, [int]$w, [int]$h, [int]$maxW, [string]$fmt) {
    $img = [System.Drawing.Image]::FromFile($src)
    try {
        $scale = [Math]::Min(1.0, $maxW / [double]$w)
        $dw = [int][Math]::Round($w * $scale); $dh = [int][Math]::Round($h * $scale)
        $bmp = New-Object System.Drawing.Bitmap $dw, $dh
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $g.DrawImage($img, (New-Object System.Drawing.Rectangle 0, 0, $dw, $dh), (New-Object System.Drawing.Rectangle $x, $y, $w, $h), [System.Drawing.GraphicsUnit]::Pixel)
        $g.Dispose()
        if ($fmt -eq 'jpg') {
            $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
            $ep = New-Object System.Drawing.Imaging.EncoderParameters 1
            $ep.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality), 90L
            $bmp.Save($dst, $codec, $ep)
        } else { $bmp.Save($dst, [System.Drawing.Imaging.ImageFormat]::Png) }
        $bmp.Dispose()
        "{0}: {1}x{2}" -f (Split-Path -Leaf $dst), $dw, $dh
    } finally { $img.Dispose() }
}

# bench photo (1280x960): drop the background at the top and bottom
Save-Crop (Join-Path $fig 'hardware_architecture_real.jpg') (Join-Path $out 'bench_photo.jpg') 0 110 1280 760 1280 'jpg'
# dashboard overview (2560x2200 @2x): main area without the sidebar, KPIs + data flow + first patient cards
Save-Crop (Join-Path $fig 'dashboard_overview.png') (Join-Path $out 'dash_overview.png') 470 0 2070 1570 1800 'png'
# patient view (2560x2242 @2x): trends + alerts
Save-Crop (Join-Path $fig 'patient_monitoring.png') (Join-Path $out 'dash_patient.png') 495 688 2040 1517 1800 'png'
# Qtenv topology (765x510): keep whole view
Save-Crop (Join-Path $fig 'omnet_flora_simulation.png') (Join-Path $out 'omnet_topology.png') 0 0 765 510 765 'png'
# LoRaMedium statistics (962x207)
Save-Crop (Join-Path $fig 'omnet_flora_log.png') (Join-Path $out 'omnet_log.png') 0 0 962 207 962 'png'
