-- N4 候选池接通实验：给候选补一列人工判分关键词。
--
-- 为什么必须有这一列：
-- `accepted` 之后候选要能进参数实验并计分，但计分靠 `EvalServiceImpl.judge()`
-- 拿 keywords 做「组内 `/` 同义、组间 `|` 必须全中」的匹配。题库的 keywords
-- 来自 `assets/eval/keywords.csv`，而候选是用户现场点👎产生的，题库里根本没有它 ——
-- 没有关键词就判不了分，硬判只会把 hitRate 算成一个假数字。
--
-- 所以链路拆成两档：
--   补了 keywords  → 进实验计分（metrics.scored 计数，进 hitRate 分母）
--   没补 keywords  → 也能进实验，但标 scored:false，只做人工对照，不进分母
-- 这一列就是「补了没补」的唯一凭据，NULL 与空串都按没补处理。
--
-- 为什么是 VARCHAR(512) 而不是 TEXT：
-- 语法上它就是 `keywords.csv` 那一列的复制品（形如 `4本/4册|21天`），
-- 题库里最长的一行不过几十字节。512 足够，且能在库层拦住误粘贴整段回答。
ALTER TABLE `eval_candidate`
    ADD COLUMN `keywords` VARCHAR(512) NULL
        COMMENT '人工补的判分关键词，语法同 keywords.csv（组内 / 同义、组间 | 必须全中）'
        AFTER `status`;
