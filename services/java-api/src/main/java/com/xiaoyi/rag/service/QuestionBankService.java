package com.xiaoyi.rag.service;

import com.xiaoyi.rag.model.dto.EvalQuestionRequest;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import java.util.List;

/**
 * 评测题库管理（P5-08）。
 *
 * <p>题库从「打包进 jar 的静态 CSV」升级为用户可管理的数据库数据：资料变多时可以自行加题，不必改代码重新打包。
 *
 * <p>第一次访问时按需把内置种子（{@code assets/eval/questions.csv} 的 13 道题）复制一份到该用户名下，之后增删改只影响自己。
 */
public interface QuestionBankService {

    /**
     * 当前用户的题库（含停用题），供管理界面与选题共用。
     *
     * @param userId 归属用户
     * @return 题库，按题型 → 题号排序
     */
    List<EvalQuestionVO> list(Long userId);

    /**
     * 当前用户**启用中**的题库，评测选题走这条。
     *
     * @param userId 归属用户
     * @return 可参与选题的题目
     */
    List<EvalQuestionVO> listEnabled(Long userId);

    /**
     * 新增题目。题号留空时自动按题型生成（single → S001、cross → X001、out → O001）。
     *
     * @param userId 归属用户
     * @param request 题面与判分关键词
     * @return 落库后的题目
     */
    EvalQuestionVO create(Long userId, EvalQuestionRequest request);

    /**
     * 修改题目。题号不可改 —— 它已被历史评测快照引用。
     *
     * @param userId 归属用户
     * @param code 题号
     * @param request 新题面与判分关键词
     * @return 修改后的题目
     */
    EvalQuestionVO update(Long userId, String code, EvalQuestionRequest request);

    /**
     * 停用 / 启用题目。停用的题不再进入新评测，但历史评测照常可读。
     *
     * @param userId 归属用户
     * @param code 题号
     * @param enabled true = 启用，false = 停用
     * @return 修改后的题目
     */
    EvalQuestionVO setEnabled(Long userId, String code, boolean enabled);

    /**
     * 删除题目。
     *
     * <p>只允许删非种子题：种子题一旦被删，用户就再也拿不回来（种子只在题库为空时灌一次）。
     *
     * @param userId 归属用户
     * @param code 题号
     */
    void delete(Long userId, String code);

    /**
     * 导出当前用户全部题目为 CSV（列与 {@code assets/eval/questions.csv} 对齐，可直接再导入）。
     *
     * @param userId 归属用户
     * @return CSV 正文（带 UTF-8 BOM）
     */
    String exportCsv(Long userId);

    /**
     * 从 CSV 导入题目。列序为「题号,类型,问题,关键词,证据文件」，表头可省略。
     *
     * <p>题号冲突时的策略是**跳过并计数**，不是整批失败 —— 导入几十行时因为一行重复就全废掉，重导成本太高。
     *
     * @param userId 归属用户
     * @param csv CSV 正文
     * @return 导入结果（新增几行、跳过几行、逐行错误说明）
     */
    ImportResult importCsv(Long userId, String csv);

    /**
     * 导入结果。
     *
     * @param created 新增行数
     * @param skipped 跳过行数
     * @param errors 逐行错误说明（行号 + 原因），为空表示无错误
     */
    record ImportResult(int created, int skipped, List<String> errors) {}
}
