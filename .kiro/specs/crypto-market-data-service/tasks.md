# Implementation Plan: Crypto Market Data Service

## Overview

本实现计划将设计文档转化为可执行的编码任务。采用增量开发方式，每个任务构建在前一个任务的基础上。

## Tasks

- [x] 1. 项目初始化和基础设施
  - [x] 1.1 创建项目结构和依赖配置
    - 使用 uv 初始化项目
    - 创建 `pyproject.toml` 配置依赖
    - 创建目录结构：`src/`, `tests/`, `alembic/`
    - _Requirements: 技术栈要求_

  - [x] 1.2 实现配置模块
    - 创建 `src/config.py`
    - 实现 `ExchangeConfig` 和 `Settings` 类
    - 实现 `@lru_cache` 的 `get_settings()` 函数
    - 创建示例 `.env.example` 和 `config.yaml.example`
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 1.3 实现异常模块
    - 创建 `src/exceptions.py`
    - 实现 `ErrorCode` 枚举
    - 实现 `MarketDataError`, `ClientError`, `ServerError`, `RateLimitError`
    - _Requirements: 1.3, 2.2_

- [x] 2. 数据模型和数据库
  - [x] 2.1 实现领域模型
    - 创建 `src/models.py`
    - 实现 `OHLCV` SQLAlchemy 模型（含 `to_dict()`, `from_dict()`, `__eq__()`）
    - 实现 `Ticker` dataclass（含 `to_dict()`, `from_dict()`）
    - _Requirements: 1.6, 2.4, 8.1_

  - [ ]* 2.2 编写 OHLCV 序列化属性测试
    - **Property 1: OHLCV Serialization Round-Trip**
    - **Validates: Requirements 1.6**

  - [ ]* 2.3 编写 Ticker 序列化属性测试
    - **Property 2: Ticker Serialization Round-Trip**
    - **Validates: Requirements 2.4**

  - [x] 2.4 配置 Alembic 和创建初始迁移
    - 创建 `alembic.ini` 和 `alembic/env.py`
    - 创建初始迁移脚本 `001_initial.py`
    - 包含 OHLCV 表、唯一约束、索引
    - _Requirements: 8.1_

- [x] 3. 基础设施层
  - [x] 3.1 实现数据库连接模块
    - 创建 `src/infrastructure/database.py`
    - 实现 `Database` 类（异步引擎、会话工厂、健康检查）
    - _Requirements: 8.1, 7.1_

  - [x] 3.2 实现缓存模块
    - 创建 `src/infrastructure/cache.py`
    - 实现 `Cache` 类（OHLCV 缓存、Ticker 缓存、健康检查）
    - 使用 Redis Sorted Set 存储 OHLCV
    - 使用 Redis String + TTL 存储 Ticker
    - _Requirements: 8.3, 8.4, 8.5_

  - [ ]* 3.3 编写缓存大小限制属性测试
    - **Property 7: Cache Size Limit**
    - **Validates: Requirements 8.3**

  - [x] 3.4 实现交易所客户端模块
    - 创建 `src/infrastructure/exchange.py`
    - 实现 `ExchangeClient` 类（CCXT 封装）
    - 实现 `fetch_ohlcv()` 和 `fetch_ticker()` 方法
    - 处理 RateLimitExceeded 异常
    - _Requirements: 4.1, 4.4, 4.5_

- [x] 4. Repository 层
  - [x] 4.1 实现 OHLCV Repository
    - 创建 `src/repositories.py`
    - 实现 `OHLCVRepository` 类
    - 实现 `save()` 方法（批量 upsert）
    - 实现 `find()` 方法（缓存优先、游标分页）
    - _Requirements: 1.1, 1.2, 8.1, 8.2, 8.3_

  - [ ]* 4.2 编写 Upsert 幂等性属性测试
    - **Property 3: Upsert Idempotence**
    - **Validates: Requirements 8.1, 8.2**

  - [ ]* 4.3 编写分页完整性属性测试
    - **Property 4: Pagination Completeness**
    - **Validates: Requirements 1.2**

  - [ ]* 4.4 编写查询过滤正确性属性测试
    - **Property 5: Query Filtering Correctness**
    - **Validates: Requirements 1.1**

  - [x] 4.5 实现 Ticker Repository
    - 实现 `TickerRepository` 类
    - 实现 `save()`, `find()`, `find_all()` 方法
    - 缓存未命中时从交易所获取
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 5. 依赖注入模块
  - [x] 5.1 实现依赖注入
    - 创建 `src/dependencies.py`
    - 实现 `get_db()`, `get_cache()`, `get_exchange_clients()` 等依赖函数
    - 实现 `get_db_session()` 会话依赖
    - 实现 `validate_exchange()`, `validate_symbol()`, `validate_timeframe()` 验证依赖
    - 定义类型别名 `DbSession`, `OHLCVRepo`, `TickerRepo` 等
    - _Requirements: 1.3, 2.2_

