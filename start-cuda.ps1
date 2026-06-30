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
$env:SPEECHBRAIN_SPEAKER_MODEL_DIR = Join-Path $ModelCacheDir "speechbrain-spkrec-ecapa-voxceleb"

Write-Host "Starting youbi-speaker on CUDA"
Write-Host "Root: $Root"
Write-Host "Device: $env:DEVICE"
Write-Host "Model: $VoxCpmModelDir"
Write-Host "FFmpeg: $env:FFMPEG_BINARY"
Write-Host "SpeechBrain speaker model: $env:SPEECHBRAIN_SPEAKER_MODEL_DIR"
Write-Host "Auto update: git pull every 60 seconds"
if ($env:FFPROBE_BINARY) {
  Write-Host "FFprobe: $env:FFPROBE_BINARY"
}

function Invoke-DependencyInstall {
  Write-Host "Installing Python dependencies after update..."
  & $Python -m pip install -e .
  if ($LASTEXITCODE -ne 0) {
    throw "pip install -e . failed"
  }
}

function Start-SpeakerProcess {
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

    Write-Host "Started background service process: $($Process.Id)"
    Write-Host "Stdout: $StdoutLog"
    Write-Host "Stderr: $StderrLog"
    return $Process
  }

  Write-Host "Started foreground service process."
  return Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "ydbi_speaker.main") `
    -WorkingDirectory $Root `
    -PassThru `
    -NoNewWindow
}

function Stop-SpeakerProcess {
  param([System.Diagnostics.Process]$Process)

  if ($Process -and -not $Process.HasExited) {
    Write-Host "Stopping speaker process $($Process.Id)..."
    Stop-Process -Id $Process.Id -Force
    Wait-Process -Id $Process.Id -Timeout 30 -ErrorAction SilentlyContinue
  }
}

function Get-GitHead {
  try {
    return (& git -C $Root rev-parse HEAD 2>$null).Trim()
  } catch {
    return ""
  }
}

function Update-Repository {
  $LocalHead = Get-GitHead
  if (-not $LocalHead) {
    Write-Warning "Not a git repository or git is unavailable; skipping auto update."
    return $false
  }

  Write-Host "Checking for updates..."
  & git -C $Root fetch --quiet origin "+refs/heads/main:refs/remotes/origin/main"
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "git fetch origin/main failed; keeping current process running."
    return $false
  }

  $RemoteHead = (& git -C $Root rev-parse refs/remotes/origin/main 2>$null).Trim()
  if (-not $RemoteHead) {
    Write-Warning "origin/main was not found after fetch; keeping current process running."
    return $false
  }

  if ($RemoteHead -eq $LocalHead) {
    Write-Host "No new version on origin/main."
    return $false
  }

  & git -C $Root merge-base --is-ancestor $LocalHead $RemoteHead
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Local HEAD and origin/main have diverged; automatic update skipped."
    return $false
  }

  Write-Host "New origin/main version found: $($RemoteHead.Substring(0, 7))"
  & git -C $Root merge --ff-only $RemoteHead
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Fast-forward update failed; keeping current process running."
    return $false
  }

  return ((Get-GitHead) -eq $RemoteHead)
}

$Process = Start-SpeakerProcess
try {
  while ($true) {
    Start-Sleep -Seconds 60

    if ($Process.HasExited) {
      Write-Warning "speaker exited with code $($Process.ExitCode); restarting."
      $Process = Start-SpeakerProcess
      continue
    }

    if (Update-Repository) {
      Write-Host "Repository updated; restarting speaker."
      Stop-SpeakerProcess $Process
      Invoke-DependencyInstall
      $Process = Start-SpeakerProcess
    }
  }
} finally {
  Stop-SpeakerProcess $Process
}
