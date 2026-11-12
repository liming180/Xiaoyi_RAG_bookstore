-- 演示模式固定用户，供 dev-token 和未登录前端联调使用。
INSERT INTO `user` (`id`, `username`, `password_hash`, `role`, `created_at`)
SELECT 1, 'demo', 'demo', 'USER', UNIX_TIMESTAMP()
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE `id` = 1);
