-- H2/H3：全链路用户隔离 + 任务幂等与代际切换。
-- 原则：只做前向迁移，不改 V1–V6；历史行的 user_id 保持 NULL（不回填成 1），由应用层显式拒绝。

-- 1) 资料：乐观锁版本号。建库成功时用它做「快照未被改动」的原子判据。
ALTER TABLE `document`
    ADD COLUMN `revision` BIGINT NOT NULL DEFAULT 0;

ALTER TABLE `document`
    ADD KEY `idx_document_owner_updated` (`uploaded_by`, `deleted`, `updated_at`);

-- 2) 建库任务：归属、幂等键、代际、请求快照。
ALTER TABLE `index_task`
    ADD COLUMN `user_id` BIGINT NULL,
    ADD COLUMN `generation` VARCHAR(64) NULL,
    ADD COLUMN `submission_key` VARCHAR(64) NULL,
    ADD COLUMN `snapshot_json` LONGTEXT NULL;

ALTER TABLE `index_task`
    ADD KEY `idx_index_task_user_status` (`user_id`, `status`),
    ADD KEY `idx_index_task_user_key` (`user_id`, `submission_key`);

-- 同一用户同时只允许一个非终态任务：用生成列 + 唯一索引在库层兜底，
-- 并发重建时第二个请求会在 INSERT 处失败，而不是两个任务互相覆盖片段缓存。
ALTER TABLE `index_task`
    ADD COLUMN `active_user_id` BIGINT
        GENERATED ALWAYS AS (
            CASE WHEN `status` IN ('PENDING', 'RUNNING') THEN `user_id` ELSE NULL END
        ) STORED;

ALTER TABLE `index_task`
    ADD UNIQUE KEY `uk_index_task_active_user` (`active_user_id`);

-- 3) 片段：加归属列，直接从任务回填历史行（任务本身此刻可能还没有 user_id，回填结果允许为 NULL）。
ALTER TABLE `chunk`
    ADD COLUMN `user_id` BIGINT NULL;

UPDATE `chunk` c
    JOIN `index_task` t ON c.`task_id` = t.`id`
SET c.`user_id` = t.`user_id`
WHERE c.`user_id` IS NULL;

ALTER TABLE `chunk`
    ADD KEY `idx_chunk_user` (`user_id`, `task_id`);

-- 4) 评测与实验：加归属列。
ALTER TABLE `eval_run`
    ADD COLUMN `user_id` BIGINT NULL;

ALTER TABLE `eval_run`
    ADD KEY `idx_eval_run_user` (`user_id`, `created_at`);

ALTER TABLE `experiment`
    ADD COLUMN `user_id` BIGINT NULL;

ALTER TABLE `experiment`
    ADD KEY `idx_experiment_user` (`user_id`, `created_at`);
