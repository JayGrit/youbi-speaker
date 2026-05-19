# speaker Plan

## Responsibility

`speaker` prepares source vocal reference clips and generates target-language
speech clips. It owns VoxCPM model loading and per-segment TTS generation.

## Input Table

`yd_speaker`

Required fields:

- `task_id`
- `audio_vocals_path`
- `translation_json_path`
- `status IN ('ready', 'running')`

`yd_speaker` is the stage lifecycle row. Actual speak work is claimed from
`yd_speaker_segment`, one row per translated sentence.

## Outputs

- `vocals_segments_dir`
- `tts_segments_dir`

It copies `translation_json_path` and `tts_segments_dir` into `yd_combiner`.

## Polling

Poll one `yd_speaker_segment.status = 'ready'` row every
`POLL_INTERVAL_SECONDS`, joined with `yd_speaker.status IN ('ready', 'running')`.
Multiple speaker instances can claim different segments from the same video.
Tasks whose translator stage is already `success` are prioritized before tasks
that are still receiving translated segments.

## Processing

1. Claim one segment by atomically changing it from `ready` to `running`.
2. Move `yd_speaker` from `ready` to `running` if this is the first segment.
3. Split the source vocal reference for that segment.
4. Generate one WAV for that segment.
5. Mark the segment `success`.
6. When translator is `success` and all speaker segments are `success`, mark
   speaker `success`.
7. Mark combiner `ready`.

## Failure Handling

Segment failures are retried independently. When a segment exhausts retries,
mark speaker and task as `failed`. Generated clips are kept for resume.

## Later Work

- Add per-speaker voice controls.
- Add TTS quality validation.
