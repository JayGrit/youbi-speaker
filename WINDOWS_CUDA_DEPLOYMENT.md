# Windows CUDA Deployment Guide

This guide records the working Windows CUDA deployment path for `youbi-speaker`.

## Verified Machine

- OS: Windows
- Python: 3.12.10
- GPU: NVIDIA GeForce GTX 1660 Ti with Max-Q Design
- VRAM: 6 GB
- NVIDIA driver: 577.03
- PyTorch: `2.11.0+cu128`
- torchaudio: `2.11.0+cu128`
- VoxCPM2 model path: `D:\Money\youbi-speaker\data\modelscope\OpenBMB__VoxCPM2`

## Code Changes Made

Two source changes were required during deployment.

1. `pyproject.toml`

   The repository has a top-level `data` directory for model files. Setuptools tried to auto-discover both `data` and `ydbi_speaker` as packages, which broke editable installation. The fix explicitly lists the Python packages:

   ```toml
   [tool.setuptools]
   packages = ["ydbi_speaker", "ydbi_speaker.adapters"]
   ```

2. `ydbi_speaker/config.py` and `ydbi_speaker/adapters/voxcpm.py`

   VoxCPM optimization is controlled by `VOXCPM_OPTIMIZE`, defaulting to disabled:

   ```powershell
   $env:VOXCPM_OPTIMIZE='0'
   ```

   This avoids the heavier `torch.compile` and warmup path during model initialization and reduces startup pressure on a low-memory Windows GPU machine. To test it explicitly, start with `.\start-cuda.ps1 -Optimize`.

## Windows Prerequisites

### 1. NVIDIA Driver

Install a recent NVIDIA driver. Verify the GPU:

```powershell
nvidia-smi
```

Expected: the GPU is listed and driver information is shown.

### 2. Python 3.12

Install Python 3.12. The working setup used Python 3.12.10.

```powershell
winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
```

Verify:

```powershell
python --version
```

If Windows Store Python placeholders interfere, use the full Python path from:

```text
C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe
```

## Virtual Memory Requirement

VoxCPM2 can fail on Windows with:

```text
OSError: page file is too small to complete the operation. (os error 1455)
```

Set the Windows page file to at least 32 GB.

Recommended value:

- Initial size: `32768 MB`
- Maximum size: `32768 MB`

GUI path:

1. Open Windows search.
2. Open `Advanced system settings`.
3. `Performance` -> `Settings`.
4. `Advanced` -> `Virtual memory` -> `Change`.
5. Disable automatic management.
6. Select `C:`.
7. Set custom size to `32768` and `32768`.
8. Apply and restart Windows.

After restart, verify in an elevated PowerShell:

```powershell
Get-CimInstance Win32_PageFileSetting | Select-Object Name,InitialSize,MaximumSize
Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage
```

Expected:

```text
C:\pagefile.sys  32768  32768
```

## Project Setup

From the project directory:

```powershell
cd D:\Money\youbi-speaker
```

Create the virtual environment:

```powershell
C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
```

Upgrade pip:

```powershell
.\.venv\Scripts\python.exe -m pip install -U pip
```

Install project dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r docker-constraints.txt -e .
```

If the default PyPI connection is unstable in China, use a mirror:

```powershell
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r docker-constraints.txt -e .
```

## Install CUDA PyTorch

Install the CUDA build of PyTorch and torchaudio:

```powershell
.\.venv\Scripts\python.exe -m pip install --timeout 1000 --retries 10 --force-reinstall --index-url https://download.pytorch.org/whl/cu128 torch==2.11.0+cu128 torchaudio==2.11.0+cu128
```

If the large `torch` wheel download times out, download the wheel manually and install it from `wheels/`:

```powershell
.\.venv\Scripts\python.exe -m pip install --timeout 1000 --retries 10 --force-reinstall --index-url https://download.pytorch.org/whl/cu128 D:\Money\youbi-speaker\wheels\torch-2.11.0+cu128-cp312-cp312-win_amd64.whl torchaudio==2.11.0+cu128
```

If `fsspec` is upgraded to an incompatible version, restore it:

```powershell
.\.venv\Scripts\python.exe -m pip install fsspec==2025.3.0
```

Verify dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip check
```

