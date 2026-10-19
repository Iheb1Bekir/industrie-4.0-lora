param(
    [string]$BoardFqbn = "esp32:esp32:esp32s3",
    [string]$SketchPath = "wokwi/patient_node",
    [string]$BuildPath = "wokwi/patient_node/build"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
Set-Location $repo

function Ensure-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required command '$name' not found in PATH. Install Arduino CLI first."
    }
}

Ensure-Command "arduino-cli"

Write-Host "Checking installed ESP32 core..."
$cores = arduino-cli core list | Out-String
if ($LASTEXITCODE -ne 0) { throw "Could not list Arduino cores." }
if ($cores -notmatch "(?m)^esp32:esp32\s") {
    Write-Host "Installing ESP32 core..."
    arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
    if ($LASTEXITCODE -ne 0) { throw "Failed to update the ESP32 board index." }
    arduino-cli core install esp32:esp32 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
    if ($LASTEXITCODE -ne 0) { throw "Failed to install the ESP32 core." }
}

Write-Host "Compiling ESP32 sketch..."
arduino-cli compile --fqbn $BoardFqbn --build-path $BuildPath $SketchPath
if ($LASTEXITCODE -ne 0) { throw "ESP32 compilation failed." }

Write-Host "Build complete. Generated outputs:"
Get-ChildItem $BuildPath | Where-Object { $_.Name -match "\.(bin|elf)$" } | Select-Object Name
