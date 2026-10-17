"""Seed for the "A2A C++ 多 Agent 通信项目" course.

Resume-driven project learning: the graph mirrors the interview story —
positioning first, then one live request chain (gRPC -> A2A adapter ->
orchestrator -> registry/agent -> back), then the supporting modules. Source
files from the sibling repo are indexed symbol-aware (see code_index.py) and
every resume claim carries a verified implementation status (claims table).

Idempotent: nodes/edges/claims are inserted once; file registration reuses
existing source ids. If the project repo is missing, the graph and claims are
still seeded and file registration is skipped with a warning list.
"""

import os
from pathlib import Path

from . import graph, sources
from .db import PROJECT_ROOT, transaction

COURSE_ID = "a2a-agent-communication"

_ENV_ROOT = "LEARNING_ORCHESTRATOR_A2A_ROOT"


def default_repo_root():
    env = os.environ.get(_ENV_ROOT)
    if env:
        return Path(env)
    return PROJECT_ROOT.parent / "-agent-communication-main"


# ---------------------------------------------------------------------------
# Graph. Node ids are prefixed "a2a:" to stay clear of the CMU seed.
# Summaries of first-stage units embed the fixed nine-part teaching frame:
# 解决什么问题 / 上下游 / 输入 / 关键处理 / 输出 / 关键文件 / 通用知识 /
# 面试追问 / 边界.
# ---------------------------------------------------------------------------

