-- J5 evaluation persistence. eval_run is created by V1; retain its BIGINT id and JSON summary payload.
-- The existing result_csv/summary_json columns hold UTF-8 BOM CSV and complete cases respectively.
ALTER TABLE `eval_run` MODIFY COLUMN `status` VARCHAR(16) NOT NULL DEFAULT 'PENDING';
