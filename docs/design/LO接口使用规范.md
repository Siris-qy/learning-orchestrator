# LO 接口使用规范

版本：1.1，2026-10-16。状态：**明确操作与核心适配已落地；新增四流程配置、文档管理与步骤级知识展示。全部旧入口归并仍在进行。**

这是接口使用和后续重构的唯一规范入口。此前调研、八环节需求、写作规范继续有效；发生操作命名或交接方式冲突时，以本文为准。本文不要求换库、八个服务或每轮执行八次工具。

## 1. 用 LO 做什么

学习：确定目标和粗计划 → 选材料 → 生成自包含教案 → 在任意窗口学习 → 登记聊天/TXT → 找回当前位置、未回应和未确认问题。

沉淀：选择已有材料和记录 → 整理可读正文及知识定位 → 复用/补充节点与关系 → 发布 → 在座舱、题库、复习包读取同一份正式内容。

复习：先登记实际回答和外部补学过的原题批次 → 随时找回该批题 → 导出项目背景、正文和题单给网页 AI → 回收实际回答、追问和缺口 → 对明确覆盖的知识更新评估及既有排期。

用户不负责记住工具组合；调用方 AI 根据目标选择操作和策略。AI负责理解、拆解、写作和语义匹配；程序负责身份、读写、引用、范围、事务和回执。

## 2. 一套调用方法，明确的业务操作

保留 `get_workflow_contract`、`prepare_workflow`、`commit_workflow` 三个现有名称，不再另外添加一套“万能入口”。

1. `get_workflow_contract(operation?)`：查操作目录；指定操作才取其完整输入、产物、写入效果和策略说明。
2. `prepare_workflow(operation, scope, inputs, strategy_id?)`：读取当前范围和必要材料，返回 ticket、材料包、所选方法、产物契约。默认只读；不调用后台模型，不产生掌握。
3. AI/skill/处理程序生成产物。外部网页 AI 可以参与，LO 不要求它连接本地仓库。
4. `commit_workflow(request_id, ticket, artifact)`：只提交 ticket 对应的操作，返回实际变化、身份和续接入口，不回整库历史。
5. 阅读继续使用具名查询，如 `get_review_detail`、`get_teaching_state`、`get_review_batch`、题库查询；它们是业务读模型，不再增加一个自由 SQL/万能查询接口。

八环节是用途分类；`operation` 才决定操作。不能靠 artifact 恰好有 `curriculum` 或 `question_entries` 字段来猜另一个操作。旧 `stage` 调用仅作兼容翻译，新使用说明和新集成采用明确 operation。

### 公共参数

| 参数 | 含义 |
| --- | --- |
| operation | 目录中登记的稳定操作名；策略不能修改它 |
| scope | course_id、section_id、project_id、node_ids、batch_id、teaching_item_id 中本次实际需要的身份；不是“能传什么都传” |
| inputs | 目标、材料、聊天原文等本次输入；与要提交的正式产物分开 |
| strategy_id | 可选分析/写作策略；不指定时由操作和 project/course 类型选默认方法 |
| ticket | 程序返回的操作版本、范围、选择的方法及必要正文版本/来源检查点；调用方原样带回 |
| artifact | 此操作的业务产物，格式由操作目录给出；不是旧方法任意 kwargs |
| request_id | 一次实际提交的稳定身份；网络重试沿用，同一请求换内容应明确报冲突 |

同一知识在项目和基础库复用 node_id。project_id 表达本次项目应用范围，不是再建一份公共知识。文件路径、导航路径、维护归属不充当知识身份。

## 3. 操作目录与写入边界

| 环节 | operation | 输入与产物 | 可写入；不隐含写入 |
| --- | --- | --- | --- |
| 规划 | curriculum.register | 课程/项目标题、类型、章节身份与包含结构 | 登记入口和章节；不生成学习/掌握 |
| 规划 | plan.save | 章节、阶段、里程碑目录及关联节点 | 版本化教学计划、现有计划位置；不把计划当正式知识 |
| 取材 | context.prepare | 目标、选定节点、资料引用、已有内容范围 → 有界材料包 | 可保存交接快照；不发布为知识正文 |
| 教案 | lesson.publish | 选定教学位置、材料 → 自包含 Markdown 教案及自然分段 | 教案版本与位置；不标为讲过/理解 |
| 记录 | record.learning | 聊天/TXT增量与教学位置 → 分析、问题树增量、可选位置变化 | 教学过程、来源覆盖与游标；不自动发布笔记或评估知识 |
| 记录 | record.review | 原题批次与聊天增量 → 实际回答/补学/确认、递归缺口、待匹配内容 | 本批作答与问题；只在明确提供复述评估时接续知识排期 |
| 检验 | assessment.record | 真实回答依据、实际覆盖节点及项目范围 → 局部判断 | 对应知识/项目用法评估和既有排期；不广播所有关联点 |
| 沉淀 | note.publish | 旧正文和本次材料 → 正式正文、定位及本次关联增量 | 正文版本、索引及显式关系；不改掌握、教学位置和复习日期 |
| 组织 | graph.commit | 已有身份与明确图增量 → 节点、边、定位、题目考察关联 | 仅明确的增量；不因 contains/uses 自动继承全部题或掌握 |
| 组织 | questions.commit | 来源候选、已有匹配 → 复用/新题、来源、分类、知识关联、待关联项 | 题库与关联；不虚构亲历或作答 |
| 复习 | review.save | 本批标题、原 question_id、顺序、项目及知识范围 | 可找回的原题批次；不重新出题或建立第二套知识排期 |

