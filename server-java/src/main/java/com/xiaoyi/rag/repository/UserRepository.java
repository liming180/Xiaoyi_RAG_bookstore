package com.xiaoyi.rag.repository;

import com.xiaoyi.rag.model.entity.User;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/** 用户仓储。J2 只用于把 token 里的 userId 校验成真实用户。 */
@Repository
public interface UserRepository extends JpaRepository<User, Long> {

    Optional<User> findByUsername(String username);
}
