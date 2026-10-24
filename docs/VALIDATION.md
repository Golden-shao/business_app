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

## 开源治理与 AWS 部署准备（2026-10-25）

- GitHub 仓库可见性已从 private 改为 public，main 已配置 PR、检查、独立批准与禁止强推规则；当前远端状态需以 GitHub 设置为准。
- 初次公开前扫描了现有 3 个提交、115 个唯一 blob：未发现本地令牌、常见云密钥标记或私钥块；这不是完整安全审计。
- 后端与云配置单元测试 19 项通过；新增测试验证云端 TLS 路由结构、不可变镜像、占位/注入输入拒绝及凭证初始化权限与幂等性。
- Terraform 1.13.4 / AWS provider 6.70.0：fmt、validate 与 4 项 mock-provider plan 测试通过；未使用 AWS 账户或创建实际资源。
- 渲染出 12 项云资源；其中 10 项标准 Kubernetes 资源通过 1.35.0 严格 schema 校验。ClusterIssuer 与 Traefik Middleware 为额外 CRD，仅验证生成结构，没有据此宣称真实控制器工作。
- 独立审查门禁的 2 项 Node 测试通过，直接执行 workflow 中的判定代码，覆盖正式批准、评论、旧 head、伪造用户、撤销和新 findings。
- 尚无 AWS 账户、已确认域名或部署预算，未完成 EC2 实机、DNS、受信任证书、SSM 或公网网站验收。
- Codex 自动审查仍需要在用户账户中接入并验证；没有真实 Bot 对当前提交的 APPROVED，AI 门禁保持阻止状态。不能把这份报告当作独立批准。
