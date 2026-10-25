# ModelJetty contributor and review guidance

- Use a feature branch and PR for changes. `main` is protected; do not bypass required checks or reviews.
- Users consume the API, website and App. Kubernetes concepts belong in operator documentation, not in ordinary user actions.
- Run the affected tests and report platform limits. A valid manifest is not evidence of a successful AWS deployment.

## Code Review Rules

### Credential and tenant boundaries

Flag any change that exposes ADMIN_TOKEN, GATEWAY_TOKEN, upstream credentials or message content in public responses, logs, Terraform state, cloud-init, artifacts or PR comments. Tests may use obviously fake credentials. Request origin labels are display metadata, not authentication.

### Paid or irreversible actions

Flag automatic POST retries, provisioning paid resources without an explicit plan/budget, or exposing Redis/Kubernetes API ports publicly. A successful model reply must survive a failed status refresh without being resent.

### Evidence and deployment

Review the exact current PR head, including deployment/workflow changes. Do not approve based only on passing tests. Record unresolved findings and do not claim that a chat review is an independent GitHub approval. AWS signup, production TLS issuance and iOS device testing require their own evidence.
