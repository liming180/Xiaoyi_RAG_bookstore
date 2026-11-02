package com.xiaoyi.rag.service;

import java.io.IOException;
import java.io.InputStream;

/**
 * 文件落盘抽象。
 *
 * <p>J2 只要求本地磁盘实现（{@code LocalStorage}）；J4/A1 接入对象存储时换实现即可， Service 层只依赖本接口。
 *
 * <p>路径规则：{@code {root}/{documentId}/{filename}}，{@code storageKey} 存相对 root 的路径， 不存绝对路径（换机器不用改库）。
 */
public interface Storage {

    /**
     * 写入一份资料。
     *
     * @param documentId 资料 id，作为一级目录
     * @param filename 已做过 {@code Path#getFileName()} 截断的纯文件名
     * @param content 文件字节
     * @return 相对 root 的 storageKey，形如 {@code 12/01_活动说明.md}
     */
    String store(long documentId, String filename, byte[] content) throws IOException;

    /**
     * 读取一份资料。
     *
     * @param storageKey {@link #store} 返回的相对路径
     */
    InputStream read(String storageKey) throws IOException;

    /** 是否存在。 */
    boolean exists(String storageKey);

    /** 删除该资料所在目录下的全部文件（整个 {@code {documentId}/} 目录）。 */
    boolean deleteByDocumentId(long documentId) throws IOException;

    /** 删除单个 storageKey 指向的文件。 */
    boolean delete(String storageKey) throws IOException;

    /** 存储根目录的绝对路径（供测试断言磁盘上真的写出了文件）。 */
    String rootPath();
}
