"""一次性修复：把 InternalParseRequest 的 submission_key/generation 按正确缩进写回。"""

from pathlib import Path

path = Path("docs/api/openapi-internal.yaml")
lines = path.read_text(encoding="utf-8").splitlines()

start = next(i for i, line in enumerate(lines) if line.strip() == "InternalParseRequest:")
end = next(i for i, line in enumerate(lines) if line.strip() == "ParseAccepted:" and i > start)

block = [
    "    InternalParseRequest:",
    "      type: object",
    "      required: [documents, chunk_size, overlap, submission_key, generation]",
    "      additionalProperties: false",
    "      properties:",
    "        documents:",
    "          type: array",
    "          minItems: 1",
    "          items:",
    "            $ref: '#/components/schemas/ParseDocumentItem'",
    "        chunk_size:",
    "          type: integer",
    "          minimum: 50",
    "          maximum: 1000",
    "        overlap:",
    "          type: integer",
    "          minimum: 0",
    "        submission_key:",
    "          type: string",
    "          minLength: 1",
    "          description: 'Java 生成的用户级幂等键；同一用户同一 key 重试必须回到同一个 task_id。'",
    "        generation:",
    "          type: string",
    "          minLength: 1",
    "          description: 'Java 生成的索引代际；任务成功时用它决定当前生效片段。'",
    "",
]

out = lines[:start] + block + lines[end:]
path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
print("rewrote lines", start + 1, "..", end, "->", len(block), "lines")