资料登记/检索、正文迁址、复习包导出属于配套具名操作，继续复用既有接口；下一批将它们的描述及兼容入口接入同一目录，不另造资料库或正文库。

### 材料包

逻辑上包含：goal、scope、targets（身份/标题/已有正文与版本）、materials（实际摘录及来源）、state（必要局部位置/未解决项）、missing。字段为空可以省略或为空，不制造“证据齐全才能学习”的门槛。

项目取材关注目标、模块职责、协作与正常/主要异常通路、关键代码。课程取材关注教材/slide范围、前置、概念、例子和练习。两种适配器交给教案/笔记策略的是同一种材料包，不让下游重扫全部仓库或整本书。

默认返回有界内容；完整正文、原始聊天和历史通过明确范围读取。已有桌面会话可以复用上下文，ticket引用版本和当前范围，不要求每次重新发送整份教案。

## 4. 产物怎么写、怎么交接

### 4.1 规划与教案

计划包含稳定阶段/小节身份、标题、目的、顺序/依赖和知识范围。粗规划先存概要，材料和教案明确之后再细化。正式项目图与教学计划分别保存，不把每次追问升级为永久知识。

教案至少能独立说明当前目标、必要背景、本次内容、分段目录、示例/代码和下一步。小节数量由内容决定，不固定12节，不要求课程也生成项目骨架。复用 teaching_item_id/章节身份定位分段教案。

### 4.2 学习与复习记录

共有语义：来源及分析覆盖范围、用户提问、AI讲解、用户确认、实际回答、父子/并列问题、未回应、已讲未确认、明确解决和暂缓。它们不强行共用一张表，但不能由不同窗口重新解释这些状态。

教学记录产物：analysis（来源、摘要、实际问答及覆盖）、items_add/items_update（稳定小节/追问）、position（明确需要同步的位置）。轻量标记记录事实，不以问题队列未清空阻止用户换话题。

复习记录产物：attempts（原question_id、answer/explanation/confirmation、实际文本及覆盖）、gaps（稳定ID、parent_id、状态、关联节点）、unmatched（待匹配片段）、source_ticket（已分析增量检查点）。显式复述结果单独给出，不由“解释过”推断。

关闭子问题不关闭父问题或同级问题。用户确认是确认，不等于通过答题验证。读取TXT不前移已分析检查点；提交实际分析覆盖后才推进。无ID内容由AI匹配，歧义保留，不要求用户手工给聊天编号。

### 4.3 正文、定位与图

正文产物是完整可读 Markdown、来源引用、知识块/原子点定位和本次明确的关联修订。公共知识一个正式入口，项目写本项目的用法与流程，不复制整篇公共原理。所有底层细节不要求变成原子节点，普通栏目不自动建node。

项目正文必须能帮助读者恢复项目：为什么有此模块、输入如何处理、如何交给下一步、关键机制及必要异常。内容自然组织，配合例子/短代码；索引摘要、登记备注与纠错声明不能代替正文。具体写作风格和节点定位遵循根目录 KNOWLEDGE_STANDARD.md。

发布协调正文、索引及显式关联，失败不返回“已发布”。旧正文版本、原资料、未合入增量和旧身份保留。正文重排、迁址和归属转交不重建题目/项目/复习身份。

题目关联表达直接考察范围、项目上下文和用途。流程页看直接项目题及使用的公共知识；知识页看基础题和使用位置。`uses`不意味着继承该知识全部问题。

### 4.4 外部复习包

批次只保存原题入口、顺序和所需范围。导出返回可直接交给网页AI的 Markdown 与 manifest：项目全貌、选定模块/流程正文、必要公共知识、原编号题单、学习/答题与回收说明；引用清单保留原题/节点/正文版本。默认题目版不带参考答案。

