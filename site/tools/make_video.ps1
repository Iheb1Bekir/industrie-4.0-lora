# Edits the real website recording + bench photo + OMNeT++ screenshot into the square showcase video.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File site\tools\make_video.ps1 <website_recording.mp4> <omnet_recording.mp4> <work_dir>
# Needs ffmpeg on PATH and the frames rendered by site/tools/render_media.py (site/design/out/*.png).
# Output: site/media/rpm-lora-showcase.mp4 (720 px, web/README), site/media/omnet-run.mp4 (web clip),
#         site/media/omnet-run.gif (README preview) and <work_dir>/rpm-lora-showcase-1080.mp4 (LinkedIn).
$ErrorActionPreference = 'Stop'
$raw = (Resolve-Path $args[0]).Path
$omnet = (Resolve-Path $args[1]).Path
$work = $args[2]; New-Item -ItemType Directory -Force -Path $work | Out-Null
$site = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$frames = Join-Path $site 'design\out'
$media = Join-Path $site 'media'
$enc = @('-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', '30', '-an')
$B = 'crop=1600:840:300:127'        # in-app browser layout: page area only (no app sidebar, no taskbar)
$A = 'crop=1876:918:42:112'         # Opera layout (first 17 s): page area only (no tabs, bookmarks or taskbar)
$i = 0; $list = @()

function Out-Scene([string]$name) { $script:i++; $p = Join-Path $work ('scene{0:D2}-{1}.mp4' -f $script:i, $name); $script:list += $p; return $p }
function Fade([double]$d) { return ('fade=t=in:st=0:d=0.3,fade=t=out:st={0}:d=0.3' -f ($d - 0.3).ToString([Globalization.CultureInfo]::InvariantCulture)) }
function Static([string]$frame, [double]$d, [switch]$first) {
    $o = Out-Scene $frame
    $f = Fade $d; if ($first) { $f = $f -replace '^fade=t=in:st=0:d=0\.3,', '' }   # the opening frame is the hook itself, not black
    & ffmpeg -v error -y -loop 1 -framerate 30 -t $d -i (Join-Path $frames "$frame.png") -vf ("format=yuv420p," + $f) @enc -t $d $o
}
function Clip([string]$frame, [double]$start, [double]$len, [double]$speed, [string]$crop, [int]$x, [int]$y, [int]$w, [int]$h) {
    $d = [Math]::Round($len / $speed, 2)
    $o = Out-Scene $frame
    $fc = "[1:v]$crop,setpts=(PTS-STARTPTS)/$speed,scale=$($w):$($h):flags=lanczos,fps=30[v];[0:v]fps=30,format=yuv420p[bg];[bg][v]overlay=$($x):$($y):shortest=1," + (Fade $d) + ",format=yuv420p[out]"
    & ffmpeg -v error -y -loop 1 -framerate 30 -t $d -i (Join-Path $frames "$frame.png") -ss $start -t $len -i $raw -filter_complex $fc -map '[out]' @enc -t $d $o
}
function Still([string]$frame, [string]$img, [string]$pre, [double]$d, [int]$x, [int]$y, [int]$w, [int]$h) {
    $o = Out-Scene $frame
    $n = [int]($d * 30); $z = (0.045 / $n).ToString('0.000000', [Globalization.CultureInfo]::InvariantCulture)
    $fc = "[1:v]$pre,scale=$(2*$w):$(2*$h),zoompan=z='1+$z*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=$($w)x$($h):fps=30[v];[0:v]fps=30,format=yuv420p[bg];[bg][v]overlay=$($x):$($y):shortest=1," + (Fade $d) + ",format=yuv420p[out]"
    & ffmpeg -v error -y -loop 1 -framerate 30 -t $d -i (Join-Path $frames "$frame.png") -loop 1 -framerate 30 -t $d -i $img -filter_complex $fc -map '[out]' @enc -t $d $o
}

