# 独立 Milvus 服务（可选）

> **本项目默认不使用这个目录。** 默认向量库是 **milvus-lite**（纯 Python 内嵌），
> 零额外依赖、数据落盘到单个文件。这里只在需要切换回独立 Milvus 服务时使用。

## 什么时候需要独立 Milvus

| 场景 | 建议 |
|---|---|
| 单机开发、语料 < 10 万切片 | **用默认的 milvus-lite 即可** |
| 需要多实例共享同一个向量库 | 需要独立 Milvus |
| 需要高可用 / 故障转移 | 需要独立 Milvus |
| 数据量 > 100 万切片 | 需要独立 Milvus 或专业方案 |
| 需要 Milvus 的索引类型（IVF/HNSW 调参） | 需要独立 Milvus |

## 代价

独立 Milvus 需要 **4 个容器**协同：

| 组件 | 作用 | 镜像大小 |
|---|---|---|
| `milvus` | 向量库主体 | ~3.9 GB |
| `etcd` | 元数据存储 | ~84 MB |
| `minio` | 对象存储 | ~383 MB |
| `attu` | Web 管理界面（可选） | ~496 MB |

合计约 **4.9 GB** 镜像，且必须按正确顺序启动（etcd / minio 就绪后 milvus 才能起来）。
而 milvus-lite 只需 `pip install milvus-lite`（约 100 MB），带 faiss-cpu。

## 切换方法

### 1. 启动 Milvus

```bash
cd infra/milvus
docker compose up -d
# 首次启动要建 meta、连 etcd/minio，约 40–60 秒才 healthy
docker ps | grep milvus
```

### 2. 修改向量库地址

编辑 `scripts/make_launchers.py`，把 `XIAOYI_MILVUS_URI` 换成 `MILVUS_URI`：

```python
# 改前（默认，milvus-lite）
"XIAOYI_MILVUS_URI": str(ROOT / "test-artifacts" / "milvus-lite" / "xiaoyi.db"),

# 改后（独立 Milvus 服务）
"MILVUS_URI": "http://127.0.0.1:19530",
```

> **为什么变量名要换**：`pymilvus 3.x` 在 import 阶段就会解析 `MILVUS_URI` 并强制校验必须是
> `http(s)://` 格式，传文件路径会直接抛 `ConnectionConfigException`。所以内嵌模式走
> `XIAOYI_MILVUS_URI`，由 `app/config.py` 的 `resolved_milvus_uri()` 读取。

### 3. 重新生成启动器并重启

```bash
python scripts/make_launchers.py
deploy/start-backend.bat
```

### 4. 重建索引

切换向量库后旧数据不会自动迁移，需要在页面「知识库」里重建，或调：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/index/rebuild \
  -H "Authorization: Bearer <token>"
```

## 文件说明

| 文件 | 内容 |
|---|---|
| `docker-compose.yml` | 4 个服务的编排定义 |
| `user.yaml` | Milvus 服务端配置（鉴权开关等）。**含明文 API key，已 gitignore，不入库** |
| `user.yaml.example` | 配置模板，占位符形式，可入库 |

## 关于服务端向量化（Function）

`user.yaml` 里原本配置了 `textEmbedding` / `rerank` provider，意图让 Milvus 服务端
在插入文本时自动调智谱 API 生成向量。**这段配置从未生效**，已移除，原因：

- Milvus Function 要求 `create_collection` 时显式声明 `function` 字段
- 本项目的建集合代码（`backend/ai-api/app/core/vector_store/store.py`）没有传
- 所以 Milvus 只当普通集合用，那两段 provider 配置是摆设

实际生效的是 **Python 侧自己算向量**（`backend/ai-api/app/core/rag/embedder.py`），
两者用同一个模型和 key，效果无差别。

若将来要启用服务端向量化，需先改造 `store.py` 在建集合时传 `function` 参数。
