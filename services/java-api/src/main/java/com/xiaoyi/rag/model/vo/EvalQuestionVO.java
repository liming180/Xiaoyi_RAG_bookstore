package com.xiaoyi.rag.model.vo;

/**
 * 评测题目视图（P5-08 起由数据库承载）。
 *
 * @param id 题号（人类可读的 {@code code}，如 T01 / U001），不是数据库主键 —— 它会被写进评测快照与导出 CSV，必须稳定
 * @param type single 单份资料可答 / cross 需综合多篇 / out 库外题（考察拒答）
 * @param question 题面
 * @param keywords 判分关键词，语法同 keywords.csv；空串 = 不参与计分
 * @param evidence 证据文件名；库外题为「无」
 * @param enabled 是否参与选题（停用题仍留在题库与历史快照里）
 * @param source seed 内置种子 / manual 手工新增 / import CSV 导入 / generated 自动生成
 */
public record EvalQuestionVO(
        String id,
        String type,
        String question,
        String keywords,
        String evidence,
        Boolean enabled,
        String source) {

    /**
     * 兼容旧调用：没有 enabled / source 的场景按「启用 + 手工」处理。
     *
     * <p>候选池转题、单元测试构造等路径只需要题号与题面，多余的字段让它们全改成 7 参数没有价值。
     */
    public EvalQuestionVO(
            String id, String type, String question, String keywords, String evidence) {
        this(id, type, question, keywords, evidence, Boolean.TRUE, "manual");
    }
}