NODES = [
    (COURSE_ID, "course", "A2A C++ 多 Agent 通信项目",
     "简历驱动的项目学习：先讲清项目定位与一分钟介绍，再沿一次 AI 查询的"
     "正常请求链（gRPC 接入 → A2A 协议转换 → Orchestrator 路由 → "
     "Registry/Agent → 原路返回）逐模块理解源码，同时标注每条简历主张的"
     "真实实现状态。", 0),

    # -- Module 1: 项目定位与简历故事 --------------------------------------
    ("a2a:mod:m1", "module", "项目定位与简历故事",
     "项目解决什么问题、架构图、三种协议的职责边界，以及简历主张的实现"
     "状态分类。学完后能脱稿做一分钟介绍。", 0),
    ("a2a:u:positioning", "unit", "项目定位：它解决什么问题",
     "解决什么问题：对外提供统一 AI 查询入口，对内协调多个专业 Agent 与 MCP"
     " 工具，展示的是通信与协调能力而不是调用大模型 API。上下游：用户/客户端"
     "在上游，Orchestrator 与各 Agent 在下游。输入：自然语言问题与 contextId。"
     "关键处理：gRPC 接入、A2A 消息转换、意图识别、能力路由、工具调用。"
     "输出：AIQueryResponse（答案 + 处理 Agent + 耗时）。关键文件："
     "原始文档/简历.txt、原始文档/面试收敛项目介绍.md、docs/architecture.md。"
     "通用知识：Agent 与工具的区别、编排与工作的边界。面试追问："
     "“这个项目和直接调一个大模型有什么区别？”边界：只讲定位与故事，"
     "不展开任何模块的内部实现。", 10),
    ("a2a:o:one-minute", "objective", "脱稿完成一分钟项目介绍",
     "按“gRPC 接入 → A2A 适配 → Orchestrator 意图路由 → Math Agent + MCP "
     "工具 → RAG 工具筛选”三段式讲完，被追问哪个模块再展开哪个。", 11),
    ("a2a:o:three-protocols", "objective", "讲清 gRPC / A2A / MCP 三层协议职责边界",
     "gRPC 面向系统调用方（强类型、流式），A2A 面向 Agent 间协作（消息/任务/"
     "流事件），MCP 面向 Agent 调工具（发现、参数描述、调用）。适配层隔离"
     "边界，一层变化不需要重写系统。", 12),
    ("a2a:o:claims-status", "objective", "用实现状态标注简历主张",
     "对每条简历主张能说出它是 implemented_and_wired / implemented_not_wired"
     " / interface_or_example / planned_upgrade / needs_verification 中哪一"
     "类，并能给出代码证据（文件:行号）。", 13),

    # -- Module 2: gRPC 外部接入与正常请求链 -------------------------------
    ("a2a:mod:m2", "module", "gRPC 外部接入与正常请求链",
     "以一次 AI 查询为主线：Protobuf 契约 → Client Stub/Channel → RPC "
     "Server/AIQueryService → 响应返回。同步与流式两种入口都在这里。", 1),
    ("a2a:u:proto-contract", "unit", "Protobuf 数据契约",
     "解决什么问题：跨进程传输需要双方都认可的强类型数据契约。上下游：上是"
     "调用方代码，下是生成的 Stub 与 Service 基类。输入：.proto 定义。"
     "关键处理：message 字段编号（兼容性来自编号而非字段名）、service/rpc "
     "声明、stream 关键字。输出：生成的 C++ 类（不索引生成文件，只看接口）。"
     "关键文件：proto/ai_query.proto、proto/agent_service.proto、"
     "proto/common.proto。通用知识：字段编号与兼容演进、message 与 service "
     "分工。面试追问：“新增一个字段怎样不破坏旧客户端？”边界：不讲 "
     "Protobuf 编码 wire format 细节。", 20),
    ("a2a:o:proto-messages", "objective", "读懂 AIQueryRequest/Response 的字段设计",
     "request_id 追踪一次调用、context_id 关联多轮会话、task_id 标识长任务；"
     "能解释三个 ID 的生命周期差异。", 21),
    ("a2a:o:proto-services", "objective", "区分两个 service 的 rpc 定义",
     "AIQueryService（Query/QueryStream/GetQueryStatus，业务主链）与 "
     "AgentCommunicationService（四种调用模式演示 + 心跳）各自的角色。", 22),
    ("a2a:u:grpc-client", "unit", "gRPC 客户端：Channel / Stub / ClientContext",
     "解决什么问题：客户端如何建立连接并发起一次远程调用。上下游：上是用户"
     "代码，下是 RPC Server。输入：服务器地址与 AIQueryRequest。关键处理："
     "CreateCustomChannel 建 Channel（带 64MB 消息上限）、NewStub 生成 "
     "Stub、ClientContext 设置 deadline、同步 stub_->Query 阻塞等待、按 "
     "grpc::Status 与业务 status 双层判断结果。输出：AIQueryResponse。"
     "关键文件：client/src/ai_query_client.cpp、client/src/rpc_client.cpp。"
     "通用知识：Channel 是长连接复用、Stub 是类型安全入口、Context 携带"
     " deadline/取消。面试追问：“deadline 超时后服务端还在跑吗？”边界："
     "不讲负载均衡（在模块 7）。", 30),
    ("a2a:o:grpc-client-send", "objective", "讲清 Query 从 connect 到返回的路径",
     "connect → CreateCustomChannel → NewStub → query 构造请求与 "
     "ClientContext → stub_->Query → 双层状态判断（gRPC 层 + 业务层）。", 31),
    ("a2a:o:grpc-deadline", "objective", "解释 deadline、取消与状态码",
     "deadline 在 ClientContext 上设置，超时返回 DEADLINE_EXCEEDED；"
     "取消与错误通过 grpc::Status 状态码区分，业务错误另走 "
     "response.status。", 32),
    ("a2a:u:grpc-server", "unit", "RPC Server 与 AIQueryService",
     "解决什么问题：给上游一个稳定的 gRPC 网关，隐藏内部 Agent 系统。"
     "上下游：上是 Client Stub，下是 A2A Adapter。输入：AIQueryRequest + "
     "ServerContext。关键处理：ServerBuilder 注册三个服务并启用健康检查/"
     "反射/keepalive；Query 入口依次做可用性检查、取消检查、熔断器检查，"
     "再委托 a2a_adapter_->processQuery，最后记录指标。输出："
     "AIQueryResponse 或 gRPC 错误状态。关键文件：server/src/rpc_server.cpp、"
     "server/src/ai_query_service.cpp。通用知识：同步 API 下每个 RPC 由线程"
     "池线程执行；GetQueryStatus 显式返回 UNIMPLEMENTED 比假装支持更诚实。"
     "面试追问：“入口为什么要先查熔断器？”边界：Adapter 内部在模块 3。",
     40),
    ("a2a:o:grpc-server-recv", "objective", "讲清 ServerBuilder 与 Query 入口防护",
     "服务注册、keepalive 参数、IsCancelled 检查、熔断器 isRequestAllowed、"
     "recordSuccess/recordFailure 反馈闭环。", 41),
    ("a2a:o:grpc-streaming", "objective", "区分 unary 与 server streaming 实现",
     "Query 一次性返回；QueryStream 用 ServerWriter 逐条 Write "
     "AIStreamEvent；AgentCommunicationService 里还有客户端流与双向流的"
     "实现可对照。四种模式都已定义并实现，主体是同步阻塞 API。", 42),
    ("a2a:u:chain-walk", "unit", "完整走通一次查询主链",
     "解决什么问题：把模块 2 的三节串成一条可脱稿复述的请求链，并延伸到"
     " Adapter/Orchestrator/Registry 的接力与响应原路返回。上下游："
     "模块 1 的故事在上游，模块 3/4 的细节在下游。输入：一个具体问题"
     "（如“计算 1+7”）。关键处理：逐跳说明谁收到什么、做了什么、交给谁。"
     "输出：完整链路叙述 + 每跳的文件:行号证据。关键文件：主链全部文件。"
     "通用知识：协议网关、防腐层、同步阻塞与 CompletionQueue 异步的区别"
     "（后者是扩展知识，当前项目未使用）。面试追问：“如果 Orchestrator "
     "挂了，调用方看到什么？”边界：Agent 内部与 MCP 细节留给模块 4-6。",
     50),
    ("a2a:o:chain-narrative", "objective", "脱稿讲通完整链路",
     "AIQueryRequest → proto 契约 → Client Stub/Channel/ClientContext → "
     "RPC Server → AIQueryService（防护） → A2A Adapter → Orchestrator → "
     "Registry/Agent → 响应原路转换返回，每步能指出源码位置。", 51),
    ("a2a:o:chain-sync-async", "objective", "说明同步 gRPC 与 CompletionQueue 的区别",
     "当前项目为同步阻塞式 API（每个 RPC 占一个线程）；CompletionQueue "
     "异步模型是扩展知识，能讲清区别但不得描述成项目现状。", 52),

    # -- Module 3: A2A Adapter ---------------------------------------------
    ("a2a:mod:m3", "module", "A2A Adapter 与协议模型转换",
     "Protobuf 与 A2A 消息模型之间的防腐层：请求转换、响应转换、SSE 流事件"
     "转换。", 2),
    ("a2a:u:adapter-request", "unit", "请求转换：RequestAdapter",
     "AIQueryRequest → MessageSendParams：提取或生成 contextId、构造 "
     "AgentMessage（role=user、TextPart）、透传 history_length。关键文件："
     "a2a_adapter/src/request_adapter.cpp、a2a_adapter.cpp。", 60),
    ("a2a:o:adapter-request", "objective", "说明请求如何变成 A2A 消息",
     "字段级映射：question→TextPart、context_id→contextId（缺失则生成）、"
     "history_length→historyLength；message_id 由适配层生成。", 61),
    ("a2a:u:adapter-response", "unit", "响应与流事件转换：ResponseAdapter",
     "A2AResponse（Task 或 Message）→ AIQueryResponse；SSE data 行 → "
     "AIStreamEvent（partial/status/complete/error）。关键文件："
     "a2a_adapter/src/response_adapter.cpp。", 70),
    ("a2a:o:adapter-response", "objective", "说明响应与流事件如何变回 Protobuf",
     "Task 取 history 中最后一条 Agent 消息作答案；流式按 "
     "chunk/stream_start/stream_end/intent 事件类型映射；能解释为什么 "
     "complete 事件由外层补发。", 71),

    # -- Module 4: Orchestrator / Registry ----------------------------------
    ("a2a:mod:m4", "module", "Orchestrator、Registry 与能力路由",
     "意图识别、按技能/标签过滤候选、健康检查与选择策略；注册中心的标签"
     "索引与心跳剔除。", 3),
    ("a2a:u:router", "unit", "AgentRouter：意图识别与候选选择",
     "关键词意图识别（analyzeRequiredSkill）→ 按技能与健康状态过滤 → "
     "无匹配时回退全体健康 Agent → 按策略选择（默认技能匹配后退化为轮询）。"
     "关键文件：orchestrator/src/agent_router.cpp、"
     "examples/ai_orchestrator/orchestrator_main.cpp。", 80),
    ("a2a:o:router-strategy", "objective", "讲清技能过滤、回退与轮询选择",
     "selectAgent 的两阶段（过滤 + 选择）；ROUND_ROBIN/RANDOM/LEAST_LOAD "
     "在 AgentRouter 内实现；简历中更多策略在 RpcClient 侧，要分开说。", 81),
    ("a2a:u:registry", "unit", "Registry：注册、心跳与标签发现",
     "Agent 信息只存一份、标签索引只存 ID；心跳更新与剔除；另有 "
     "Consul/Etcd/Memory 三种 ServiceRegistry（RPC 服务注册，与 Agent "
     "注册中心不是一回事）。关键文件：a2a/include/a2a/examples/"
     "agent_registry.hpp、registry/src/service_registry.cpp。", 90),
    ("a2a:o:registry-tags", "objective", "解释标签索引与心跳剔除",
     "tags_index_ 反查 Agent ID 再取完整信息；服务发现回答“有哪些可用”，"
     "负载均衡回答“选哪一个”，意图识别回答“需要什么能力”——三者分清。", 91),

    # -- Module 5: A2A SDK ---------------------------------------------------
    ("a2a:mod:m5", "module", "A2A SDK、消息模型与任务生命周期",
     "AgentCard / Message / Part / Task / Artifact 数据模型，"
     "message/send 与 message/stream，TaskStore 的 Memory 与 Redis 实现"
     "及真实接入状态。", 4),
    ("a2a:u:a2a-models", "unit", "A2A 消息与任务模型",
     "信息模型（AgentCard：你是谁、能做什么）、消息模型（Message/Part："
     "单轮信息）、任务模型（Task：长任务分多次返回）。关键文件："
     "a2a/include/a2a/models/*.hpp。", 100),
    ("a2a:o:a2a-models", "objective", "区分 Message/Part/Task/Artifact 与三个 ID",
     "requestId 追踪一次调用、contextId 串联会话、taskId 标识长任务；"
     "当前数学示例主要用请求与上下文链。", 101),
    ("a2a:u:taskstore", "unit", "TaskStore：Memory 与 Redis",
     "MemoryTaskStore 是主链默认；RedisTaskStore 在 examples 中有实现，"
     "a2a_adapter 的 TaskManagerWrapper 仍是 TODO 并回退 Memory。关键文件："
     "a2a/src/server/memory_task_store.cpp、a2a/src/examples/"
     "redis_task_store.cpp、a2a_adapter/src/task_manager_wrapper.cpp。", 110),
    ("a2a:o:taskstore-status", "objective", "说明 RedisTaskStore 的真实接入状态",
     "能指出 TODO 位置与回退逻辑，面试中主动说明“示例已验证、主链适配层"
     "尚未接入”，不把示例讲成在线运行。", 111),

    # -- Module 6: MCP --------------------------------------------------------
    ("a2a:mod:m6", "module", "MCP、插件系统与工具调用",
     "MCP Client/Server、STDIO 与 SSE 传输、动态库插件、RAG 工具筛选。", 5),
    ("a2a:u:mcp-client", "unit", "MCP Client 与传输层",
     "JSON-RPC 通信：initialize 能力协商、tools/list、tools/call；STDIO "
     "适合本机集成，SSE 适合远程。关键文件：mcp/src/mcp_client.cpp、"
     "mcp_server_integrated/src/transport/。", 120),
    ("a2a:o:mcp-transport", "objective", "比较 STDIO 与 SSE 两种传输",
     "进程间零部署 vs 跨机器远程调用；能说明各自适用场景与代价。", 121),
    ("a2a:u:mcp-agent-loop", "unit", "单 Agent 的 MCP 工具调用闭环",
     "从 mcp/ 目录的上层业务入口理解最小闭环：MCPAgentIntegration 初始化并连接"
     " Server，MCPToolManager 获取与管理工具，Agent 选择并调用工具，再把结构化"
     "结果交回模型或业务层。关键文件：mcp/src/mcp_agent_integration.cpp、"
     "mcp/src/mcp_tool_manager.cpp、mcp/src/mcp_client.cpp。先讲模块关系与一次"
     "调用，随后再分别深入传输和 RAG；这一节点不等同于 MCP Server。", 125),
    ("a2a:o:mcp-agent-loop", "objective", "讲通一次单 Agent 工具调用",
     "能从初始化、连接、tools/list、工具选择、tools/call、结果返回讲通最小"
     "闭环，并区分 Agent、MCP Client、Tool Manager 与 MCP Server。", 126),
    ("a2a:u:mcp-plugins", "unit", "插件系统与动态加载",
     "统一 C ABI + 动态库扫描加载，tools/prompts/resources 三类插件，"
     "新增功能不改主服务。关键文件：mcp_server_integrated/src/loader/"
     "PluginsLoader.cpp、mcp_server_integrated/plugins/。", 130),
    ("a2a:o:mcp-plugins", "objective", "讲清统一抽象与插件生命周期",
     "面试重点是抽象与生命周期，不背平台加载 API；注意该插件系统属于独立 "
     "MCP server，不在 AI 查询主链上。", 131),
    ("a2a:u:mcp-rag", "unit", "RAG 工具筛选",
     "工具描述向量化 → 向量索引 → 余弦相似度 Top-K → 候选工具交给模型。"
     "解决工具过多时的上下文开销与选择准确率。关键文件：mcp/src/rag/"
     "tool_retriever.cpp、examples/rag_mcp_example.cpp。", 140),
    ("a2a:o:mcp-rag", "objective", "说明 Top-K 检索的动机与边界",
     "工具少时直接列出更简单；能讲 fallback 与阈值；知道它未接入 AI 查询"
     "主链（implemented_not_wired）。", 141),

    # -- Module 7: 可靠性 -----------------------------------------------------
    ("a2a:mod:m7", "module", "可靠性机制：deadline、重试、熔断、心跳、指标",
     "跨进程调用不确定性的应对：熔断三态机、负载均衡策略族、心跳、"
     "指标记录——以及它们各自接没接进主链。", 6),
    ("a2a:u:circuit", "unit", "熔断器",
     "CLOSED/OPEN/HALF_OPEN 三态；AIQueryService.Query 在调用 A2A 后端前"
     "检查熔断器并按结果反馈。关键文件：common/include/agent_rpc/common/"
     "circuit_breaker.h、server/src/ai_query_service.cpp。", 150),
    ("a2a:o:circuit", "objective", "讲清熔断三态与主链接入点",
     "失败率超阈值熔断、恢复窗口后试探；能指出 isRequestAllowed 与 "
     "recordSuccess/Failure 的调用位置。", 151),
    ("a2a:u:loadbalance", "unit", "负载均衡策略",
     "轮询/随机/最少连接/加权轮询/一致性哈希在 common/load_balancer 实现"
     "并接入 RpcClient；“最短响应时间”需核实。AgentRouter 侧是另一套"
     "（轮询/随机/最少负载）。关键文件：common/include/agent_rpc/common/"
     "load_balancer.h、client/src/rpc_client.cpp。", 160),
    ("a2a:o:loadbalance", "objective", "区分两套负载均衡的接入情况",
     "RpcClient（服务端点选择）与 AgentRouter（Agent 选择）分开讲；"
     "逐项核实简历中的六种策略。", 161),
    ("a2a:u:metrics", "unit", "指标与心跳",
     "counter/gauge/histogram；AIQueryService 记录请求耗时与成败；"
     "RpcClient 有心跳线程与 Heartbeat RPC。关键文件：common/include/"
     "agent_rpc/common/metrics.h、client/src/rpc_client.cpp。", 170),
    ("a2a:o:metrics", "objective", "说明指标类型与心跳接线",
     "指标在入口记录；业务心跳（AgentCommunicationService.Heartbeat）与 "
     "gRPC keepalive 不是一回事。", 171),

    # -- Module 8: 面试验收 ---------------------------------------------------
    ("a2a:mod:m8", "module", "面试验收与薄弱点复习",
     "随机抽模块回答职责/上下游/实现状态；针对 struggling 节点复习；"
     "收敛简历描述。", 7),
    ("a2a:u:mock", "unit", "模拟面试与薄弱点复习",
     "验收标准：一分钟介绍、完整请求链、随机模块追问、概念辨析（A2A vs "
     "MCP、contextId vs taskId、Agent vs 工具）、实现状态不吹过头。", 180),
    ("a2a:o:mock-interview", "objective", "随机抽模块完成追问应答",
     "任一模块能答：解决什么问题、上下游是谁、关键文件在哪、实现状态"
     "如何。", 181),
    ("a2a:o:weak-review", "objective", "针对薄弱节点完成复习",
     "用 review 模式重测所有 struggling / 超期节点，直到最新一次为无提示"
     "答对。", 182),
]

