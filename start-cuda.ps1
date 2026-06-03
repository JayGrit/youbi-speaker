param(
  [string]$Device = "LPXB_HP",
  [switch]$Background
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ModelCacheDir = Join-Path $Root "data\modelscope"
$VoxCpmModelDir = Join-Path $ModelCacheDir "OpenBMB__VoxCPM2"
$StdoutLog = Join-Path $Root "speaker.out.log"
$StderrLog = Join-Path $Root "speaker.err.log"
$LocalFfmpegBin = Join-Path $Root "ffmpeg\bin"

if (-not (Test-Path -LiteralPath $Python)) {
  throw "Python virtual environment not found: $Python"
}

if (-not (Test-Path -LiteralPath $VoxCpmModelDir)) {
  throw "VoxCPM2 model directory not found: $VoxCpmModelDir"
}

function Resolve-Executable {
  param(
    [string]$Name,
    [string]$EnvName
  )

  $Explicit = [Environment]::GetEnvironmentVariable($EnvName)
  if ($Explicit) {
    if (Test-Path -LiteralPath $Explicit) {
      return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $FromExplicit = Get-Command $Explicit -ErrorAction SilentlyContinue
    if ($FromExplicit) {
      return $FromExplicit.Source
    }
    throw "$EnvName points to a missing executable: $Explicit"
  }

  $FromPath = Get-Command $Name -ErrorAction SilentlyContinue
  if ($FromPath) {
    return $FromPath.Source
  }

  $Candidate = Join-Path $LocalFfmpegBin "$Name.exe"
  if (Test-Path -LiteralPath $Candidate) {
    return (Resolve-Path -LiteralPath $Candidate).Path
  }

  $CommonCandidates = @(
    "C:\ffmpeg\bin\$Name.exe",
    "C:\Program Files\ffmpeg\bin\$Name.exe",
    "C:\ProgramData\chocolatey\bin\$Name.exe"
  )
  foreach ($Path in $CommonCandidates) {
    if (Test-Path -LiteralPath $Path) {
      return (Resolve-Path -LiteralPath $Path).Path
    }
  }

  throw "Missing $Name. Install FFmpeg and add its bin directory to PATH, or set $EnvName to $Name.exe."
}

$env:FFMPEG_BINARY = Resolve-Executable "ffmpeg" "FFMPEG_BINARY"
try {
  $env:FFPROBE_BINARY = Resolve-Executable "ffprobe" "FFPROBE_BINARY"
} catch {
  $env:FFPROBE_BINARY = ""
  Write-Warning "ffprobe not found; continuing because speaker reads WAV files with an explicit format."
}
$env:DEVICE = $Device

Write-Host "Starting youbi-speaker on CUDA"
Write-Host "Root: $Root"
Write-Host "Device: $env:DEVICE"
Write-Host "Model: $VoxCpmModelDir"
Write-Host "FFmpeg: $env:FFMPEG_BINARY"
if ($env:FFPROBE_BINARY) {
  Write-Host "FFprobe: $env:FFPROBE_BINARY"
}

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