用户先回答过并在外部补学的问题优先登记和找回；不自动生成另一批题替代。日期安排、页面提示、主动提醒分别声明，不能把“有下次日期”说成“已发通知”。

## 5. 调用例子（目标契约）

以下明确 operation 的调用已随本轮结构改造接入；旧 stage 写法只是兼容。查操作说明后调用，不凭示例硬编码项目、知识标题或小节数量。

```python
contract = lo.get_workflow_contract(operation="note.publish")
job = lo.prepare_workflow(
    operation="note.publish",
    scope={"project_id": project_id, "node_ids": [flow_id], "profile": "project"},
    inputs={"goal": "读后能复述此模块", "materials": selected_materials})
# 当前AI/skill生成，不隐含远程模型调用。
artifact = {"documents": [{"node_id": flow_id, "body": readable_markdown}]}
receipt = lo.commit_workflow(request_id="note-publication-r1",
                            ticket=job["ticket"], artifact=artifact)
detail = lo.get_review_detail(flow_id, project_id=project_id)
```

```python
job = lo.prepare_workflow(operation="review.save",
    scope={"batch_id": batch_id, "project_id": project_id})
lo.commit_workflow(request_id="register-answered-batch-r1", ticket=job["ticket"],
    artifact={"title": "本次已答面经", "items": [
        {"question_id": existing_question_id, "label": "原题1", "node_ids": [flow_id]}]})
package = lo.export_review_batch(batch_id)
# 网页AI中讨论，用户提供聊天/TXT后再准备增量。
job = lo.prepare_workflow(operation="record.review", scope={"batch_id": batch_id},
    inputs={"transcript": chat_text, "source_key": "external-round-1"})
# AI匹配原题、分析实际回答和递归缺口；带回读取检查点。
lo.commit_workflow(request_id="external-round-1-analysis-r1", ticket=job["ticket"],
    artifact=analysis_artifact)
again = lo.get_review_batch(batch_id)  # 无需等到期即可找回同一批原题。
```

## 6. 扩展怎么接

扩展点是某个操作中的分析/取材/写作方法。每个工作区有独立策略注册，不能因为另一个工作区加载扩展而改变当前任务。默认项目/课程方法也走同一注册机制。

策略声明 id、支持的operation/profile、简短方法说明，以及可选 prepare（加工本次材料包）/transform（加工本次产物）。skill、代码组件或模型适配器都可实现；最终产物仍满足操作契约。策略不直接写数据库；持久化由对应业务操作处理。不将任意插件视为沙箱，安装的代码扩展具有本机程序权限。

按任务加载所选策略，不能每次拼接所有规则。替换策略不会改变request_id含义、题目来源、确认/掌握语义或发布事务。

## 7. 程序内部怎样收口

```text
MCP / HTTP / Python / 导入脚本
       ↓ 参数翻译（旧入口仅兼容）
操作目录 + 工作区策略注册
       ↓ 同一业务操作及产物契约
资料 / 教学 / 正文 / 图关系 / 题库 / 复习领域实现
       ↓
SQLite、正式正文入口、来源资源
       ↓ 同一范围与身份解析
座舱读模型 / 题库 / 正文读取 / 外部教案与复习包
```

不是把旧API再包一层就算完成。每个兼容入口必须列出目标操作、字段转换、仍保留的返回格式、是否还有独有逻辑。核心写入规则只有一处，操作不能经由公开兼容入口递归分发。端口层不写业务状态推断或独立SQL。

旧入口对照：

| 旧入口 | 收口目标 |
| --- | --- |
| save_teaching_plan | plan.save，共用教学计划保存实现 |
| register_curriculum | curriculum.register |
| prepare_content_task / commit_content_task | note.publish或lesson.publish，旧ticket转换；共用生产/发布实现 |
| prepare_learning_record / commit_teaching_turn | record.learning；旧直接授课额外字段显式保留兼容，不混入新记录产物 |
| prepare_review_record / commit_review_record | record.review |
| record_review_assessment | assessment.record |
| commit_review_map | graph.commit |
| commit_question_batch及旧题目新增工具 | questions.commit；旧覆盖导入仅维护用途，不作默认追加 |
| save_review_batch | review.save |

旧入口保持原返回格式。旧save_teaching_plan等未提供request_id的调用，仍不能当作通用幂等提交；需要可靠重试的新调用用prepare/commit。兼容并不表示把旧参数和旧隐含行为推荐给新接入方。

## 8. 重试、错误与跨机器

