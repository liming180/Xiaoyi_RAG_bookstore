-- N2 追问推荐落库。
--
-- 为什么必须落库而不是只在 SSE 的 done 帧里带一次：
-- `done.suggestions` 只在「刚刚生成完」那一刻可见。用户刷新页面、切到别的会话
-- 再切回来、或者第二天打开历史，chips 就全没了 —— 而那正是 chips 最有用的时候
-- （看完回答才想追问）。旧实现里 `ConversationServiceImpl.toVO` 恒给 `List.of()`，
-- 所以刷新即丢。
--
-- 类型选 JSON 而不是 TEXT：与同表的 citations_json / retrieval_trace_json /
-- usage_json 保持一致，Java 侧统一按 String 存原文（见 Message 实体的注释）。
-- 允许 NULL：N2 之前的历史行没有这一列，它们就该是 NULL 而不是 '[]'。
ALTER TABLE `message`
    ADD COLUMN `suggestions_json` JSON NULL COMMENT '追问推荐，字符串数组' AFTER `usage_json`;