# (src, dst, type, note)
EDGES = (
    [(mod, COURSE_ID, "part_of", "") for mod in (
        "a2a:mod:m1", "a2a:mod:m2", "a2a:mod:m3", "a2a:mod:m4",
        "a2a:mod:m5", "a2a:mod:m6", "a2a:mod:m7", "a2a:mod:m8")]
    + [(unit, mod, "part_of", "") for mod, units in (
        ("a2a:mod:m1", ("a2a:u:positioning",)),
        ("a2a:mod:m2", ("a2a:u:proto-contract", "a2a:u:grpc-client",
                        "a2a:u:grpc-server", "a2a:u:chain-walk")),
        ("a2a:mod:m3", ("a2a:u:adapter-request", "a2a:u:adapter-response")),
        ("a2a:mod:m4", ("a2a:u:router", "a2a:u:registry")),
        ("a2a:mod:m5", ("a2a:u:a2a-models", "a2a:u:taskstore")),
        ("a2a:mod:m6", ("a2a:u:mcp-client", "a2a:u:mcp-agent-loop",
                        "a2a:u:mcp-plugins", "a2a:u:mcp-rag")),
        ("a2a:mod:m7", ("a2a:u:circuit", "a2a:u:loadbalance",
                        "a2a:u:metrics")),
        ("a2a:mod:m8", ("a2a:u:mock",)),
    ) for unit in units]
    + [(obj, unit, "part_of", "") for unit, objs in (
        ("a2a:u:positioning", ("a2a:o:one-minute", "a2a:o:three-protocols",
                               "a2a:o:claims-status")),
        ("a2a:u:proto-contract", ("a2a:o:proto-messages",
                                  "a2a:o:proto-services")),
        ("a2a:u:grpc-client", ("a2a:o:grpc-client-send",
                               "a2a:o:grpc-deadline")),
        ("a2a:u:grpc-server", ("a2a:o:grpc-server-recv",
                               "a2a:o:grpc-streaming")),
        ("a2a:u:chain-walk", ("a2a:o:chain-narrative",
                              "a2a:o:chain-sync-async")),
        ("a2a:u:adapter-request", ("a2a:o:adapter-request",)),
        ("a2a:u:adapter-response", ("a2a:o:adapter-response",)),
        ("a2a:u:router", ("a2a:o:router-strategy",)),
        ("a2a:u:registry", ("a2a:o:registry-tags",)),
        ("a2a:u:a2a-models", ("a2a:o:a2a-models",)),
        ("a2a:u:taskstore", ("a2a:o:taskstore-status",)),
        ("a2a:u:mcp-client", ("a2a:o:mcp-transport",)),
        ("a2a:u:mcp-agent-loop", ("a2a:o:mcp-agent-loop",)),
        ("a2a:u:mcp-plugins", ("a2a:o:mcp-plugins",)),
        ("a2a:u:mcp-rag", ("a2a:o:mcp-rag",)),
        ("a2a:u:circuit", ("a2a:o:circuit",)),
        ("a2a:u:loadbalance", ("a2a:o:loadbalance",)),
        ("a2a:u:metrics", ("a2a:o:metrics",)),
        ("a2a:u:mock", ("a2a:o:mock-interview", "a2a:o:weak-review")),
    ) for obj in objs]
    # 学习顺序 = 请求主链顺序（前段）+ 支撑模块（后段）。前端“主链视角”
    # 直接按这条 sequence 路径渲染。
    + [(a, b, "sequence", "") for a, b in zip(
        ("a2a:u:positioning",
         "a2a:u:proto-contract", "a2a:u:grpc-client", "a2a:u:grpc-server",
         "a2a:u:adapter-request", "a2a:u:router", "a2a:u:registry",
         "a2a:u:adapter-response", "a2a:u:chain-walk",
         "a2a:u:a2a-models", "a2a:u:taskstore",
         "a2a:u:mcp-client", "a2a:u:mcp-agent-loop", "a2a:u:mcp-plugins", "a2a:u:mcp-rag",
         "a2a:u:circuit", "a2a:u:loadbalance", "a2a:u:metrics"),
        ("a2a:u:proto-contract", "a2a:u:grpc-client", "a2a:u:grpc-server",
         "a2a:u:adapter-request", "a2a:u:router", "a2a:u:registry",
         "a2a:u:adapter-response", "a2a:u:chain-walk",
         "a2a:u:a2a-models", "a2a:u:taskstore",
         "a2a:u:mcp-client", "a2a:u:mcp-agent-loop", "a2a:u:mcp-plugins", "a2a:u:mcp-rag",
         "a2a:u:circuit", "a2a:u:loadbalance", "a2a:u:metrics",
         "a2a:u:mock"))]
    + [(a, b, "prerequisite", "") for a, b in (
        ("a2a:u:positioning", "a2a:u:proto-contract"),
        ("a2a:u:proto-contract", "a2a:u:grpc-client"),
        ("a2a:u:grpc-client", "a2a:u:grpc-server"),
        ("a2a:u:grpc-server", "a2a:u:chain-walk"),
        ("a2a:u:adapter-request", "a2a:u:adapter-response"),
        ("a2a:u:a2a-models", "a2a:u:taskstore"),
        ("a2a:u:mcp-client", "a2a:u:mcp-rag"),
        ("a2a:o:grpc-client-send", "a2a:o:grpc-deadline"),
        ("a2a:o:grpc-server-recv", "a2a:o:chain-narrative"),
        ("a2a:o:adapter-request", "a2a:o:router-strategy"),
        ("a2a:o:chain-narrative", "a2a:o:mock-interview"),
    )]
    + [("a2a:o:chain-sync-async", "a2a:o:grpc-streaming", "contrasts_with",
        "同步阻塞 API（现状） vs CompletionQueue 异步（扩展知识）")]
)

