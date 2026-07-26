/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `speaker_segment` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `item_index` int(11) NOT NULL,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `src_text` mediumtext COLLATE utf8mb4_unicode_ci,
  `dst_text` mediumtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `src_lang` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `dst_lang` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `start_time` int(11) NOT NULL,
  `end_time` int(11) NOT NULL,
  `speaker` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reference_wav_path` text COLLATE utf8mb4_unicode_ci,
  `tts_wav_path` text COLLATE utf8mb4_unicode_ci,
  `attempt_count` int(11) NOT NULL DEFAULT '0',
  `max_attempts` int(11) NOT NULL DEFAULT '3',
  `error_message` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `started_at` datetime DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `operator` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `actual_start_time` int(11) DEFAULT NULL,
  `actual_end_time` int(11) DEFAULT NULL,
  `speed_ratio` double DEFAULT NULL,
  `reference_wav_url` text COLLATE utf8mb4_unicode_ci,
  `tts_wav_url` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_speaker_segment` (`task_id`,`item_index`),
  KEY `idx_speaker_segment_ready` (`status`,`task_id`,`item_index`),
  KEY `idx_speaker_segment_status_task_item` (`status`,`task_id`,`item_index`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `speaker_voice_profile` (
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sub_stage` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `profile_version` int(11) NOT NULL,
  `reference_item_index` int(11) DEFAULT NULL,
  `reference_text` mediumtext COLLATE utf8mb4_unicode_ci,
  `reference_wav_url` text COLLATE utf8mb4_unicode_ci,
  `reference_embedding_url` text COLLATE utf8mb4_unicode_ci,
  `generation_options_json` json DEFAULT NULL,
  `similarity_threshold` double DEFAULT NULL,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ready',
  `error_message` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`task_id`,`sub_stage`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `speaker_segment_similarity` (
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `segment_id` bigint(20) unsigned DEFAULT NULL,
  `item_index` int(11) NOT NULL,
  `sub_stage` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reference_embedding_url` text COLLATE utf8mb4_unicode_ci,
  `generated_embedding_url` text COLLATE utf8mb4_unicode_ci,
  `similarity_score` double DEFAULT NULL,
  `threshold` double DEFAULT NULL,
  `passed` tinyint(1) DEFAULT NULL,
  `metrics_json` json DEFAULT NULL,
  `error_message` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY `uk_speaker_segment_similarity_task_item_stage` (`task_id`,`item_index`,`sub_stage`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `speaker_multi_segment` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `item_index` int(11) NOT NULL,
  `chunk_index` int(11) NOT NULL DEFAULT '0',
  `text` mediumtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `start_time` int(11) NOT NULL,
  `end_time` int(11) NOT NULL,
  `whisper_run_id` bigint(20) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dubbing_multi_alignment_item` (`task_id`,`item_index`),
  KEY `idx_dubbing_multi_alignment_task` (`task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
