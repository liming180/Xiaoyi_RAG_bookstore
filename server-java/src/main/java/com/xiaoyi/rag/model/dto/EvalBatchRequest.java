package com.xiaoyi.rag.model.dto;

import java.util.List;

/**
 * 批量评测请求（P5-08 起支持按条件选题）。
 *
 * <p>选题有两条路径，语义互斥、按优先级解析：
 *
 * <ol>
 *   <li>{@code questionIds} 非空 → **精确点选**，忽略 types / limit / sample（用户已经明确勾了哪几道）；
 *   <li>{@code questionIds} 为空 → **按条件筛选**：先按 {@code types} 过滤（空 = 全部题型）， 再按 {@code sample}
 *       决定顺序，最后取 {@code limit} 道（空 = 不限）。
 * </ol>
 *
 * <p>为什么要加 types/limit 而不是让前端算出题号列表：题库是用户数据，会持续增长； 前端算题号意味着每次筛选都要把整库拉到浏览器再回传，题库涨到几百行时这个往返既慢又容易不一致。
 *
 * @param questionIds 精确点选的题号；空 = 走条件筛选
 * @param types 题型筛选（single / cross / out）；空 = 全部题型
 * @param limit 最多测几道；null 或 &lt;= 0 = 不限
 * @param sample true = 随机抽样，false / null = 按题库顺序取前 N
 * @param mode both / direct / rag
 * @param k 检索 top-k
 */
public record EvalBatchRequest(
        List<String> questionIds,
        List<String> types,
        Integer limit,
        Boolean sample,
        String mode,
        Integer k) {

    /** 兼容旧调用：只有题号 + 模式 + k 时全部走精确点选。 */
    public EvalBatchRequest(List<String> questionIds, String mode, Integer k) {
        this(questionIds, List.of(), null, null, mode, k);
    }
}
