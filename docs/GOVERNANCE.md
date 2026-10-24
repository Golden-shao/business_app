# 开源协作与审查

仓库已公开，代码采用 MIT 许可；公开不代表已经有多位维护者。当前维护者是 Golden-shao，欢迎使用者和贡献者通过 Issues、Discussions 和 PR 参与。

## 合并约束

main 通过 GitHub 分支保护执行 PR、必需 CI、独立批准、最新推送批准及对话解决，管理员也不能直接绕过。禁止强推和删除 main。新增功能在分支中开发，经 PR 合并。

本次准备了 `Harbor / AI review` 门禁。它只认可 `chatgpt-codex-connector[bot]` 在**当前 PR head SHA** 上的正式 APPROVED review；旧批准、COMMENTED、表情、普通用户或本聊天里的“审查通过”不会放行。新的 findings/撤销会阻止通过。workflow 不 checkout 或执行 PR 代码，只查询 GitHub review 元数据。

**尚需接通真实审查身份**：在 [Codex code review 设置](https://chatgpt.com/codex/settings/code-review) 中连接该仓库并开启审查，然后在 PR 请求 `@codex review`。[官方文档](https://learn.chatgpt.com/docs/third-party/github) 说明了审查与 AGENTS.md 规则，但没有保证每种集成都产生 APPROVED；如果当前集成仅发布 COMMENTED，就不能满足本门禁，必须先采用能够正式批准的独立审查配置再推进合并，不能伪造 Bot 的身份、把 COMMENTED 当批准或自动绕过。

GitHub 也不能由 PR 作者批准自己的 PR。因此，当前用户身份下的编码助手提交，不等于一个独立审查账号。该限制会让首次配置 PR 保持阻止状态，直到实际审查接入完成。当前 PR 不会被自动合并。

## 维护者与社区的职责

- 使用者负责描述真实问题，提供版本、复现步骤和脱敏请求 ID，不需要了解 K8s。
- 贡献者对照产品目标提交小范围 PR，保持 API 和网站/App 契约兼容。
- 维护者负责路线图、发布、成本预算和运行实例。云资源账户、账单和域名由实例持有人掌控。
- 新维护者应通过持续贡献和审查建立信任，再授予必要权限，不公开共享云账户或主令牌。
- 优先修复安全和数据损失风险，其次修复接入/恢复阻塞，再扩展模型与运维能力。

线上运行状态、CI 状态、审查结论分开报告。所有人都不得把配置文件、mock 测试或目标 URL 当成已经完成的公网部署证据。
