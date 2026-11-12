-- V11：管理端与用户管理（docs/02-重构设计/06_管理端与用户管理设计方案.md §6）
-- 1) user 表补 display_name 与 deleted
ALTER TABLE `user`
    ADD COLUMN `display_name` VARCHAR(64) NULL
        COMMENT '显示名（NULL 时前端回退显示 username）' AFTER `username`,
    ADD COLUMN `deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '软删标记';

-- 2) 主 bootstrap 账号升 ADMIN（幂等：只升级不降级；行不存在时不做事）
UPDATE `user`
SET role = 'ADMIN',
    display_name = COALESCE(display_name, '管理员')
WHERE username = 'admin' AND role <> 'ADMIN' AND deleted = 0;
