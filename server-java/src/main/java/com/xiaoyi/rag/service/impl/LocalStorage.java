package com.xiaoyi.rag.service.impl;

import com.xiaoyi.rag.config.XiaoyiProperties;
import com.xiaoyi.rag.service.Storage;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.Comparator;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 本地磁盘存储实现。
 *
 * <p>根目录取 {@code xiaoyi.storage.root}（默认 {@code ./storage}），路径 {@code
 * {root}/{documentId}/{filename}}。
 *
 * <p>所有路径都先 {@code normalize()} 再 {@code startsWith(rootAbs)} 校验， 保证任何情况下都写不出根目录之外（防路径穿越的最后一道闸）。
 */
@Service
public class LocalStorage implements Storage {

    private static final Logger log = LoggerFactory.getLogger(LocalStorage.class);

    private final Path root;

    public LocalStorage(XiaoyiProperties properties) {
        this.root = Paths.get(properties.getStorage().getRoot()).toAbsolutePath().normalize();
    }

    @Override
    public String store(long documentId, String filename, byte[] content) throws IOException {
        Path dir = resolveDir(documentId);
        Files.createDirectories(dir);
        Path target = guard(dir.resolve(filename));
        Files.write(target, content);
        return documentId + "/" + filename;
    }

    @Override
    public InputStream read(String storageKey) throws IOException {
        return Files.newInputStream(guard(root.resolve(storageKey)));
    }

    @Override
    public boolean exists(String storageKey) {
        if (storageKey == null || storageKey.isBlank()) {
            return false;
        }
        return Files.exists(guard(root.resolve(storageKey)));
    }

    @Override
    public boolean deleteByDocumentId(long documentId) throws IOException {
        Path dir = resolveDir(documentId);
        if (!Files.exists(dir)) {
            return false;
        }
        try (Stream<Path> walk = Files.walk(dir)) {
            // 逆序删除：先文件后目录
            walk.sorted(Comparator.reverseOrder())
                    .forEach(
                            p -> {
                                try {
                                    Files.deleteIfExists(p);
                                } catch (IOException e) {
                                    log.warn("删除失败，跳过：{} - {}", p, e.getMessage());
                                }
                            });
        }
        return true;
    }

    @Override
    public boolean delete(String storageKey) throws IOException {
        if (storageKey == null || storageKey.isBlank()) {
            return false;
        }
        Path target = guard(root.resolve(storageKey));
        boolean removed = Files.deleteIfExists(target);
        // 顺手清空空的父目录，避免 storage/ 下留一堆空壳
        Path parent = target.getParent();
        if (parent != null && !parent.equals(root) && Files.isDirectory(parent)) {
            try (Stream<Path> children = Files.list(parent)) {
                if (children.findAny().isEmpty()) {
                    Files.deleteIfExists(parent);
                }
            }
        }
        return removed;
    }

    @Override
    public String rootPath() {
        return root.toString();
    }

    /** 移动：覆盖写入（去重命中时用）。 */
    public void copyInto(Path source, long documentId, String filename) throws IOException {
        Path dir = resolveDir(documentId);
        Files.createDirectories(dir);
        Files.copy(source, guard(dir.resolve(filename)), StandardCopyOption.REPLACE_EXISTING);
    }

    private Path resolveDir(long documentId) {
        return guard(root.resolve(String.valueOf(documentId)));
    }

    /** 归一化后必须仍在 root 之内，否则直接拒绝。 */
    private Path guard(Path candidate) {
        Path normalized = candidate.toAbsolutePath().normalize();
        if (!normalized.startsWith(root)) {
            throw new IllegalArgumentException("路径越界：" + candidate);
        }
        return normalized;
    }
}
