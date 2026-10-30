"""星河读书会个人资料助手 —— 应用包。

模块划分：
    settings   配置、路径、密钥（只存内存/环境变量）
    chunking   滑窗分块、资料读取、manifest
    embedding  嵌入（真实接口 / 离线模拟）
    retrieval  余弦相似度、top-k、全量 trace
    prompting  系统提示词、参考资料拼装、可信度标注、引用校验
    llm        对话接口调用（真实 / 离线模拟）
    judging    关键词初判、题目读取
    store      index.json 读写与校验、日志
    session    会话状态（history / mode / k / 清空）
    chat       一轮问答编排
    batch      批量对照测试与 CSV 导出
    api        FastAPI 路由
"""

__all__ = [
    "settings", "chunking", "embedding", "retrieval", "prompting",
    "llm", "judging", "store", "session", "chat", "batch", "api",
]
