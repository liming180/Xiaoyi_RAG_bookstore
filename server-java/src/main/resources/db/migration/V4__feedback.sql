-- J5 反馈与候选池；每条助手消息一条当前反馈，负反馈最多产生一个候选。
CREATE TABLE IF NOT EXISTS `feedback` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `message_id` BIGINT NOT NULL,
    `rating` VARCHAR(8) NOT NULL,
    `tags_json` JSON NOT NULL,
    `comment` TEXT NULL,
    `created_at` BIGINT NOT NULL,
    `updated_at` BIGINT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_feedback_message` (`message_id`),
    KEY `idx_feedback_rating` (`rating`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `eval_candidate` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `message_id` BIGINT NULL,
    `question` MEDIUMTEXT NOT NULL,
    `source` VARCHAR(16) NOT NULL DEFAULT 'feedback',
    `status` VARCHAR(16) NOT NULL DEFAULT 'pending',
    `created_at` BIGINT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_eval_candidate_message` (`message_id`),
    KEY `idx_eval_candidate_status` (`status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci;
