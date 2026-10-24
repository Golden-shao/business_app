# v0.1 本地验证记录

日期：2026-10-25（Asia/Shanghai）。这是本地结果，不表示 GitHub Actions 已执行。

| 范围 | 验证结果 |
| --- | --- |
| 后端 | `PYTHONPATH=gateway python -m pytest gateway/tests -q`：10 passed |
| Flutter | 格式化通过，`flutter analyze` 无问题，`flutter test` 2 passed |
| Flutter 网页 | `flutter build web` 成功；Chrome 实际连接真实后端并发送模拟 completion |
| HTML 网站 | Chrome 自动化通过连接、发送、缓存命中、独立调用客户端联动、断开清除、390px 窄屏；无 JS 异常 |
| 真实共享状态 | 两个独立 Uvicorn 进程连接同一个本机 Redis，第二个进程命中第一个进程写入的缓存，统计和历史相同 |
| Docker | 通过 Windows Docker Desktop 引擎实际构建 Linux 镜像；容器内 UID 为 10001 |
| Compose | 在独立项目 `harbor-agent-qa`、端口 18000 启动，健康检查、网站、completion、缓存与统计通过，测试资源随后清理 |
| Kubernetes 文件 | kubectl 1.35.0 Kustomize 构建成功；kubeconform 0.7.0 对 1.35.0 严格 schema 校验：8 valid、0 invalid、0 skipped |
| 本地凭证 | `.env` 和 `.local/` 确认被 Git 忽略；未输出实际令牌 |

主要环境：WSL2 Ubuntu 24.04、Python 3.12、Flutter 3.47.8 / Dart 3.13.7、Linux Chrome 156；真实本机 Redis 7.0，Compose Redis 7.4。

## 尚未验证

- Kubernetes 集群部署、PVC 实际绑定、滚动更新、NetworkPolicy 实施与 HPA 自动扩缩。schema 有效不代表集群运行成功。
- macOS/Xcode 编译、iPhone 真机、签名和 App Store 发布。Flutter web 验证不替代 iOS 验证。
- 真实付费模型供应商。上游协议转发、错误脱敏通过 HTTP mock 测试，没有发送付费请求。
- GitHub Actions 在线运行与远程发布。本次修改留在本地工作区，未推送仓库。

测试环境中 Starlette TestClient 对 HTTPX 0.28 的兼容路径给出一条弃用提示，测试均通过；后续升级测试依赖时应一并迁移。

## v0.1.1 产品体验增量（2026-10-25）

- 后端：12 项通过，新增请求来源、失败请求 ID 和跨域限流头测试。
- Flutter：静态分析无问题，9 项测试通过，覆盖自动同步、后台暂停/恢复、断开清理、限流倒计时、HTML 错误响应，以及成功回复后的同步失败不触发重发。
- `flutter build web` 成功。
- 网页：`scripts/test_site.py` 浏览器验收通过。覆盖首次使用引导、独立 API 客户端的自动联动、暂停开关、页面隐藏/恢复、限流后恢复按钮但不重发、503 旧快照提示和恢复、完整请求 ID、390px 布局及断开清理。
- 浏览器验收使用独立 FakeRedis 与 mock 模型，不读取 `.env`。可选截图保存在被 Git 忽略的 `.local/`。
- CI 已加入同一网页验收脚本，在线运行仍需推送后确认。本轮未重复执行容器与 K8s 验证；相应记录见上方 v0.1 基线，iOS 真机与集群运行仍待验证。
