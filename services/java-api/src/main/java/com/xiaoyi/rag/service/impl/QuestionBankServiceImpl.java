package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.common.enums.ErrorCode;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.EvalQuestionRequest;
import com.xiaoyi.rag.model.entity.EvalQuestion;
import com.xiaoyi.rag.model.vo.EvalQuestionVO;
import com.xiaoyi.rag.repository.EvalQuestionRepository;
import com.xiaoyi.rag.service.QuestionBankService;
import jakarta.annotation.PostConstruct;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 评测题库管理实现（P5-08）。
 *
 * <p>核心变化：题库不再是启动时读进内存的不可变 List，而是数据库里的用户数据。
 *
 * <p>种子策略 —— 首次访问时按需灌入：{@code assets/eval/questions.csv} 只在「该用户题库为空」时复制一份到其名下， 标记 {@code
 * source=seed}。这样每个用户都能编辑自己的那份（改题面、停用、删掉不想要的），互不影响； 同时也避免了在 {@code @PostConstruct}
 * 里为所有历史用户批量插入，那会让启动变慢且无法服务将来新增的用户。
 */
@Service
public class QuestionBankServiceImpl implements QuestionBankService {

    private static final String TYPE_SINGLE = "single";
    private static final String TYPE_CROSS = "cross";
    private static final String TYPE_OUT = "out";
    private static final Set<String> TYPES = Set.of(TYPE_SINGLE, TYPE_CROSS, TYPE_OUT);

    private final EvalQuestionRepository repository;

    /** 启动时读一次种子模板；只作为「新用户首次灌库」的模板，不直接参与评测。 */
    private final List<EvalQuestionVO> seed;

    public QuestionBankServiceImpl(EvalQuestionRepository repository) {
        this.repository = repository;
        this.seed = loadSeed();
    }

    /**
     * 启动时校验种子可读。
     *
     * <p>刻意不在这里灌库：一是没有用户列表，二是灌库应当按需发生（见类注释）。这里只做 fail-fast —— 种子文件缺失或格式坏掉时，
     * 让应用在启动阶段就炸掉，而不是等第一个用户点进评测页才发现。
     */
    @PostConstruct
    void validateSeed() {
        if (seed.isEmpty()) throw new IllegalStateException("内置题库为空");
    }

    @Override
    @Transactional
    public List<EvalQuestionVO> list(Long userId) {
        ensureSeeded(userId);
        return repository.findAllOwnedBy(userId).stream()
                .map(QuestionBankServiceImpl::toVO)
                .toList();
    }

    @Override
    @Transactional
    public List<EvalQuestionVO> listEnabled(Long userId) {
        ensureSeeded(userId);
        return repository.findEnabledOwnedBy(userId).stream()
                .map(QuestionBankServiceImpl::toVO)
                .toList();
    }

    @Override
    @Transactional
    public EvalQuestionVO create(Long userId, EvalQuestionRequest request) {
        ensureSeeded(userId);
        String type = normalizeType(request.type());
        String question = requireText(request.question(), "题面不能为空");
        String code = blank(request.code()) ? nextCode(userId, type) : request.code().strip();
        if (repository.existsByUserIdAndCode(userId, code)) {
            throw new ApiException(ErrorCode.QUESTION_CODE_DUPLICATE.getCode(), "题号已存在: " + code);
        }
        EvalQuestion row = new EvalQuestion();
        row.setUserId(userId);
        row.setCode(code);
        row.setType(type);
        row.setQuestion(question);
        row.setKeywords(blank(request.keywords()) ? "" : request.keywords().strip());
        row.setEvidence(blank(request.evidence()) ? null : request.evidence().strip());
        row.setSource("manual");
        row.setEnabled(Boolean.TRUE);
        return toVO(repository.saveAndFlush(row));
    }

    @Override
    @Transactional
    public EvalQuestionVO update(Long userId, String code, EvalQuestionRequest request) {
        EvalQuestion row = owned(userId, code);
        row.setType(normalizeType(request.type()));
        row.setQuestion(requireText(request.question(), "题面不能为空"));
        row.setKeywords(blank(request.keywords()) ? "" : request.keywords().strip());
        row.setEvidence(blank(request.evidence()) ? null : request.evidence().strip());
        return toVO(repository.saveAndFlush(row));
    }

