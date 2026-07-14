# ydbi-speaker

`speaker` generates target speech. It claims speaker tasks and speaker segment
rows, prepares reference audio, calls VoxCPM, stores TTS segments, and records
timing/quality metadata for downstream combiner stages.

## Role

- Selects or builds voice references from vocals or narration reference audio.
- Generates per-segment TTS audio.
- Supports dubbing, multi-segment voice profiles and narration segments.
- Uploads generated speech and reference artifacts to MinIO.
- Keeps VoxCPM/model-heavy runtime isolated from lighter services.

## Run

```bash
cd /Users/hoshuuch/Money/YouBi/services/speaker
pip install -e .
ydbi-speaker
```

Helper commands:

```bash
ydbi-speaker-test-tts
ydbi-speaker-rerun-segment
```

See `WINDOWS_CUDA_DEPLOYMENT.md` for Windows CUDA deployment notes.

## Configuration

- `VOXCPM_DEVICE`: default `auto`.
- `WORKFOLDER` or `YDBI_WORK_ROOT`: local work root.
- `NARRATION_REFERENCE_AUDIO_URL`: reference audio for narration.
- `SPEECHBRAIN_SPEAKER_MODEL`: speaker similarity model.
- `YDBI_MYSQL_*` and `YDBI_MINIO_*`: database and object storage.
- `DEVICE`: worker identity.

## Checks

```bash
pytest
python -m compileall ydbi_speaker
```