# (node_id, claim text, status, evidence)
CLAIMS = [
    ("a2a:o:grpc-streaming",
     "四种 gRPC 调用模式（简单、服务端流、客户端流、双向流）",
     "implemented_and_wired",
     "proto/agent_service.proto:111-141 定义；server/src/agent_service.cpp "
     "ListenMessages:307 / BatchSendMessages:335 / RealTimeCommunication:358 "
     "有实现；主链 AI 查询使用 unary(Query) 与服务端流(QueryStream)"),
    ("a2a:o:chain-sync-async",
     "主体使用同步阻塞式 gRPC API，不是 CompletionQueue 异步服务器",
     "implemented_and_wired",
     "client/src/ai_query_client.cpp:119 stub_->Query 同步阻塞；"
     "server/src/rpc_server.cpp:222 setupServer 用 ServerBuilder."
     "BuildAndStart，无 CompletionQueue"),
    ("a2a:u:taskstore",
     "基于 Redis 的分布式 TaskStore 保存上下文记忆",
     "interface_or_example",
     "a2a/src/examples/redis_task_store.cpp 有实现；examples/ai_orchestrator/"
     "orchestrator_main.cpp:92 在示例中接入；但 a2a_adapter/src/"
     "task_manager_wrapper.cpp:101 仍是 TODO 并回退 MemoryTaskStore"),
    ("a2a:u:loadbalance",
     "多种负载均衡策略：轮询/随机/最少连接/加权轮询/一致性哈希",
     "implemented_and_wired",
     "common/include/agent_rpc/common/load_balancer.h 实现五种策略；"
     "client/src/rpc_client.cpp:128-196 接入 RpcClient 的端点选择"),
    ("a2a:u:loadbalance",
     "最短响应时间负载均衡策略",
     "needs_verification",
     "简历列出六种策略，load_balancer.h 中未见 LeastResponseTime 实现，"
     "需逐项核实"),
    ("a2a:o:router-strategy",
     "Orchestrator 的 Agent 选择支持多种负载均衡策略",
     "implemented_not_wired",
     "orchestrator/src/agent_router.cpp:314-349 实现轮询/随机/最少负载；"
     "默认 SKILL_MATCH 过滤后退化为轮询；加权/一致性哈希未接入 AgentRouter"),
    ("a2a:o:circuit",
     "熔断机制：失败率超阈值自动切断，超时后试探恢复",
     "implemented_and_wired",
     "server/src/ai_query_service.cpp:102 Query 前 isRequestAllowed；"
     ":114-117 recordSuccess/recordFailure 反馈闭环"),
    ("a2a:o:metrics",
     "RPC 请求/耗时/错误指标与心跳机制",
     "implemented_and_wired",
     "ai_query_service.cpp:265 recordMetrics 记录耗时与成败；"
     "client/src/rpc_client.cpp:522 sendHeartbeat 走 "
     "AgentCommunicationService.Heartbeat，另有 startHeartbeat 线程"),
    ("a2a:o:mcp-rag",
     "RAG-MCP：工具描述向量化 + 相似度 Top-K 筛选",
     "implemented_not_wired",
     "mcp/src/rag/tool_retriever.cpp 等实现存在；examples/"
     "rag_mcp_example.cpp 有示例；未见接入 AI 查询主链"),
    ("a2a:o:mcp-plugins",
     "MCP 插件动态加载（.dll/.so/.dylib）与统一 C ABI",
     "implemented_not_wired",
     "mcp_server_integrated/src/loader/PluginsLoader.cpp 实现扫描加载；"
     "属于独立 MCP server，不在 AI 查询主链上"),
    ("a2a:u:registry",
     "Consul/Etcd 服务注册中心",
     "implemented_not_wired",
     "registry/src/service_registry.cpp 实现 Consul/Etcd/Memory 三种；"
     "server/src/rpc_server.cpp:187 仅配置 memory:// 时走内存注册，"
     "默认未接外部注册中心"),
    (COURSE_ID,
     "简历中的完整项目描述（简历.txt 全部主张）",
     "needs_verification",
     "以 原始文档/简历.txt 为准逐条核实；已核实项见各节点主张，"
     "页面明确区分已接入/未接入/仅示例/待核实"),
]

