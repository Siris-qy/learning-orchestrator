# Learning Orchestrator

LO 是由 AI 协助使用的本地个人知识工作区，用于备课、登记学习记录、整理正式笔记、关联知识与题目，以及项目复盘。

你指定学习范围、材料和期望讲法；连接 LO 的 AI 查找已有内容，完成必要登记与配置，生成并保存教案。学习可以在普通网页 AI 中进行，再把聊天记录交回 LO，恢复进度、追问和未确认项。正式知识正文、项目关系、题目与复习记录在同一工作区中管理。

当前为 **0.2 试用版**。已有功能持续整理中，欢迎通过 Issues 提交使用问题。仓库提供代码和虚构示例，不含维护者的笔记、教材、聊天、个人题库或数据库。

## 安装和启动

需要 Python 3.10 或更新版本。先下载或克隆本仓库，在源码目录运行。前端不需要 Node.js 或构建步骤。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp,pdf]"
.\.venv\Scripts\python.exe -m learning_orchestrator.workspace init --path ./lo-workspace --demo
.\.venv\Scripts\python.exe -m learning_orchestrator.dashboard --workspace ./lo-workspace --port 8745
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp,pdf]'
.venv/bin/python -m learning_orchestrator.workspace init --path ./lo-workspace --demo
.venv/bin/python -m learning_orchestrator.dashboard --workspace ./lo-workspace --port 8745
```

服务运行期间打开：

- [演示项目](http://127.0.0.1:8745/review-map.html#root_id=demo-project)：模块、流程、正文、使用知识和相关问题。
- [流程与文档](http://127.0.0.1:8745/workflows.html)：使用引导、工作设置和材料管理。
- [演示复盘批次](http://127.0.0.1:8745/review-batches.html#batch_id=demo-review)：原题、导出和外部回答回收。

首次创建自己的空白工作区时，去掉 `--demo`，或另选工作区目录。关闭服务进程会停止页面，重新运行最后一条命令即可恢复。同一学习工作区始终使用同一路径。

## 连接 AI

在同一虚拟环境中生成本机配置：

```powershell
# Windows
.\.venv\Scripts\python.exe scripts/make_mcp_config.py --workspace ./lo-workspace
```

```bash
# macOS / Linux
.venv/bin/python scripts/make_mcp_config.py --workspace ./lo-workspace
```

把输出加入客户端的 MCP 设置并重新连接；具体设置入口随客户端而异。生成配置使用你本机的 Python 和工作区绝对路径。

同时让 AI 使用 [LO skill](skills/learning-orchestrator/SKILL.md) 及其相对引用文件。支持安装 skill 的客户端可以安装整个 `skills/learning-orchestrator/` 文件夹；其他能读取本地文件的 AI 可以按该文件工作。仅连接工具不会自动让每个模型遵循完整工作流程。

然后直接对 AI 说：

> 用 LO 为这本教材的第一章准备教案。我希望从一个例子讲起，按适合讨论的小节组织，能交给看不到教材的网页 AI 讲解。材料在我提供的文件里。请完成必要登记、生成和保存，最后给我完整教案。

AI 负责查找和登记范围、复用配置、准备材料、生成、提交和读回。缺关键信息时会询问。网页看板可查看和调整已存设置；页面本身不运行模型。使用没有 LO 工具的网页 AI 时，可选择手动任务导出和结果接回。

完整流程与记录返回方式见 [使用指南](docs/使用指南.md)。

## 存储与扩展

每个工作区有独立 `lo.json`、SQLite 数据库、文档版本和来源目录。正式知识只有一个正文入口，节点负责定位和关系；项目流程通过关系复用公共知识。讲解、用户确认、作答评估和复习安排分别保存。

四类工作为教案、记录、笔记、知识关联。AI 和程序组件可以使用共同的准备/提交契约，按工作区注册不同策略。详见：

- [接口使用规范](docs/design/LO接口使用规范.md)
- [实现与目录](docs/design/2026-10-16-统一接口实现与目录说明.md)
- [笔记与知识规范](KNOWLEDGE_STANDARD.md)
- [知识图接口](docs/requirements/2026-10-10-知识图接口使用说明.md)
- [策略扩展示例](examples/strategy_ext.py)

主要目录：`src/learning_orchestrator/` 为服务与存储，`dashboard_static/` 为前端，`skills/` 为 AI 操作说明，`examples/` 为配置与扩展示例。用户资料放在独立工作区，不需要提交到本仓库。

## 当前边界

LO 目前面向本地单用户使用，默认监听 `127.0.0.1`，没有多用户账户或远程同步。AI 的内容生成使用你自己的客户端及模型。旧版工作区和部分专用课程导入代码仍在兼容，新安装按上面的显式工作区方式使用。

## 源码分发

```bash
python scripts/build_release.py
```

生成 `dist/learning-orchestrator-0.2.0-source.zip`。打包采用明确文件清单，排除个人学习资料和笔记图片。源代码仓库不包含个人工作区和本机生成的 MCP 配置。第三方前端组件的许可证保留在各自 `vendor` 目录中。
