-- J4 建库编排所需的结构变更。
--
-- 1) index_task 增加 external_task_id：Python /documents/parse 返回的 task_id 要存下来，
--    否则轮询 /ingest/{task_id} 时无从得知该问哪个任务。Java 自己的主键 id 不能复用 ——
--    那是对外契约里的 taskId，和 Python 侧的任务标识是两个东西。
--
-- 2) 新建 chunk 表：GET /api/v1/chunks 的数据来源。
--    手册 §J4 第 4 条给了两个选项（调 Python 的 list 模式 / 读 Java 侧缓存表），
--    这里选缓存表：Python 侧任务表是进程内 dict，重启即丢；而片段浏览页要求重启后仍能看到
--    上次建库的结果。Java 侧缓存表的代价是「以最后一次成功建库为准」，这也正是
--    /index/status 的 needs_rebuild 语义所依赖的。
--
-- 注意 start / end 在 MySQL 里是保留字（END 尤其），列名用 char_start / char_end 规避，
-- 实体里仍叫 start / end 并显式映射。

-- 3) index_task 增加 poll_failures：轮询失败要「只重试、连续 30 次才 FAILED」，
--    计数必须落库 —— 放在内存里的话服务重启后计数归零，一个注定失败的任务会被无限重试。
ALTER TABLE `index_task`
    ADD COLUMN `external_task_id` VARCHAR(64) NULL COMMENT 'Python 侧入库任务 id' AFTER `overlap`,
    ADD COLUMN `poll_failures` INT NOT NULL DEFAULT 0 COMMENT '轮询连续失败次数' AFTER `error`;

CREATE TABLE IF NOT EXISTS `chunk` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `task_id`      BIGINT       NOT NULL COMMENT '产出它的建库任务（index_task.id）',
    `chunk_id`     VARCHAR(32)  NOT NULL COMMENT '片段号，形如 D02-C001',
    `doc_id`       BIGINT       NOT NULL COMMENT '所属资料 id',
    `doc_title`    VARCHAR(255) NOT NULL DEFAULT '' COMMENT '资料标题',
    `heading_path` VARCHAR(512) NOT NULL DEFAULT '' COMMENT '标题路径',
    `text`         MEDIUMTEXT   NOT NULL COMMENT '片段正文',
    `char_start`   INT          NOT NULL DEFAULT 0 COMMENT '正文起始偏移',
    `char_end`     INT          NOT NULL DEFAULT 0 COMMENT '正文结束偏移',
    `kind`         VARCHAR(16)  NOT NULL DEFAULT 'chunk' COMMENT 'chunk/summary/rule',
    `verified`     TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '资料是否已核实',
    `seq`          INT          NOT NULL DEFAULT 0 COMMENT '全局序号，用于稳定排序',
    `created_at`   BIGINT       NOT NULL COMMENT '创建时间（Unix 秒）',
    PRIMARY KEY (`id`),
    KEY `idx_chunk_task` (`task_id`),
    KEY `idx_chunk_doc` (`doc_id`),
    KEY `idx_chunk_kind` (`kind`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT ='片段缓存（最后一次成功建库的产物）';
