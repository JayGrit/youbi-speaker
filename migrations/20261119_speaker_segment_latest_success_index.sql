ALTER TABLE speaker_segment
    ADD INDEX idx_speaker_segment_status_completed (status, completed_at),
    ALGORITHM=INPLACE,
    LOCK=NONE;