- [ ] 6. API 层
  - [x] 6.1 修复 API Schemas
    - 更新 `src/api/schemas.py`
    - 添加缺失的 schema 类：`PaginationInfo`, `OHLCVListMeta`, `TickerMeta`, `BatchErrorItem`, `BatchResponse`
    - 确保所有 API 路由使用的 schema 都已定义
    - _Requirements: 1.5, 2.4, 3.2_

  - [x] 6.2 实现 OHLCV 路由
    - 创建 `src/api/ohlcv.py`
    - 实现 `GET /api/v1/ohlcv/{exchange}/{symbol}` 端点
    - 实现 `POST /api/v1/ohlcv/batch` 端点
    - 使用依赖注入的 session
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 3.2, 3.3, 3.4_

  - [ ]* 6.3 编写批量部分失败属性测试
    - **Property 6: Batch Partial Failure**
    - **Validates: Requirements 3.2**

  - [x] 6.4 实现 Ticker 路由
    - 创建 `src/api/ticker.py`
    - 实现 `GET /api/v1/ticker/{exchange}/{symbol}` 端点
    - 实现 `GET /api/v1/tickers/{exchange}` 端点
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 6.5 实现健康检查路由
    - 创建 `src/api/health.py`
    - 实现 `GET /health` 端点
    - 检查 PostgreSQL、Redis、交易所连接状态
    - _Requirements: 7.1, 7.2_

  - [ ]* 6.6 编写健康状态映射属性测试
    - **Property 8: Health Status Mapping**
    - **Validates: Requirements 7.1, 7.2**

- [x] 7. 应用入口和生命周期
  - [x] 7.1 实现应用入口
    - 创建 `src/main.py`
    - 实现 `lifespan` 上下文管理器
    - 初始化所有组件到 `app.state`
    - 注册路由和异常处理器
    - _Requirements: 4.1, 6.1_

- [x] 8. 调度器和数据采集
  - [x] 8.1 实现调度器
    - 创建 `src/infrastructure/scheduler.py`
    - 实现 `CollectionScheduler` 类
    - 实现 OHLCV 采集任务（按 timeframe 间隔）
    - 实现 Ticker 采集任务（10秒间隔）
    - 实现 rate limit 暂停机制
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 8.2 集成调度器到应用生命周期
    - 在 `src/main.py` 的 `lifespan` 中启动调度器
    - 在应用关闭时停止调度器
    - _Requirements: 4.1_

- [ ] 9. Checkpoint - 基础功能验证
  - 确保所有 API 端点可以正常工作
  - 手动测试 OHLCV 和 Ticker 查询
  - 检查健康检查端点
  - 如有问题，询问用户

- [ ] 10. 测试基础设施
  - [ ] 10.1 创建测试配置和 fixtures
    - 创建 `tests/conftest.py`
    - 实现 PostgreSQL 和 Redis testcontainers fixtures
    - 实现数据库引擎、会话、缓存 fixtures
    - 实现 API 客户端 fixture
    - _Requirements: 测试策略_

  - [ ] 10.2 创建 Hypothesis 测试策略
    - 创建 `tests/property/strategies.py`
    - 实现 `ohlcv_strategy()` 生成器
    - 实现 `ticker_strategy()` 生成器
    - 实现 `time_range_strategy()` 生成器
    - _Requirements: 测试策略_

- [ ] 11. 属性测试实现
  - [ ]* 11.1 编写序列化属性测试
    - 创建 `tests/property/test_serialization.py`
    - 实现 Property 1: OHLCV Serialization Round-Trip
    - 实现 Property 2: Ticker Serialization Round-Trip
    - _Requirements: 1.6, 2.4_

  - [ ]* 11.2 编写 Repository 属性测试
    - 创建 `tests/property/test_repository.py`
    - 实现 Property 3: Upsert Idempotence
    - 实现 Property 4: Pagination Completeness
    - 实现 Property 5: Query Filtering Correctness
    - _Requirements: 1.1, 1.2, 8.1, 8.2_

  - [ ]* 11.3 编写缓存属性测试
    - 创建 `tests/property/test_cache.py`
    - 实现 Property 7: Cache Size Limit
    - _Requirements: 8.3_

  - [ ]* 11.4 编写 API 属性测试
    - 创建 `tests/property/test_api.py`
    - 实现 Property 6: Batch Partial Failure
    - 实现 Property 8: Health Status Mapping
    - _Requirements: 3.2, 7.1, 7.2_

- [ ] 12. 集成测试实现
  - [ ]* 12.1 编写 Repository 集成测试
    - 创建 `tests/integration/test_repository.py`
    - 测试 OHLCV 保存和查询
    - 测试 upsert 更新已存在记录
    - 测试分页功能
    - _Requirements: 8.1, 8.2_

  - [ ]* 12.2 编写 API 集成测试
    - 创建 `tests/integration/test_api.py`
    - 测试 OHLCV 查询端点
    - 测试 Ticker 查询端点
    - 测试批量查询端点
    - 测试健康检查端点
    - 测试错误处理
    - _Requirements: 1.1, 2.1, 3.1, 7.1_

- [ ] 13. 单元测试实现
  - [ ]* 13.1 编写模型单元测试
    - 创建 `tests/unit/test_models.py`
    - 测试 OHLCV to_dict/from_dict
    - 测试 Ticker to_dict/from_dict
    - 测试精度保留
    - _Requirements: 1.6, 2.4_

  - [ ]* 13.2 编写配置单元测试
    - 创建 `tests/unit/test_config.py`
    - 测试配置加载
    - 测试环境变量覆盖
    - 测试 YAML 配置加载
    - _Requirements: 6.1, 6.2, 6.3_

- [ ] 14. Final Checkpoint - 完整验证
  - 运行所有测试（单元、集成、属性）
  - 确保所有功能正常工作
  - 检查代码覆盖率
  - 如有问题，询问用户

## Notes

- 标记 `*` 的任务是可选的测试任务，可以跳过以加快 MVP 开发
- 每个任务引用具体的需求条款以确保可追溯性
- Checkpoint 任务用于验证阶段性成果
- 属性测试验证设计文档中定义的正确性属性
- 核心实现已完成，主要剩余工作是修复 API schemas 和实现测试
