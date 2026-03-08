# TSingBox

基于 `Textual` 的 `sing-box` 终端客户端（TUI），支持：

- 订阅拉取与节点管理
- 路由与 DNS 偏好配置
- Cloudflare WARP 账户生成与落地
- 生成运行时配置并重启 `sing-box`
- 启动时先渲染 TUI，再后台执行 `sing-box` 检查与已选节点自动应用
- Dashboard / footer / logs 实时显示启动阶段与应用进度
- 全局 apply 互斥，避免启动自动应用、手动应用、节点切换应用并发冲突
- 内存日志 + 文件日志（`~/.config/tsingbox/logs/app.log`）

## 环境要求

- Python >= 3.11
- `uv`
- 本机可执行 `sing-box`（用于应用配置时重启进程）

## 快速开始

```bash
uv sync --extra dev
uv run python -m tsingbox
```

## 测试

```bash
uv run --extra dev pytest
```

## 项目结构

- `src/tsingbox/app.py`：应用入口与组件装配
- `src/tsingbox/ui/`：Textual 界面
- `src/tsingbox/services/`：业务逻辑（订阅、WARP、配置构建、进程控制）
- `src/tsingbox/data/`：SQLite 与仓储层
- `tests/`：测试用例

## 设计文档

详细设计请见 `spec.md`。
