# Sing-Box TUI 客户端详细设计文档

## 1. 项目概述

本项目旨在开发一个基于 `sing-box` 内核的终端用户界面（TUI）客户端。通过现代化的 Python 技术栈与异步设计，提供订阅管理、节点选择、路由与 DNS 分流配置，并原生支持生成 Cloudflare WARP 账户以构建链式代理（Chain Proxy）落地功能。

## 2. 技术栈选型

为了保证高性能与现代化开发体验，采用以下核心技术与依赖：

| 组件类别 | 技术/依赖库 | 说明 |
| --- | --- | --- |
| **包管理/环境** | `uv` | Rust 编写的极速 Python 包与环境管理器。 |
| **UI 框架** | `textual` | 支持响应式布局、CSS 样式与异步事件的现代 TUI 框架。 |
| **数据校验/序列化** | `pydantic` | 用于构建符合 `sing-box` 规范的 JSON 配置模型，保证类型安全。 |
| **网络请求** | `httpx` | 异步 HTTP 客户端，用于订阅下载、节点测速与 WARP 注册。 |
| **加密运算** | `cryptography` | 用于本地生成 WireGuard (X25519) 密钥对。 |
| **本地存储** | `sqlite3` + `aiosqlite` | 轻量级关系型数据库，存储订阅链接、节点数据与 WARP 凭证。 |

---

## 3. 核心架构设计

系统分为四个解耦的层级，确保界面的流畅与内核的稳定运行：

### 3.1 展现层 (Presentation Layer)

* **Main App (Textual App):** 统筹应用的生命周期与路由（界面的切换）。
* **组件划分:**
* **侧边栏 (Sidebar):** 提供导航（仪表盘、订阅、节点、路由、WARP 设置）。
* **内容区 (Content View):** 动态渲染数据列表（数据表、输入框、日志终端）。
* **状态栏 (Footer):** 显示按键绑定与 `sing-box` 运行状态（Running / Stopped）。



### 3.2 业务逻辑层 (Business Logic Layer)

* **Subscription Manager:** 负责异步拉取、解析订阅数据，提取协议信息。
* **Config Builder:** 核心枢纽。读取用户的数据库配置，通过 `Pydantic` 模型组装并输出最终的 `config.json`。
* **WARP Generator:** 基于 `httpx` 与 `cryptography`，原生模拟 `wgcf` 注册流程，获取 WARP 凭证并落库。

### 3.3 进程控制层 (Daemon Layer)

* **Singbox Controller:** 封装 `asyncio.create_subprocess_exec`。负责启动 `sing-box` 进程，监控进程状态，并捕获标准输出流（stdout）反馈到 TUI 的日志界面。

### 3.4 数据持久层 (Data Access Layer)

* 使用 SQLite 存储持久化数据。

---

## 4. 数据表结构设计 (SQLite)

系统主要包含以下四张核心表：

* **`subscriptions` (订阅表):**
* `id`: 主键
* `name`: 订阅名称
* `url`: 订阅链接
* `last_update`: 上次更新时间


* **`nodes` (节点表):**
* `id`: 主键
* `sub_id`: 关联订阅 ID
* `tag`: 节点标签 (用于 sing-box outbound tag)
* `protocol`: 协议类型 (vless, trojan 等)
* `config_json`: 节点具体的 JSON 配置（序列化存储）
* `ping_delay`: 最近测速延迟


* **`warp_accounts` (WARP 凭证表):**
* `id`: 主键 (单例存储)
* `private_key`: 本地生成的私钥
* `local_address_v4`: 分配的 IPv4
* `local_address_v6`: 分配的 IPv6
* `reserved`: 计算出的 3 字节保留数组 (例如 `[10, 20, 30]`)


* **`preferences` (用户设置):**
* 存储当前选中的节点 ID、路由模式（全局/规则）、DNS 防泄漏开关等。



---

## 5. 核心工作流解析

### 5.1 WARP 链式代理装配流 (Chain Proxy Workflow)

此工作流是实现节点请求转发至 Cloudflare WARP 的关键。

1. **用户操作:** 用户在 TUI 选中节点 A，并开启 "通过 WARP 落地" 开关，点击应用。
2. **读取数据:** `Config Builder` 从数据库读取节点 A 的配置，并读取 `warp_accounts` 的凭证。
3. **构造 Outbounds (Pydantic):**
* 构造基础的出站节点：类型 `vless`/`trojan`，`tag` 为 `proxy-node`。
* 构造 WARP 出站节点：类型 `wireguard`，`tag` 为 `warp-outbound`，填入凭证数据。
* **核心纽带:** 将 WARP 节点的 `detour` 字段设置为 `proxy-node`。


4. **构造 Route:** 将默认规则或目标路由指向 `warp-outbound`。
5. **生成与重启:** 序列化为 `config.json`，调用 `Singbox Controller` 停止旧进程，带新配置启动。

### 5.2 订阅解析流 (Subscription Flow)

1. **输入:** 用户在界面输入订阅 URL。
2. **下载:** `httpx` 异步获取响应文本。
3. **解码:** 识别 Base64 并解码，按行分割。
4. **协议解析:** 针对 `vless://`, `trojan://` 等前缀编写解析函数，转换为 `sing-box` 标准 Outbound 字典。
5. **落库:** 插入 `nodes` 表，触发 UI 节点列表组件更新。

---

## 6. 潜在挑战与应对方案

* **TUI 界面阻塞 (UI Freezing):**
* *挑战:* 测速、网络请求和配置解析如果是同步阻塞的，会导致 Textual 界面无响应。
* *应对:* 严格遵守 Textual 的异步范式。使用 Textual 的 `@work` 装饰器派发后台任务，配合 `httpx` 和 `asyncio`。


* **Sing-box 僵尸进程:**
* *挑战:* TUI 异常退出时，后台的 `sing-box` 子进程可能仍在运行，导致端口占用。
* *应对:* 在 Python 中注册退出信号处理（`atexit` 或捕获 `SIGINT`/`SIGTERM`），确保在应用销毁前调用 `process.terminate()`。


* **复杂配置校验:**
* *挑战:* 漏填字段导致 sing-box 内核启动报错。
* *应对:* Pydantic 模型作为唯一真相源（Source of Truth）。在写入 `config.json` 前，必须通过 Pydantic 的 `.model_validate()`，捕获并向用户展示清晰的校验错误日志。



---

开发这样一个客户端，定义好数据结构是成功的一半。

**需要我为你提供基于 Pydantic 的 `sing-box` 核心 Outbound（特别是包含 Detour 的链式代理结构）的数据模型代码吗？** 它可以直接作为你项目 `Config Builder` 模块的地基。