    @Override
    @Transactional
    public EvalQuestionVO setEnabled(Long userId, String code, boolean enabled) {
        EvalQuestion row = owned(userId, code);
        row.setEnabled(enabled);
        return toVO(repository.saveAndFlush(row));
    }

    @Override
    @Transactional
    public void delete(Long userId, String code) {
        EvalQuestion row = owned(userId, code);
        if ("seed".equals(row.getSource())) {
            // 种子题删了就再也拿不回来（种子只在题库为空时灌一次），只能停用。
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "内置题不能删除，可以改成停用");
        }
        repository.delete(row);
    }

    @Override
    @Transactional
    public String exportCsv(Long userId) {
        ensureSeeded(userId);
        StringBuilder out = new StringBuilder("\ufeff题号,类型,问题,关键词,证据文件\r\n");
        for (EvalQuestionVO q : list(userId)) {
            out.append(csvCell(q.id()))
                    .append(',')
                    .append(csvCell(typeLabel(q.type())))
                    .append(',')
                    .append(csvCell(q.question()))
                    .append(',')
                    .append(csvCell(q.keywords()))
                    .append(',')
                    .append(csvCell(q.evidence() == null ? "" : q.evidence()))
                    .append("\r\n");
        }
        return out.toString();
    }

    @Override
    @Transactional
    public ImportResult importCsv(Long userId, String csv) {
        ensureSeeded(userId);
        if (blank(csv)) throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "CSV 内容为空");
        int created = 0;
        int skipped = 0;
        List<String> errors = new ArrayList<>();
        String[] lines = csv.split("\r?\n");
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i].strip();
            if (line.isEmpty()) continue;
            // 表头：第一行含「题号」或 question 字样就跳过，不强制要求表头存在。
            if (i == 0 && (line.contains("题号") || line.contains("问题"))) continue;
            String[] cells = line.split(",", -1);
            if (cells.length < 3) {
                skipped++;
                errors.add("第 " + (i + 1) + " 行：列数不足，至少需要「题号,类型,问题」");
                continue;
            }
            try {
                String code = cells[0].strip();
                String type = normalizeType(typeCode(cells[1].strip()));
                String question = requireText(cells[2], "题面不能为空");
                if (blank(code)) code = nextCode(userId, type);
                if (repository.existsByUserIdAndCode(userId, code)) {
                    skipped++;
                    errors.add("第 " + (i + 1) + " 行：题号已存在 " + code);
                    continue;
                }
                EvalQuestion row = new EvalQuestion();
                row.setUserId(userId);
                row.setCode(code);
                row.setType(type);
                row.setQuestion(question);
                row.setKeywords(cells.length > 3 ? cells[3].strip() : "");
                row.setEvidence(cells.length > 4 && !cells[4].isBlank() ? cells[4].strip() : null);
                row.setSource("import");
                row.setEnabled(Boolean.TRUE);
                repository.save(row);
                created++;
            } catch (ApiException error) {
                skipped++;
                errors.add("第 " + (i + 1) + " 行：" + error.getMessage());
            }
        }
        repository.flush();
        return new ImportResult(created, skipped, List.copyOf(errors));
    }

    /* ------------------------------------------------------------- 内部 */

    /** 该用户题库为空时，把内置种子复制一份进去。 */
    private void ensureSeeded(Long userId) {
        if (repository.countByUserId(userId) > 0) return;
        for (EvalQuestionVO q : seed) {
            EvalQuestion row = new EvalQuestion();
            row.setUserId(userId);
            row.setCode(q.id());
            row.setType(q.type());
            row.setQuestion(q.question());
            row.setKeywords(q.keywords() == null ? "" : q.keywords());
            row.setEvidence(q.evidence());
            row.setSource("seed");
            row.setEnabled(Boolean.TRUE);
            repository.save(row);
        }
        repository.flush();
    }

    /** 取当前用户的题；别人的题号一律 40408，不给「存在但不是你的」这种可枚举信号。 */
    private EvalQuestion owned(Long userId, String code) {
        return repository
                .findByUserIdAndCode(userId, code)
                .orElseThrow(
                        () ->
                                new ApiException(
                                        ErrorCode.QUESTION_NOT_FOUND.getCode(), "题目不存在: " + code));
    }

    /**
     * 生成下一个题号：按题型取前缀（single → S、cross → X、out → O），从 S001 起找第一个空位。
     *
     * <p>用独立前缀而不是接着 T 往下编，是为了让「内置题」与「自建题」在题号上一眼可分 —— 看到 S003 就知道是自己加的。
     */
    private String nextCode(Long userId, String type) {
        String prefix =
                switch (type) {
                    case TYPE_SINGLE -> "S";
                    case TYPE_CROSS -> "X";
                    default -> "O";
                };
        Set<String> taken = new TreeSet<>();
        repository.findAllOwnedBy(userId).forEach(q -> taken.add(q.getCode()));
        for (int i = 1; i < 100000; i++) {
            String candidate = prefix + String.format("%03d", i);
            if (!taken.contains(candidate)) return candidate;
        }
        throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "题号空间已用尽");
    }

    private String normalizeType(String raw) {
        String type = blank(raw) ? "" : raw.strip();
        if (!TYPES.contains(type)) {
            throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), "题型必须是 single / cross / out");
        }
        return type;
    }

    /** CSV 里的中文题型 → 内部码；已是内部码时原样返回。 */
    private String typeCode(String raw) {
        return switch (raw) {
            case "单文档", "单份资料可答" -> TYPE_SINGLE;
            case "跨文档", "需综合多篇" -> TYPE_CROSS;
            case "库外", "库外题" -> TYPE_OUT;
            default -> raw;
        };
    }

    private String typeLabel(String type) {
        return switch (type) {
            case TYPE_SINGLE -> "单文档";
            case TYPE_CROSS -> "跨文档";
            default -> "库外";
        };
    }

    private static String requireText(String raw, String message) {
        if (blank(raw)) throw new ApiException(ErrorCode.INVALID_PARAM.getCode(), message);
        return raw.strip();
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    /** CSV 单元格转义：含逗号/引号/换行时用双引号包裹并把内部引号翻倍。 */
    private static String csvCell(String value) {
        if (value == null) return "";
        boolean needQuote = value.contains(",") || value.contains("\"") || value.contains("\n");
        String escaped = value.replace("\"", "\"\"");
        return needQuote ? "\"" + escaped + "\"" : escaped;
    }

    private static EvalQuestionVO toVO(EvalQuestion row) {
        return new EvalQuestionVO(
                row.getCode(),
                row.getType(),
                row.getQuestion(),
                row.getKeywords() == null ? "" : row.getKeywords(),
                row.getEvidence(),
                row.getEnabled(),
                row.getSource());
    }

    /** 读 classpath 的种子 CSV（pom 已把 ../assets/eval 映射到 eval/）。 */
    private static List<EvalQuestionVO> loadSeed() {
        List<String[]> questions = readCsv("eval/questions.csv");
        List<String[]> keywords = readCsv("eval/keywords.csv");
        List<String[]> rows = keywords.isEmpty() ? questions : keywords;
        // 题目与关键词按题号合并：questions.csv 有题面、keywords.csv 有判分关键词。
        java.util.Map<String, String> keywordMap = new java.util.LinkedHashMap<>();
        for (String[] row : keywords) {
            if (row.length >= 2) keywordMap.put(row[0].strip(), row[1].strip());
        }
        List<EvalQuestionVO> result = new ArrayList<>();
        for (String[] row : questions) {
            if (row.length < 5) continue;
            String type =
                    switch (row[1].strip()) {
                        case "单文档" -> TYPE_SINGLE;
                        case "跨文档" -> TYPE_CROSS;
                        case "库外" -> TYPE_OUT;
                        default -> TYPE_SINGLE;
                    };
            result.add(
                    new EvalQuestionVO(
                            row[0].strip(),
                            type,
                            row[2].strip(),
                            keywordMap.getOrDefault(row[0].strip(), ""),
                            row[4].strip(),
                            Boolean.TRUE,
                            "seed"));
        }
        return List.copyOf(result);
    }

    private static List<String[]> readCsv(String path) {
        var stream = QuestionBankServiceImpl.class.getClassLoader().getResourceAsStream(path);
        if (stream == null) return List.of();
        try (var reader =
                new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            reader.readLine();
            return reader.lines()
                    .filter(line -> !line.isBlank())
                    .map(line -> line.split(",", -1))
                    .toList();
        } catch (Exception error) {
            throw new IllegalStateException("题库读取失败: " + path, error);
        }
    }
}
