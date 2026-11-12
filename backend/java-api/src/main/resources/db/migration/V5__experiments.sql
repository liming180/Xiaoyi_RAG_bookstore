CREATE TABLE IF NOT EXISTS `experiment` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(255) NOT NULL,
    `status` VARCHAR(16) NOT NULL,
    `progress` INT NOT NULL DEFAULT 0,
    `total_groups` INT NOT NULL,
    `finished_groups` INT NOT NULL DEFAULT 0,
    `axes_json` JSON NOT NULL,
    `created_at` BIGINT NOT NULL,
    `finished_at` BIGINT NULL,
    `error` TEXT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_experiment_status` (`status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `experiment_run` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `experiment_id` BIGINT NOT NULL,
    `group_index` INT NOT NULL,
    `params_json` JSON NOT NULL,
    `metrics_json` JSON NOT NULL,
    `elapsed_ms` BIGINT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_experiment_group` (`experiment_id`, `group_index`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci;
