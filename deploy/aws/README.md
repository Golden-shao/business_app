# AWS 虚拟机 + K3s + HTTPS 部署草案

此目录是**新建 Ubuntu EC2 的可审查配置，不是已经上线的网站**。现已提供一台 Amazon Linux 2023 EC2，但 SSH 尚未连通；本模块不会接管或重建那台已有实例。未运行真实 `terraform plan/apply`，未创建额外收费资源或签发证书。默认单机，不能承诺高可用 SLA。

## 先完成账户与成本准备

1. 自行通过 [AWS 官方注册流程](https://docs.aws.amazon.com/accounts/latest/reference/getting-started.html) 完成邮箱、付款方式和手机号验证。本项目的 EC2/IAM/Budgets 部署需要能使用这些服务的标准 AWS 账户；不要把验证码、银行卡、root 密码或访问密钥发到聊天或仓库。
2. 启用 MFA，通过 IAM Identity Center/短期凭证配置部署者权限；日常部署不使用 root 凭证。
3. 选定区域、拥有一个可修改 DNS 的域名，并确认每月最高可接受费用。示例 `monthly_budget_usd=0` 会阻止部署，必须自行填写正数。预算通知只是告警，**不会自动停止费用**。
4. 估价需包含 EC2、30GiB gp3 磁盘、公网 IPv4、网络流出与域名。不能把“有免费额度”当成永久免费。IPv4 官方公开标价为每地址每小时 $0.005，实际优惠与地区、账户计划另查：[VPC pricing](https://aws.amazon.com/vpc/pricing/)。

配置使用一个 t3.medium（2 vCPU / 4GiB）起步，实际可用容量和费用需在选定区域确认。K3s 官方最低服务端要求为 2 核/2GiB，不包含应用负载：[requirements](https://docs.k3s.io/installation/requirements)。此处没有 EKS 控制面或 NAT Gateway。

## 架构

```text
https://你拥有的域名:443
  → EC2 安全组（仅公网 TCP 80/443）
  → K3s Traefik + cert-manager / Let's Encrypt
  → ClusterIP Service → 网关 Pods → 私有 Redis PVC
管理：AWS Systems Manager Session Manager；不开公网 SSH / 6443 / Redis / NodePort
```

外部地址不含 `:8000` 或 `:8080`。HTTP 会重定向到 HTTPS；80 仍用于 ACME HTTP-01 验证。内部服务继续使用 8000 是正常的服务网络配置，不决定服务是否正式可用。

## 发布前置条件

- 本 PR 已通过审查并合并到 main。
- 手动运行 `Publish reviewed gateway image` workflow，记录 Summary 中的 `ghcr.io/...@sha256:...`。
- 首次 GHCR 发布后，检查 package 的可见性，确认镜像可匿名拉取；公开仓库不等于 package 必然公开。当前配置不把 registry 密码放进云主机。
- `release_commit` 必须是包含部署脚本的、已审查合并的完整 commit SHA。`gateway_image` 必须来自该发布的 digest，不接受 `latest`。`ami_id` 必须是区域内经过审阅的固定 Ubuntu 24.04 AMI；不自动选择最新镜像，避免上游发布镜像导致状态盘被意外替换。

## 在有凭证的受信任终端操作

```bash
cd deploy/aws
cp terraform.tfvars.example terraform.tfvars
# 用编辑器填写区域、固定 AMI、域名、邮箱、预算、commit 和镜像 digest。
terraform init
terraform plan -out=reviewed.tfplan
# 先审阅费用、区域、资源数量、权限和输出，再由账户持有人批准执行。
terraform apply reviewed.tfplan
```

不要自动运行 `apply`。当前还没有确认预算与域名。Terraform state、plan、tfvars 已加入 Git 忽略；团队协作前应迁移到加密、有访问控制和锁的远程 state。

启动脚本安装已固定版本的 K3s/cert-manager，拉取固定 commit，并在 VM 本地生成随机凭证。令牌保存在 root-only `/etc/harbor/access.env` 和 Kubernetes Secret，不写入 Terraform 输入、user-data 或输出。公开配置默认 mock 上游、关闭回复缓存，不产生真实模型费用。

## DNS、凭证和上线验收

1. 将你域名的 A 记录指向 `terraform output -raw public_ip`。不要添加不可达的 AAAA 记录。
2. 在 AWS 控制台使用 Session Manager 连接实例，查看 `/var/log/harbor-bootstrap.log` 和 `sudo k3s kubectl -n harbor get pods,pvc,ingress`。
3. 等待 `sudo k3s kubectl -n harbor wait --for=condition=Ready certificate/harbor-tls --timeout=300s`。首次 DNS 未生效可能需要重试；查看 `kubectl get challenges,orders -n harbor` 排错。若先测试 ACME，使用渲染脚本的 `--staging`；staging 证书不受浏览器信任，正式上线须切换生产 issuer。
4. 只在自己的受信任 SSM 会话中读取 `/etc/harbor/access.env`，将 ADMIN_TOKEN 填入 HTTPS 网站或 App。不要公开截图此文件。
5. 从公网验证 HTTP 重定向、受信任证书、网页、`/health/ready`，以及带调用令牌的模拟请求；随后验证 App 联动。不要用 `curl -k` 的结果宣称正式 TLS 验证通过。
6. 在本机确认 22、6443、6379、8000、8080 和 NodePort 没有暴露到公网。安全组只允许 80/443，K8s NetworkPolicy 限制网关流量来自 Traefik。

渲染器只生成配置，不部署资源：

```bash
python3 scripts/render_cloud.py --domain 你拥有的域名 --email 你的联系邮箱 \
  --image ghcr.io/你的命名空间/镜像@sha256:已发布的完整digest > cloud.json
```

## 维护、升级、数据与回滚

- 先在独立环境验证新镜像，再用 `kubectl -n harbor set image deployment/gateway gateway=完整digest` 更新，观察 `rollout status`。应用回滚可用 `rollout undo`，但不能回退已发生的数据变更。
- 在每次云主机替换/销毁前备份 Redis、k3s 状态与本地凭证，并演练恢复。这里只配置了磁盘加密，**没有自动备份或跨 AZ 容灾**。
- `user_data_replace_on_change=true` 可能触发 VM 替换，因此配置启用 `prevent_destroy`，并设置根盘不随终止删除。AMI 已固定，升级必须明确修改输入；迁移或销毁前，先备份、演练恢复并审查移除保护的变更，不能直接重建单机状态。
- 不再使用时，先备份并显式审阅移除销毁保护，再执行 `terraform plan -destroy`。账户持有人批准后才能销毁。保留的根盘需要另行审查清理；停止 EC2 并不停止 EBS/IPv4 等费用，清理后检查 Billing。

## 当前验证范围

Terraform fmt/validate 和 mock-provider 的 4 项 plan 测试通过，未访问 AWS 创建资源。云端渲染、TLS 路由结构、私有凭证初始化通过单元测试。AWS 实机、域名解析、真实证书签发、SSM 登录和故障恢复仍需账户就绪后验证。