# OMNeT++ Qtenv recording (1432x834): three cuts shown 1:1 in the 1000x525 hole, without dips between them:
# packets in flight (network canvas), drill-down into the doctor gateway's NIC, end-of-run LoRaMedium statistics.
function Omnet([string]$frame) {
    $cuts = @(@(1.4, 7.4, 1.5, 216, 0), @(8.5, 13.6, 1.5, 0, 0), @(20.2, 23.6, 1.0, 0, 309))
    $d = 0.0; foreach ($c in $cuts) { $d += ($c[1] - $c[0]) / $c[2] }; $d = [Math]::Round($d, 2)
    $o = Out-Scene $frame
    $inv = [Globalization.CultureInfo]::InvariantCulture
    $parts = @(); $labels = @()
    for ($j = 0; $j -lt $cuts.Count; $j++) {
        $c = $cuts[$j]
        $parts += ('[s{0}]trim=start={1}:end={2},setpts=(PTS-STARTPTS)/{3},crop=1000:525:{4}:{5},fps=30[c{0}]' -f $j, $c[0].ToString($inv), $c[1].ToString($inv), $c[2].ToString($inv), $c[3], $c[4])
        $labels += "[c$j]"
    }
    $fc = '[1:v]split=3[s0][s1][s2];' + ($parts -join ';') + ';' + ($labels -join '') + 'concat=n=3:v=1:a=0[v];[0:v]fps=30,format=yuv420p[bg];[bg][v]overlay=40:300:shortest=1,' + (Fade $d) + ',format=yuv420p[out]'
    & ffmpeg -v error -y -loop 1 -framerate 30 -t $d -i (Join-Path $frames "$frame.png") -i $omnet -filter_complex $fc -map '[out]' @enc -t $d $o
    # web clip of the same run for the site (packets in flight + statistics, no frame) and a README GIF
    & ffmpeg -v error -y -i $omnet -filter_complex '[0:v]split=2[x][y];[x]trim=start=1.4:end=7.4,setpts=PTS-STARTPTS,crop=1000:525:216:0[a];[y]trim=start=20.2:end=24.2,setpts=PTS-STARTPTS,crop=1000:525:0:309[b];[a][b]concat=n=2:v=1:a=0,fps=30,scale=1000:-2[v]' -map '[v]' -c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p -an -movflags +faststart (Join-Path $media 'omnet-run.mp4')
    & ffmpeg -v error -y -ss 22.6 -i $omnet -frames:v 1 -vf 'crop=1000:525:216:0' -q:v 3 (Join-Path $media 'omnet-run-poster.jpg')
    & ffmpeg -v error -y -ss 1.4 -t 6 -i $omnet -vf 'crop=1000:525:216:0,fps=10,scale=720:-1:flags=lanczos,split[p][q];[p]palettegen=max_colors=96:stats_mode=diff[pal];[q][pal]paletteuse=dither=bayer:bayer_scale=4' (Join-Path $media 'omnet-run.gif')
}

Static 'hook' 3.6 -first
Still 'scene-photo' (Join-Path $media 'hardware-bench.jpg') 'crop=1280:672:0:44' 5.0 40 300 1000 525
Clip 'scene-login' 1.0 15.5 2.0 $A 40 317 1000 490
Clip 'scene-overview' 23.5 24.0 2.4 $B 40 300 1000 525
Clip 'scene-map' 110.0 24.0 3.0 $B 40 300 1000 525
Clip 'scene-twin' 139.0 33.0 3.0 $B 40 300 1000 525
Clip 'scene-ai' 226.5 24.0 2.4 $B 40 300 1000 525
Omnet 'scene-omnet'
Static 'results' 5.2
Static 'end' 5.0

$txt = Join-Path $work 'scenes.txt'
($list | ForEach-Object { "file '" + ($_ -replace '\\', '/') + "'" }) | Set-Content -Encoding ascii $txt
$total = 0.0; foreach ($p in $list) { $total += [double](& ffprobe -v error -show_entries format=duration -of csv=p=0 $p) }
$tot = $total.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
$big = Join-Path $work 'rpm-lora-showcase-1080.mp4'
& ffmpeg -v error -y -f concat -safe 0 -i $txt -f lavfi -t $tot -i 'anullsrc=r=48000:cl=stereo' -map 0:v -map 1:a -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -profile:v high -level 4.1 -r 30 -c:a aac -b:a 64k -shortest -movflags +faststart $big
& ffmpeg -v error -y -i $big -vf 'scale=720:720:flags=lanczos' -c:v libx264 -preset slow -crf 25 -pix_fmt yuv420p -profile:v high -r 30 -an -movflags +faststart (Join-Path $media 'rpm-lora-showcase.mp4')
& ffmpeg -v error -y -ss 1.2 -i $big -frames:v 1 -q:v 3 (Join-Path $work 'linkedin-video-thumbnail.jpg')
"total {0} s" -f $tot
Get-Item $big, (Join-Path $media 'rpm-lora-showcase.mp4') | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 2) } } | Format-Table -AutoSize | Out-String