# (repo-relative path, title, [node ids to attach])
FILES = [
    ("原始文档/简历.txt", "简历原文（主张来源，需逐条核实）",
     [COURSE_ID, "a2a:u:positioning", "a2a:o:claims-status"]),
    ("原始文档/面试收敛项目介绍.md", "面试收敛项目介绍（教学主线）",
     [COURSE_ID, "a2a:mod:m1", "a2a:u:positioning", "a2a:mod:m2",
      "a2a:u:chain-walk", "a2a:mod:m4", "a2a:mod:m6", "a2a:mod:m8"]),
    ("原始文档/后端通信_正常主链与分块知识学习清单.md", "主链与分块知识清单",
     ["a2a:mod:m2", "a2a:mod:m7"]),
    ("docs/architecture.md", "架构文档", ["a2a:mod:m1", "a2a:u:positioning"]),
    ("proto/ai_query.proto", "AI 查询数据契约",
     ["a2a:u:proto-contract", "a2a:o:proto-messages"]),
    ("proto/agent_service.proto", "Agent 通信服务契约（四种调用模式 + 心跳）",
     ["a2a:u:proto-contract", "a2a:o:proto-services",
      "a2a:o:grpc-streaming", "a2a:u:metrics"]),
    ("proto/common.proto", "公共 message（Status/ServiceInfo 等）",
     ["a2a:u:proto-contract"]),
    ("client/src/ai_query_client.cpp", "AI 查询客户端（Stub/Channel/Context）",
     ["a2a:u:grpc-client", "a2a:o:grpc-client-send", "a2a:o:grpc-deadline",
      "a2a:o:chain-sync-async"]),
    ("client/include/agent_rpc/client/ai_query_client.h", "AI 查询客户端头文件",
     ["a2a:u:grpc-client"]),
    ("client/src/rpc_client.cpp", "通用 RPC 客户端（负载均衡/心跳/重连）",
     ["a2a:u:grpc-client", "a2a:u:loadbalance", "a2a:u:metrics"]),
    ("server/src/rpc_server.cpp", "RPC Server（服务注册/keepalive/SSL）",
     ["a2a:u:grpc-server", "a2a:o:grpc-server-recv", "a2a:u:registry"]),
    ("server/src/ai_query_service.cpp", "AIQueryService（入口防护/熔断/指标）",
     ["a2a:u:grpc-server", "a2a:o:grpc-server-recv", "a2a:o:grpc-streaming",
      "a2a:u:circuit", "a2a:o:chain-sync-async"]),
    ("server/src/agent_service.cpp", "AgentCommunicationService（四种模式实现）",
     ["a2a:o:grpc-streaming"]),
    ("server/include/agent_rpc/server/ai_query_service.h", "AIQueryService 头文件",
     ["a2a:u:grpc-server"]),
    ("a2a_adapter/src/a2a_adapter.cpp", "A2A 适配器主流程",
     ["a2a:mod:m3", "a2a:u:adapter-request", "a2a:u:adapter-response"]),
    ("a2a_adapter/src/request_adapter.cpp", "请求转换 RequestAdapter",
     ["a2a:u:adapter-request", "a2a:o:adapter-request"]),
    ("a2a_adapter/src/response_adapter.cpp", "响应/流事件转换 ResponseAdapter",
     ["a2a:u:adapter-response", "a2a:o:adapter-response"]),
    ("a2a_adapter/src/task_manager_wrapper.cpp", "TaskManager 包装（Redis TODO）",
     ["a2a:u:taskstore", "a2a:o:taskstore-status"]),
    ("a2a/src/examples/redis_task_store.cpp", "RedisTaskStore 示例实现",
     ["a2a:u:taskstore", "a2a:o:taskstore-status"]),
    ("a2a/src/server/memory_task_store.cpp", "MemoryTaskStore（主链默认）",
     ["a2a:u:taskstore"]),
    ("a2a/include/a2a/examples/agent_registry.hpp", "Agent 注册中心（标签索引）",
     ["a2a:u:registry", "a2a:o:registry-tags"]),
    ("a2a/include/a2a/models/agent_message.hpp", "A2A 消息模型",
     ["a2a:u:a2a-models", "a2a:o:a2a-models"]),
    ("a2a/include/a2a/models/agent_task.hpp", "A2A 任务模型",
     ["a2a:u:a2a-models", "a2a:o:a2a-models"]),
    ("orchestrator/src/agent_router.cpp", "AgentRouter（意图/过滤/选择）",
     ["a2a:u:router", "a2a:o:router-strategy"]),
    ("registry/src/service_registry.cpp", "ServiceRegistry（Consul/Etcd/Memory）",
     ["a2a:u:registry", "a2a:o:registry-tags"]),
    ("examples/ai_orchestrator/orchestrator_main.cpp", "Orchestrator 示例主程序",
     ["a2a:u:router", "a2a:u:taskstore"]),
    ("common/include/agent_rpc/common/load_balancer.h", "负载均衡策略族",
     ["a2a:u:loadbalance", "a2a:o:loadbalance"]),
    ("common/src/load_balancer.cpp", "负载均衡实现",
     ["a2a:u:loadbalance"]),
    ("common/include/agent_rpc/common/circuit_breaker.h", "熔断器",
     ["a2a:u:circuit", "a2a:o:circuit"]),
    ("common/include/agent_rpc/common/metrics.h", "指标（counter/gauge/histogram）",
     ["a2a:u:metrics", "a2a:o:metrics"]),
    ("mcp/src/mcp_client.cpp", "MCP Client（JSON-RPC）",
     ["a2a:u:mcp-client", "a2a:o:mcp-transport", "a2a:u:mcp-agent-loop",
      "a2a:o:mcp-agent-loop"]),
    ("mcp/include/agent_rpc/mcp/mcp_client.h", "MCP Client 接口与配置",
     ["a2a:u:mcp-client", "a2a:u:mcp-agent-loop"]),
    ("mcp/src/mcp_agent_integration.cpp", "单 Agent 的 MCP 集成入口",
     ["a2a:u:mcp-agent-loop", "a2a:o:mcp-agent-loop"]),
    ("mcp/include/agent_rpc/mcp/mcp_agent_integration.h", "MCP Agent 集成接口",
     ["a2a:u:mcp-agent-loop"]),
    ("mcp/src/mcp_tool_manager.cpp", "MCP 工具管理与服务集成",
     ["a2a:u:mcp-agent-loop", "a2a:o:mcp-agent-loop"]),
    ("mcp_server_integrated/src/loader/PluginsLoader.cpp", "插件动态加载",
     ["a2a:u:mcp-plugins", "a2a:o:mcp-plugins"]),
    ("mcp/src/rag/tool_retriever.cpp", "RAG 工具检索",
     ["a2a:u:mcp-rag", "a2a:o:mcp-rag"]),
    ("examples/rag_mcp_example.cpp", "RAG-MCP 示例",
     ["a2a:u:mcp-rag"]),
]