Expected:

```text
No broken requirements found.
```

Verify CUDA:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.version.cuda); print(torch.cuda.get_device_name(0))"
```

Expected:

```text
2.11.0+cu128
True
12.8
NVIDIA GeForce GTX 1660 Ti with Max-Q Design
```

## Model Files

The working model directory is:

```text
D:\Money\youbi-speaker\data\modelscope\OpenBMB__VoxCPM2
```

Important files include:

```text
model.safetensors
audiovae.pth
```

If this directory exists, the service uses it directly and does not need to download `OpenBMB/VoxCPM2`.

## Test Model Loading

Before starting the service, test a direct model load:

```powershell
$env:VOXCPM_MODEL_DIR='D:\Money\youbi-speaker\data\modelscope\OpenBMB__VoxCPM2'
.\.venv\Scripts\python.exe -c "from voxcpm import VoxCPM; import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0)); m=VoxCPM.from_pretrained(r'D:\Money\youbi-speaker\data\modelscope\OpenBMB__VoxCPM2', load_denoiser=False, optimize=False); print('loaded', m.tts_model.device)"
```

Expected:

```text
Running on device: cuda, dtype: bfloat16
Loaded VoxCPM2Model
loaded cuda
```

## Start The Service

Recommended one-command startup:

```powershell
.\start-cuda.cmd
```

Or call PowerShell directly:

```powershell
.\start-cuda.ps1
```

The script sets:

- `DEVICE=MY_HP`
- `YDBI_ROOT=D:\Money\youbi-speaker`
- `WORKFOLDER=D:\Money\youbi-speaker\workfolder`
- `MODEL_CACHE_DIR=D:\Money\youbi-speaker\data\modelscope`
- `VOXCPM_MODEL_DIR=D:\Money\youbi-speaker\data\modelscope\OpenBMB__VoxCPM2`
- `VOXCPM_OPTIMIZE=0`
- `YDBI_SPEAKER_WORK_DIR=D:\Money\youbi-speaker\workfolder\speaker`

Successful startup logs look like:

```text
speaker service started; polling segments every 10s
Running on device: cuda, dtype: bfloat16
Loaded VoxCPM2Model
o2V-JJpJH_I:50 succeeded
```

## Background Mode

To run in the background and write logs:

```powershell
.\start-cuda.ps1 -Background
```

## Optional VoxCPM Optimize Mode

The default Windows CUDA startup keeps VoxCPM optimization disabled:

```text
VOXCPM_OPTIMIZE=0
```

On this machine, that is the safer production default. `optimize=True` triggers `torch.compile` and a warmup generation. It may improve repeated inference throughput on some CUDA machines, but it also increases startup time, memory pressure, and the chance of startup failure on 6 GB VRAM.

To test optimize mode:

```powershell
.\start-cuda.ps1 -Optimize
```

To test optimize mode in the background:

```powershell
.\start-cuda.ps1 -Optimize -Background
```

Keep optimize enabled only if startup completes and segment throughput is clearly better in real tasks.

Logs:

```text
speaker.out.log
speaker.err.log
```

Stop the background process:

```powershell
Get-Process python | Where-Object { $_.Path -like 'D:\Money\youbi-speaker\*' } | Stop-Process
```

## Troubleshooting

### `torch.cuda.is_available()` is `False`

- Confirm `nvidia-smi` works.
- Confirm CUDA PyTorch is installed: `torch.__version__` should include `+cu128`.
- Reinstall `torch==2.11.0+cu128` and `torchaudio==2.11.0+cu128`.

### Page file error `os error 1455`

- Increase Windows virtual memory to 32 GB or higher.
- Restart Windows after changing it.
- Retry the direct model load test.

### MySQL connection blocked in Codex sandbox

If running through a restricted sandbox, remote MySQL/MinIO sockets may be blocked. Run the start command directly in your own PowerShell terminal.

### Process exits with empty logs

Run in foreground mode first:

```powershell
.\start-cuda.ps1
```

Foreground mode prints Python exceptions directly to the terminal.

### 6 GB VRAM is tight

The GTX 1660 Ti Max-Q worked after increasing page file size, but the margin is small. Avoid running other GPU-heavy applications while the service is processing.
