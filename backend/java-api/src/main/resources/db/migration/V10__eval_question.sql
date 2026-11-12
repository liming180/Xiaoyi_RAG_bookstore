-- P5-08 题库数据库化：把「固定 13 题」升级为用户可管理的题库。
--
-- 为什么要拆表：
--   旧实现把题库写死在 classpath 的 assets/eval/questions.csv，靠 pom 的
--   <resource> 打进 jar，并由 `EvalServiceImpl.loadQuestions()` 硬校验
--   `size() != 13` 抛异常。资料一多，13 道题根本覆盖不到新资料，
--   而加一道题要改仓库文件 + 重新打包 + 重启 —— 这就是「题库不跟着知识库长大」的根因。
--
-- 为什么带 user_id：
--   题库是用户资产，A 加的题不该出现在 B 的评测选题里。带 user_id 之后
--   后续要做「共享题库 / 团队题库」只需再加一张授权表，不用改这张表的结构。
--
-- 为什么有 enabled 而不是直接删行：
--   `eval_run.summary_json` 里存着历史评测的题号快照。硬删题会让历史报告里的
--   题号变成孤儿（点开详情只看到一串查不到的 id）。停用只影响「下次选题」，
--   历史评测照常可读，这是可复现性的底线。
--
-- 为什么 code 与 id 分开：
--   code 是稳定的人类可读编号（T01 / U001 / G001），会被写进 summary_json 与
--   导出 CSV；id 是数据库自增主键，只在内部用。用 code 做业务键，将来换库
--   （或重建种子数据）时历史记录不会因为 id 变化而对不上。
--
-- 为什么 (user_id, code) 唯一而 code 本身不全局唯一：
--   内置种子题在每个用户第一次进评测页时按需复制一份（source='seed'），
--   这样每个用户都能编辑/停用自己的那份，互不影响。
CREATE TABLE `eval_question` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL COMMENT '归属用户',
    `code` VARCHAR(64) NOT NULL COMMENT '题号，如 T01 / U001 / G001',
    `type` VARCHAR(16) NOT NULL COMMENT 'single 单份资料可答 / cross 需综合多篇 / out 库外题',
    `question` TEXT NOT NULL COMMENT '题面',
    `keywords` VARCHAR(512) NOT NULL COMMENT '判分关键词，语法同 keywords.csv（组内 / 同义、组间 | 必须全中）',
    `evidence` VARCHAR(512) NULL COMMENT '证据文件名；库外题填「无」',
    `source` VARCHAR(16) NOT NULL DEFAULT 'manual' COMMENT 'seed 内置种子 / manual 手工新增 / generated 自动生成 / import CSV导入',
    `enabled` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 参与选题；0 停用（历史评测仍可读）',
    `created_at` BIGINT NOT NULL,
    `updated_at` BIGINT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_eval_question_user_code` (`user_id`, `code`),
    KEY `idx_eval_question_user_type` (`user_id`, `enabled`, `type`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'P5-08 评测题库（用户可增删改）';
