# 开源协作与审查

仓库已公开，代码采用 MIT 许可；公开不代表已经有多位维护者。当前维护者是 Golden-shao，欢迎使用者和贡献者通过 Issues、Discussions 和 PR 参与。

## 合并约束

main 通过 GitHub 分支保护执行 PR、必需 CI、独立 AI 结果及对话解决，管理员也不能直接绕过。禁止强推和删除 main。新增功能在分支中开发，经 PR 合并。独立 Bot 的当前提交结论通过必需状态 `Harbor / AI review` 实施，不能用 CI job 为绿色代替该状态。

`Harbor / AI review` 只信任 `chatgpt-codex-connector[bot]` 的 Bot 身份和**当前 PR head SHA**。它接受正式 APPROVED，或该 Bot 的版本化机器可读摘要明确报告 completed、无任何 findings、无 unresolved findings；旧提交、普通文字 LGTM、表情、未知格式、普通用户伪造的摘要均不放行。摘要格式变化时保持阻止。新的发现/撤销会阻止通过。

已在 PR #1 观察到真实 Codex Bot 的独立审查与结构化摘要。审查入口为 [Codex code review 设置](https://chatgpt.com/codex/settings/code-review)，可在 PR 请求 `@codex review`。[官方文档](https://learn.chatgpt.com/docs/third-party/github) 说明了审查与 AGENTS.md 规则。不是把 COMMENTED 自动当作 APPROVED，而是验证该 Bot 单独发布的明确、当前提交、无发现的审查结论；两者在报告中区分。

状态发布器仅运行于 `pull_request_target` 和 PR 的 `issue_comment` 事件，从可信 base/default 分支读取 workflow；不使用加载 PR 代码的 `pull_request_review` 写权限流程，也不 checkout 或执行 PR 代码。因此 fork 的 review 通知同样由可信、可写上下文重新评估。首次安装 workflow 尚不在 main 时，由维护者执行同一判定代码查询真实 Bot 结果同步一次状态，不可手工宣称审查通过。

GitHub 不允许作者正式批准自己的 PR。本项目不伪造该批准：单维护者模式额外的人工批准数为 0，但强制独立 AI 状态与 CI。扩展维护团队后可另外要求人工批准。拥有仓库写权限的成员属于受信任维护者，应严格审核新增 workflow 的权限；分支规则不等于对恶意仓库管理员的隔离。

## 维护者与社区的职责

- 使用者负责描述真实问题，提供版本、复现步骤和脱敏请求 ID，不需要了解 K8s。
- 贡献者对照产品目标提交小范围 PR，保持 API 和网站/App 契约兼容。
- 维护者负责路线图、发布、成本预算和运行实例。云资源账户、账单和域名由实例持有人掌控。
- 新维护者应通过持续贡献和审查建立信任，再授予必要权限，不公开共享云账户或主令牌。
- 优先修复安全和数据损失风险，其次修复接入/恢复阻塞，再扩展模型与运维能力。

线上运行状态、CI 状态、审查结论分开报告。所有人都不得把配置文件、mock 测试或目标 URL 当成已经完成的公网部署证据。