def seed(conn, repo_root=None):
    """Insert the A2A course graph, claims, and source index. Idempotent.

    repo_root=None seeds graph + claims only (no file registration) — used by
    tests and by installs where the project repo is unavailable. The auto
    resolution of the default repo path lives in the Orchestrator.
    """
    repo_root = Path(repo_root) if repo_root else None
    existed = conn.execute(
        "SELECT 1 FROM nodes WHERE id = ?", (COURSE_ID,)
    ).fetchone() is not None
    before = conn.total_changes
    with transaction(conn):
        conn.executemany(
            "INSERT OR IGNORE INTO nodes (id, course_id, type, title, summary,"
            " sort_order) VALUES (?,?,?,?,?,?)",
            [(nid, COURSE_ID, ntype, title, summary, order)
             for (nid, ntype, title, summary, order) in NODES],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO edges (src, dst, type, note) VALUES (?,?,?,?)",
            EDGES,
        )
        # Content migration: the new Agent integration unit sits between the
        # low-level MCP client and the standalone server/plugin material.
        # Remove the pre-existing shortcut when upgrading an older database.
        conn.execute(
            "DELETE FROM edges WHERE src=? AND dst=? AND type='sequence'",
            ("a2a:u:mcp-client", "a2a:u:mcp-plugins"),
        )
        if not existed:
            for node_id, text, status, evidence in CLAIMS:
                conn.execute(
                    "INSERT INTO claims (course_id, node_id, text, status,"
                    " evidence, updated_at) VALUES (?,?,?,?,?,?)",
                    (COURSE_ID, node_id, text, status, evidence,
                     graph.now_iso()),
                )
        changed = conn.total_changes > before
        if changed:
            conn.execute(
                "INSERT INTO graph_versions (applied_at, proposal_id, note)"
                " VALUES (?,NULL,?)",
                (graph.now_iso(),
                 "a2a content expansion" if existed else "a2a initial seed"),
            )

    warnings = []
    registered = 0
    if repo_root and repo_root.is_dir():
        for rel, title, node_ids in FILES:
            path = repo_root / rel
            if not path.is_file():
                warnings.append("missing file: %s" % rel)
                continue
            try:
                info = sources.register_file(
                    conn, COURSE_ID, str(path), [str(repo_root)],
                    title=title, source_id="src:a2a:" + rel)
            except Exception as exc:  # keep seeding the rest
                warnings.append("%s: %s" % (rel, exc))
                continue
            registered += 1
            with transaction(conn):
                conn.executemany(
                    "INSERT OR IGNORE INTO node_sources (node_id, source_id,"
                    " anchor) VALUES (?,?,'')",
                    [(nid, info["source_id"]) for nid in node_ids],
                )
    else:
        warnings.append("repo not found: %s (set %s)"
                        % (repo_root or default_repo_root(), _ENV_ROOT))
    return {"changed": changed, "sources": registered,
            "warnings": warnings,
            "repo_root": str(repo_root) if repo_root else None}
