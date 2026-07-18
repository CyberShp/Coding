<!-- PROJECT-GOVERNANCE-START -->
> Provider: kimi

## Observation Web 协作与工程纪律

### 硬约束（不可变）
- **本地默认端口**：前端 5174、API 8002。端口以根目录 `config.json` 的 `server.port` 为单一真相源；脚本能读 config.json 就读，不要再散落写死端口。
- **No self-review**：不得自行评审自己的代码，优先交叉评审。

### 质量纪律（优先于"先试最简单的做法"）
- **Bug 先找根因再修**：复现 → 看日志 → 理调用链 → 确认根因 → 再修。不做 guess-and-patch。
- **方向不确定时**：停 → 查 → 问 → 确认 → 再动手，不要"先跑起来看看"。
- **"完成"需要证据**：测试通过 / 截图 / 日志。修 bug 遵循先红后绿。

### 文档纪律
- 描述须与实现一致。改了行为就同步改 README/docs；发现文档漂移就据实修正，不保留过时宣称。
- 分层信息架构：治理文件（本文件，简短）→ docs/（细节）。
<!-- PROJECT-GOVERNANCE-END -->
