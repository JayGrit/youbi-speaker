param(
  [string]$Device = "LPXB_HP",
  [switch]$Optimize,
  [switch]$Background
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$WorkFolder = Join-Path $Root "workfolder"
$ModelCacheDir = Join-Path $Root "data\modelscope"
$VoxCpmModelDir = Join-Path $ModelCacheDir "OpenBMB__VoxCPM2"
$SpeakerWorkDir = Join-Path $WorkFolder "speaker"
$StdoutLog = Join-Path $Root "speaker.out.log"
$StderrLog = Join-Path $Root "speaker.err.log"

if (-not (Test-Path -LiteralPath $Python)) {
  throw "Python virtual environment not found: $Python"
}

if (-not (Test-Path -LiteralPath $VoxCpmModelDir)) {
  throw "VoxCPM2 model directory not found: $VoxCpmModelDir"
}

New-Item -ItemType Directory -Force -Path $WorkFolder, $SpeakerWorkDir | Out-Null

$env:DEVICE = $Device
$env:YDBI_ROOT = $Root
$env:WORKFOLDER = $WorkFolder
$env:MODEL_CACHE_DIR = $ModelCacheDir
$env:VOXCPM_MODEL_DIR = $VoxCpmModelDir
$env:VOXCPM_OPTIMIZE = if ($Optimize) { "1" } else { "0" }
$env:YDBI_SPEAKER_WORK_DIR = $SpeakerWorkDir

Write-Host "Starting youbi-speaker on CUDA"
Write-Host "Root: $Root"
Write-Host "Device: $env:DEVICE"
Write-Host "Model: $env:VOXCPM_MODEL_DIR"
Write-Host "VoxCPM optimize: $env:VOXCPM_OPTIMIZE"

if ($Background) {
  Remove-Item -LiteralPath $StdoutLog, $StderrLog -Force -ErrorAction SilentlyContinue
  $Process = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "ydbi_speaker.main") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru `
    -WindowStyle Hidden

  Write-Host "Started background process: $($Process.Id)"
  Write-Host "Stdout: $StdoutLog"
  Write-Host "Stderr: $StderrLog"
  exit 0
}

& $Python -m ydbi_speaker.main
