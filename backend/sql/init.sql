-- AILOVE 初始化数据库脚本 (MySQL 8.0 / utf8mb4)
CREATE DATABASE IF NOT EXISTS `ailove`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `ailove`;

CREATE TABLE IF NOT EXISTS `users` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `username` VARCHAR(64) NULL COMMENT '登录用户名（管理员或可选别名）',
  `email` VARCHAR(191) NOT NULL COMMENT '规范化邮箱地址',
  `canonical_email` VARCHAR(191) NOT NULL COMMENT '去别名归一化邮箱（防同邮箱多注册）',
  `password_hash` VARCHAR(255) NOT NULL COMMENT 'bcrypt密码哈希',
  `nickname` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '用户昵称',
  `role` VARCHAR(32) NOT NULL DEFAULT 'user' COMMENT '角色: super_admin / admin / user',
  `register_source` VARCHAR(32) NOT NULL DEFAULT 'email_register' COMMENT '来源: email_register / admin_assigned / system_bootstrap',
  `email_provider` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '识别出的邮箱服务商',
  `email_trust_score` INT NOT NULL DEFAULT 100 COMMENT '邮箱可信度评分 (0-100)',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `created_by` BIGINT UNSIGNED NULL COMMENT '分配创建该用户的管理员ID',
  `last_login_at` DATETIME NULL COMMENT '最后登录时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`),
  UNIQUE KEY `uk_users_email` (`email`),
  UNIQUE KEY `uk_users_canonical_email` (`canonical_email`),
  KEY `idx_users_role_source` (`role`, `register_source`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='平台统一用户表';

CREATE TABLE IF NOT EXISTS `login_logs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` BIGINT UNSIGNED NULL COMMENT '用户ID',
  `account` VARCHAR(191) NOT NULL COMMENT '登录使用的账号或邮箱',
  `ip` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '客户端IP',
  `device_label` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '解析后的终端/浏览器描述',
  `user_agent` VARCHAR(512) NOT NULL DEFAULT '' COMMENT '原始User-Agent',
  `status` VARCHAR(16) NOT NULL DEFAULT 'success' COMMENT 'success / failed',
  `fail_reason` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '失败原因',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_login_logs_user_id` (`user_id`),
  KEY `idx_login_logs_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户登录安全审计日志表';

CREATE TABLE IF NOT EXISTS `admin_users` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `username` VARCHAR(64) NOT NULL COMMENT '管理员用户名',
  `password_hash` VARCHAR(255) NOT NULL COMMENT 'bcrypt密码哈希',
  `nickname` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '显示名称',
  `role` VARCHAR(32) NOT NULL DEFAULT 'admin' COMMENT '角色: super_admin / admin / operator',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `last_login_at` DATETIME NULL COMMENT '最后登录时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_admin_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='后台管理员表';

CREATE TABLE IF NOT EXISTS `wechat_users` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `openid` VARCHAR(64) NOT NULL COMMENT '微信 OpenID',
  `unionid` VARCHAR(64) NULL COMMENT '微信 UnionID',
  `nickname` VARCHAR(64) NOT NULL DEFAULT '微信用户' COMMENT '昵称',
  `avatar_url` VARCHAR(512) NOT NULL DEFAULT '' COMMENT '头像地址',
  `phone` VARCHAR(32) NULL COMMENT '手机号',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1正常 0禁用',
  `last_login_at` DATETIME NULL COMMENT '最后登录时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_wechat_users_openid` (`openid`),
  KEY `idx_wechat_users_unionid` (`unionid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='微信小程序用户表';

CREATE TABLE IF NOT EXISTS `ai_conversations` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `session_id` VARCHAR(64) NOT NULL COMMENT '会话唯一标识',
  `user_type` VARCHAR(16) NOT NULL DEFAULT 'miniapp' COMMENT '用户来源: admin / miniapp',
  `user_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联用户ID',
  `title` VARCHAR(128) NOT NULL DEFAULT '新对话' COMMENT '会话标题',
  `model_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '使用模型名',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ai_conversations_session_id` (`session_id`),
  KEY `idx_ai_conversations_user` (`user_type`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 对话会话表';

CREATE TABLE IF NOT EXISTS `ai_messages` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `conversation_id` BIGINT UNSIGNED NOT NULL COMMENT '关联会话ID',
  `role` VARCHAR(16) NOT NULL COMMENT '角色: system / user / assistant',
  `content` TEXT NOT NULL COMMENT '消息内容',
  `token_usage` INT NOT NULL DEFAULT 0 COMMENT 'Token 消耗估算',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_ai_messages_conversation_id` (`conversation_id`),
  CONSTRAINT `fk_ai_messages_conversation`
    FOREIGN KEY (`conversation_id`) REFERENCES `ai_conversations` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 对话消息记录表';

CREATE TABLE IF NOT EXISTS `ai_model_configs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `name` VARCHAR(64) NOT NULL COMMENT '配置展示名称',
  `provider` VARCHAR(32) NOT NULL DEFAULT 'deepseek' COMMENT '提供商标识: deepseek 等',
  `model_name` VARCHAR(64) NOT NULL DEFAULT 'deepseek-flash' COMMENT '模型标识',
  `base_url` VARCHAR(255) NOT NULL DEFAULT 'https://api.deepseek.com' COMMENT 'API 接口地址',
  `api_key_encrypted` TEXT NOT NULL COMMENT 'Fernet 加密存储的 API Key',
  `api_key_masked` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '脱敏展示的 API Key',
  `temperature` FLOAT NOT NULL DEFAULT 0.7 COMMENT '采样温度',
  `top_p` FLOAT NOT NULL DEFAULT 1.0 COMMENT '核采样 Top-P',
  `max_tokens` INT NOT NULL DEFAULT 4096 COMMENT '单次最大输出 Token',
  `timeout_seconds` INT NOT NULL DEFAULT 60 COMMENT '请求超时秒数',
  `max_history_messages` INT NOT NULL DEFAULT 20 COMMENT '多轮上下文保留消息条数',
  `system_prompt` TEXT NOT NULL COMMENT '默认系统人设提示词',
  `extra_params` TEXT NOT NULL COMMENT '预留扩展参数 JSON',
  `is_enabled` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为全局默认生效模型',
  `last_test_status` VARCHAR(16) NOT NULL DEFAULT 'untested' COMMENT 'untested / ok / failed',
  `last_test_latency_ms` INT NULL COMMENT '最近连通测试延迟(ms)',
  `last_test_message` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '最近测试结果描述',
  `last_tested_at` DATETIME NULL COMMENT '最近测试时间',
  `updated_by` BIGINT UNSIGNED NULL COMMENT '最后修改管理员ID',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_ai_model_configs_provider` (`provider`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 模型配置表';