prepare默认只读，可重复。commit同request_id同输入回原回执；同ID不同内容报冲突。读取到的正文或来源前缀已变化时，返回具体冲突并重新准备，不覆盖新内容。只做身份/范围/引用与真实并发检查，不增加“必须学完才能继续”的门禁。

错误区分调用格式、找不到对象、范围冲突、并发冲突与存储失败；回执指出失败处，不返回含糊成功。某操作事务内失败全部回滚，AI策略可以先产出明确的局部结果，其余保留待处理。

程序安装、工作区数据、素材和导出分离。`lo.json`配置数据库、来源根和扩展模块，材料以来源身份和相对位置定位。换窗口重连同工作区；换机器安装程序并迁移/导入工作区和资料映射。源码演示可运行不等于个人资料搬迁已通过验收。

## 9. 本轮落实顺序与完成判据

1. 本文定操作、语义和交接；修正历史文档中将统一入口写成完整重构的表述。
2. 将workflow的stage分支改成可查询的操作目录、显式产物说明和业务处理器；工作区策略隔离。旧stage仅做翻译。
3. 按上表将旧MCP/HTTP/Python入口归到相同处理器，列清尚未归并的入口，不能把“底层函数存在”报成调用链完成。
4. 整理共享材料包及记录适配，统一范围读模型；用项目模块和教材小节核验交接。
5. 验证原题→外部记录→登记→再次找回；新工作区复用；软件、原有正文整理和个人数据迁移分别报告。

目前11个明确操作均有目录和处理器。计划/课程登记、正文、图增量、题目批次、原题批次/回收、评估的具名服务入口已委托共同处理器；直接授课和新记录共享教学写入核心。工作区策略隔离已实现，项目/课程调用方式一致。

尚未完成：旧面经新增工具、旧知识append/consolidate与部分来源入口的完整归并；跨机器来源资源迁移、所有页面范围读模型的统一，以及其他旧正文整理。**整个项目重构尚未完成**；本轮进展继续写入现有夜间实施计划的接续记录，不再另起一份互相冲突的总规划。

## 10. 四类工作流程与配置看板

### 默认使用方式：AI 引导并执行

用户只需说明范围、期望成品和可用材料。连接 LO 并加载 skill 的 AI 依次：查找已有项目/课程及范围 → 必要时登记 → 读取当前流程配置并保存可复用要求 → 选择材料 → prepare_workflow → 生成实际内容 → commit_workflow → 读回并交付。生成教案走 lesson.publish，不绕过本项目的流程配置直接使用旧保存接口。

缺少会影响结果的信息时才询问用户；可由当前请求和已有默认值确定的字段由 AI 填好。一次性范围和要求不覆盖长期偏好。看板是查看和调整已保存设置的地方；用户不必手动选择策略、填写编号或搬运 JSON。手动交接保留给无法调用 LO 的外部 AI。页面本身不启动模型，实际生成由当前 AI 对话执行。用户说明见 docs/使用指南.md。

### 配置与交接约定

对用户的主要工作入口收敛为四类：生成教案（lesson）、学习记录登记（record）、笔记生成（note）、知识点关联（associate）。八环节继续表达需求和内部能力分类；不要求用户逐个操作八个环节。

`/workflows.html` 展示四类工作。每个项目/课程分别保存 goal、input_requirements、output_requirements、strategy_id、constraint_ids、extra_instructions 和 material_selections。输入要求表达本次做什么、依据和范围；产出要求表达希望得到的成品与读者。无专用策略时仍有这些字段，可沿用默认方法，通过澄清填入项目要求。

`get_workflow_board(project_id)` 读取配置与可用方法；`save_workflow_controls(project_id,process,values,base_version)` 保存。配置和约束编辑的版本号用于避免另一窗口被旧表单覆盖。已有明确要求复用，不重新盘问所有内容。

约束模块使用稳定 id、title、effect=input/method/output、instructions、applies_to、version。effect 说明约束起作用的对象；模型生成前已经能看到输入和产出要求，并非在模型输出后才追加输出要求。可以在看板多选、创建、编辑或复制内置模块，通过 `save_constraint_module` 接入同一管理接口。代码策略继续使用工作区注册和 prepare/transform 扩展。面板选约束，当前调用方 AI 或外部 AI 执行内容生产；没有另设一个默认后台模型。

`prepare_workflow` 自动装配本项目当前流程的配置、所选约束和材料。临时文本要求用 controls 参数覆盖，临时材料用 inputs.document_selections；返回 controls、ready、clarification、handoff_markdown。未明确目标/输入/产出时，返回具体澄清字段和续接说明；看板支持复制澄清请求、接回 JSON 字段并保存。AI 完成澄清后再准备任务；程序不把这一过程变成学习顺序门禁。

