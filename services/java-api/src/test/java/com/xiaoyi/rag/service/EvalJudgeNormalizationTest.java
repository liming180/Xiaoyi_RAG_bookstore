package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.xiaoyi.rag.service.impl.EvalServiceImpl;
import org.junit.jupiter.api.Test;

/**
 * 评测判分必须对空白不敏感。
 *
 * <p>缺陷出处：真实 provider（glm-4-flash）在中文与数字之间加空格是常态输出 ——「普通图书每人最多借 4 本，借期 21 天」，而题库关键词写的是 {@code 4本} /
 * {@code 21天}。原来的 {@code answer.contains(word)} 直接比对，完全正确的答案被判成未命中，passedRag 被系统性压低（实测 T03 命中 4 本 /
 * 21 天却给 False）。
 *
 * <p>为什么必须改在 Java 侧：最终判分入口是 {@code EvalServiceImpl.evaluate}，它调用本类的 {@code judge}。Python 的 {@code
 * /eval/batch} 只被黑盒用例直接调用，改那边不影响前端看到的成绩。
 *
 * <p>语义必须与 Python 侧 {@code routes._judge} 的 {@code _squash} 保持一致，否则同一份答案两侧给出不同结论。
 */
class EvalJudgeNormalizationTest {

    private static final String KEYWORDS = "4本/四本|21天/二十一天";

    @Test
    void spacesAroundNumbersStillMatch() {
        assertThat(EvalServiceImpl.judge("普通图书每人最多借 4 本，借期 21 天。", KEYWORDS))
                .as("带空格的真实回答被判成未命中 —— 判分没做空白归一化")
                .isTrue();
        // 无空格写法照样要过。
        assertThat(EvalServiceImpl.judge("普通图书每人最多借4本，借期21天。", KEYWORDS)).isTrue();
    }

    @Test
    void fullwidthSpaceAndNewlineAreNormalized() {
        String keywords = "周六|14:00";
        assertThat(EvalServiceImpl.judge("读书会每周六\u300014:00 举行", keywords)).isTrue();
        assertThat(EvalServiceImpl.judge("读书会\n每周六\t14:00", keywords)).isTrue();
    }

    @Test
    void groupSemanticsUnchanged() {
        String keywords = "周六|14:00/14点";
        assertThat(EvalServiceImpl.judge("每周六 14:00 举行", keywords)).as("组内同义 + 组间全命中应通过").isTrue();
        assertThat(EvalServiceImpl.judge("每周六 15:00 举行", keywords)).as("缺 14:00 这组不该通过").isFalse();
        assertThat(EvalServiceImpl.judge("每周日 14:00 举行", keywords)).as("缺周六这组不该通过").isFalse();
    }

    @Test
    void emptyKeywordsStillFail() {
        // N4 的既定边界：没有关键词就判不出对错，不计入分母。
        assertThat(EvalServiceImpl.judge("随便什么答案", "")).isFalse();
        assertThat(EvalServiceImpl.judge("随便什么答案", null)).isFalse();
    }
}
