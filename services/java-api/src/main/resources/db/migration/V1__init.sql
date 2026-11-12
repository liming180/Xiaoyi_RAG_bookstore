-- ============================================================================
-- 小忆 RAG 问答系统 · 初始化建表
-- 对应 docs/02-重构设计/00_项目架构规格.md §5「数据表」与 后端文档.md §4
-- 阶段 J1 只建表，不插数据（演示账号由 J2 落地）
-- ============================================================================

CREATE TABLE IF NOT EXISTS `user` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `username`      VARCHAR(64)  NOT NULL COMMENT '登录名',
    `password_hash` VARCHAR(128) NOT NULL COMMENT '密码哈希（阶段1 演示账号，JWT 预留）',
    `role`          VARCHAR(32)  NOT NULL DEFAULT 'USER' COMMENT '角色：USER / ADMIN',
    `created_at`    BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_username` (`username`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='用户';

CREATE TABLE IF NOT EXISTS `conversation` (
    `id`         BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `user_id`    BIGINT       NOT NULL COMMENT '所属用户',
    `title`      VARCHAR(255) NOT NULL DEFAULT '新会话' COMMENT '会话标题',
    `deleted`    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记',
    `created_at` BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    `updated_at` BIGINT       NOT NULL COMMENT '更新时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_conversation_user_updated` (`user_id`, `updated_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='会话';

CREATE TABLE IF NOT EXISTS `message` (
    `id`                   BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `conversation_id`      BIGINT      NOT NULL COMMENT '所属会话',
    `role`                 VARCHAR(16) NOT NULL COMMENT 'user / assistant',
    `content`              MEDIUMTEXT  NOT NULL COMMENT '消息正文',
    `mode`                 VARCHAR(16) NULL COMMENT 'rag / direct / both',
    `top_k`                INT         NULL COMMENT '本次检索 top-k',
    `citations_json`       JSON        NULL COMMENT '引用列表（对外 Citation 数组）',
    `retrieval_trace_json` JSON        NULL COMMENT '检索轨迹（RetrievalTrace）',
    `usage_json`           JSON        NULL COMMENT 'token 用量',
    `elapsed_ms`           BIGINT      NULL COMMENT '耗时（毫秒）',
    `degraded`             TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否降级直答',
    `feedback`             VARCHAR(8)  NULL COMMENT 'up / down',
    `deleted`              TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '软删标记',
    `created_at`           BIGINT      NOT NULL COMMENT '创建时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_message_conversation_created` (`conversation_id`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='消息';

CREATE TABLE IF NOT EXISTS `document` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `title`       VARCHAR(255) NOT NULL COMMENT '展示标题',
    `filename`    VARCHAR(255) NOT NULL COMMENT '原始文件名',
    `storage_key` VARCHAR(512) NULL COMMENT '落盘相对路径',
    `sha256`      CHAR(64)     NULL COMMENT '内容指纹，用于去重',
    `version`     VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '版本号',
    `tags`        VARCHAR(512) NULL COMMENT '标签，逗号分隔',
    `status`      VARCHAR(24)  NOT NULL DEFAULT 'UPLOADING' COMMENT 'UPLOADING/PARSING/INDEXED/FAILED/NEEDS_REBUILD/DISABLED',
    `verified`    TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否已审核',
    `char_count`  INT          NOT NULL DEFAULT 0 COMMENT '正文字符数',
    `chunk_count` INT          NOT NULL DEFAULT 0 COMMENT '片段数',
    `error_msg`   VARCHAR(512) NULL COMMENT '失败原因',
    `uploaded_by` BIGINT       NULL COMMENT '上传者',
    `deleted`     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记',
    `created_at`  BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    `updated_at`  BIGINT       NOT NULL COMMENT '更新时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_document_status` (`status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='资料';

CREATE TABLE IF NOT EXISTS `index_task` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `status`          VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/RUNNING/SUCCEEDED/FAILED',
    `stage`           VARCHAR(16)  NOT NULL DEFAULT 'parsing' COMMENT 'parsing/splitting/embedding/summarizing/done',
    `progress`        INT          NOT NULL DEFAULT 0 COMMENT '进度 0-100',
    `chunk_size`      INT          NOT NULL COMMENT '片段长度',
    `overlap`         INT          NOT NULL COMMENT '重叠字数',
    `embedding_model` VARCHAR(64)  NULL COMMENT '嵌入模型',
    `doc_count`       INT          NOT NULL DEFAULT 0 COMMENT '参与文档数',
    `chunk_count`     INT          NOT NULL DEFAULT 0 COMMENT '产出片段数',
    `error`           VARCHAR(512) NULL COMMENT '失败原因',
    `created_at`      BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    `finished_at`     BIGINT       NULL COMMENT '完成时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_index_task_created` (`created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='建库任务';

CREATE TABLE IF NOT EXISTS `eval_run` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `name`           VARCHAR(255) NULL COMMENT '批次名',
    `mode`           VARCHAR(16)  NOT NULL DEFAULT 'both' COMMENT 'rag / direct / both',
    `top_k`          INT          NOT NULL DEFAULT 3 COMMENT '评测用 top-k',
    `question_count` INT          NOT NULL DEFAULT 0 COMMENT '题量',
    `result_csv`     MEDIUMTEXT   NULL COMMENT '逐题结果 CSV',
    `summary_json`   JSON         NULL COMMENT '汇总统计',
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING/SUCCEEDED/FAILED',
    `progress`       INT          NOT NULL DEFAULT 0 COMMENT '进度 0-100',
    `created_at`     BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    `finished_at`    BIGINT       NULL COMMENT '完成时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_eval_run_created` (`created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='评测批次';

CREATE TABLE IF NOT EXISTS `audit_log` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `user_id`     BIGINT       NULL COMMENT '操作者',
    `action`      VARCHAR(64)  NOT NULL COMMENT '动作',
    `target`      VARCHAR(255) NULL COMMENT '目标对象',
    `detail_json` JSON         NULL COMMENT '详情',
    `created_at`  BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_audit_log_created` (`created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='操作审计';