本次实际采用的配置版本、约束内容及材料引用随 ticket 保存，提交后登记到 workflow_run_receipts。仅选择本次流程，不拼入其他流程的提示词。已有 course 与项目根存在显式 owner_ref 或绑定时复用项目配置，不按标题或项目名猜测。

准备任务本身只读。需要跨窗口或关闭页面后续接时，使用 `save_workflow_task(task,title?)`，看板对应“存入文档库”。它保存一份交接文档和原任务快照。`get_workflow_task(document_id)` 恢复原 ticket、稳定提交 request_id 及已有回执；文档预览可“恢复此任务”，不必重新筛材料或猜原来的范围。任务存档保持原快照，新的要求另准备一轮任务。

HTTP 对应 `/api/workflow_board`、`/api/workflow_controls/save`、`/api/workflow_constraints/save`，仍调用同一服务层。

## 11. 文档入口与材料选择

`list_documents`、`save_document`、`read_document`、`document_versions` 提供统一文档身份与读取。类型为 material（原始材料）、lesson（教案）、record（学习记录）、note（笔记）、review_pack（复习包）。

新导入文件或粘贴正文存放在工作区 `documents/<kind>/`，workspace_documents 保存位置与版本，workspace_document_versions 保留旧版元数据。注册外部允许目录中的文件时复制成工作区版本，原文件保留。更新复用文档 id，版本文件不覆盖。移动整个工作区时，相对文件定位继续有效。

已有 sources、正式 knowledge_blocks、教案和原题复盘包按来源身份投影到文档库，分别使用 source:、knowledge:、lesson:、review-pack: 文档引用；不复制正式正文，不通过导入再造知识或题目。正式笔记仍由 note.publish 发布，文档库里手工保存的 note 是待处理笔记草稿。读取正式入口、页面阅读、复习导出沿用相同内容。

材料选择形如 `{document_id,version?,start_line?,end_line?,page_start?,page_end?,anchor?,max_chars?}`。省略 version 跟随当前文档；指定版本固定读取工作区旧版。ticket 记录实际读取版本、范围与指纹。材料总量有界，PDF 按页选取，读取可访问原文时不把检索摘要当整页正文；仅有旧索引时标注 indexed_excerpt。

record 流程可选择一个 record 文档，自动以其稳定 id 作为记录来源；先前已提交覆盖的前缀保持不变时只分析新增片段。用户更新、告知窗口后才分析，无文件监听器。教案背景等其他选定材料仍可一起提供，原聊天不会再作为材料重复回传一份。

HTTP 对应 `/api/documents`、`/api/document`、`/api/document/versions`、`/api/document/save`。网页支持粘贴、文件导入、行/页预览、选为材料与版本历史。

## 12. 模块、流程、步骤与公共知识

正式图采用 `project → module → flow → step` 组织项目处理过程；公共知识继续是 kind=knowledge，通过 step uses knowledge 表达“此步用到什么、有什么用”。步骤存标题与简明操作说明，流程保存连贯正式笔记。步骤不是新的公共原子概念，也不是教学追问。旧流程级 uses 保留，尚未具体归位的可作为流程关联显示。

note.publish 与 graph.commit 均接受：

```json
{"flow_steps":[{"flow_id":"existing-flow-id","steps":[
  {"id":"stable-step-id","title":"按工具名查找提供者","description":"在已加载插件目录中找到处理者。",
   "knowledge":[{"node_id":"existing-knowledge-id","usage":"用工具契约解释名称、输入与结果。"}]}
],"connections":[]}]}
```

省略 connections 按所给步骤顺序建立 next；分支、异常或循环用 connections 显式声明 from/to、next/fails_to 与 conditions。当前为增量 upsert；修改沿用步骤 id，省略旧步骤不代表删除旧数据。步骤内知识引用必须复用可定位的知识身份，不能把任意标题当作知识点。

流程详情读取同一个 flow_structure：先展示步骤说明、逐步知识用途与掌握情况，之后是正式流程正文、直接考察本流程/步骤的项目题，以及知识题节选。知识题节选可选 Top 3/5/10，仅查询公共知识题，按原题身份去重并排除直接项目题；不是为项目再复制一份题目或自动追加关联。掌握情况读取既有评估，不由图结构或正文发布产生。

模块页保留流程选择并显示模块正文；项目卡片和知识视角同时计入步骤级使用关系。外部复盘包也输出所选流程的步骤、知识用途与分支，manifest 保留同一身份。无步骤数据的旧流程显示待整理及原有正文；接口上线不等于全部旧流程内容已自动补写。
