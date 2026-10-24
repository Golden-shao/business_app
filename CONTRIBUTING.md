# 参与贡献

欢迎小而清晰的 PR。先阅读 README 并用 mock 模式运行，无需模型 API Key。

仓库已公开；main 的合并规则与独立 Codex 审查接入说明见 [GOVERNANCE.md](docs/GOVERNANCE.md)。请从分支提交 PR，不直接推送 main。已创建 Issues 与 Discussions 入口，但目前不宣称已有成熟的社区维护团队。

从文档、错误处理、可访问性、上游兼容性测试、本地 K8s 实验开始。架构或新依赖等较大修改，先开 issue 描述问题和验收方法。

提交前执行后端测试、`dart format lib test`、`flutter analyze` 和 `flutter test`。网页检查窄屏、键盘、错误和空数据状态；部署修改检查 Kustomize 输出和 schema，说明是否真实部署。

PR 说明解决的问题、用户可见变化和验证结果。不要提交 `.env`、密钥、聊天正文和私人数据。缺少设备或集群时说明未验证部分。欢迎中文或英文沟通。
