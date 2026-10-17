"""A2A course overlay organization (2026-09-23 可视化收敛轮):

1. topic_org: classify the 46 flat mcp-plugins topic records into five content
   themes + one archive group. Decisions were made by reading every raw
   teaching_updates payload (#12-#32); each theme's note cites the update ids
   it comes from. Original payloads untouched; rows carry origin
   'organize-2026-09-23' so 后补归类 stays distinguishable from real records.
2. links: cross-view associations for the MCP Server slice (code modules from
   the approved Archify map ↔ learning nodes ↔ skeleton knowledge anchors ↔
   themes). basis marks 源码确认 / 配置示例 / 推断 / 人工整理.
3. code_maps: the approved Archify architecture JSON, enriched per component
   with responsibility / input→process→output / key source files, authored
   from previews/a2a-archify/README.md source evidence (paths verified
   against the working tree 2026-09-23).
"""

import json
from pathlib import Path

from .db import PROJECT_ROOT
from . import organize

COURSE_ID = 'a2a-agent-communication'
SECTION = 'a2a:u:mcp-plugins'
ORIGIN = 'organize-2026-09-23'

PREVIEW_JSON = (PROJECT_ROOT / 'previews' / 'a2a-archify'
                / 'a2a.architecture.json')

# ---------------------------------------------------------------- topic org
# (group_key, group_title, kind, note, [topic titles]) — 46 titles total.
TOPIC_ORG = [
    ('t1-overview', '首轮总览：MCP Server 职责六小点', 'theme',
     '09-17 备课种子六小点，同日首轮讲解完成（记录 #12-#15）。',
     ['MCP Server 进程入口与传输启动',
      'initialize / tools/list / tools/call 请求分发',
      '插件扫描、动态加载与统一 C ABI',
      'PluginAPI 生命周期',
      '一个工具从发现到执行的最小闭环',
      '实现状态与主链接入边界']),
    ('t2-arch', '协议分层与架构映射', 'theme',
     '09-18~19 概念讲解：MCP/RPC/A2A 分层、Host/Client/Server 项目映射'
     '（记录 #16-#21）。',
     ['从业务目标推导 MCP Server 架构与构建顺序',
      'MCP 与 RPC、A2A 的协议分层关系',
      '项目实现与通用 MCP 的对应及差异',
      'Host、Client、Server 的职责与项目映射',
      'Tools、Resources、Prompts 与工具设计边界',
      'mcp_server_integrated 的项目职责总览',
      '从零实现一个工具的最小 MCP Server 纵向切片',
      '最小请求响应与线程边界',
      'MCP Server 与 Transport 的职责区别',
      'STDIO 与 SSE 的连接维护模型']),
    ('t3-retell', '骨架复述与职责链校正', 'theme',
     '09-19 四块骨架复述自测，留下首轮疑问与回补项（记录 #22-#23）。',
     ['最小 MCP Server 四块骨架复述与校正',
      '最小请求处理职责链',
      '工具适配的最小含义',
      'initialize、tools/list、tools/call 的语义区分',
      'STDIO 连接维护与请求路由边界']),
    ('t4-tools', '工具实现与 JSON-RPC 信封', 'theme',
     '09-19 提出疑问、09-21 展开实现：ITool/ToolRegistry/ResponseBuilder'
     ' 与协议格式（记录 #25、#29）。',
     ['JSON-RPC 请求与响应按 id 关联',
      'MCP 请求、成功响应、错误响应与通知格式',
      '从最小协议骨架演进到多传输层',
      'ITool：工具描述与执行接口',
      'CalculatorTool：describe 与 call 的分工',
      '工具描述字段与 inputSchema',
      '工具参数校验的边界',
      'ToolRegistry：统一存储与按名称查找',
      'ResponseBuilder：JSON-RPC 成功/错误信封',
      '请求 id 关联与错误码',
      '传输边界前的最小请求闭环']),
    ('t5-resume-skeleton', '简历边界与当前完整骨架', 'theme',
     '09-19 简历映射 + 09-22 M2 完整骨架登记与运行自检（记录 #24、#31；'
     '骨架本体与源码映射见 skeletons / skeleton_map）。',
     ['简历五项功能的需求与最简实现映射',
      '简历插件与测试表述的实现边界',
      '完整重构式 MCP Server 学习骨架',
      '骨架运行自检与边界']),
    ('archive', '备课安排与旧版骨架约定', 'archive',
     '学习顺序安排与 V0…V2 累计演进式约定；2026-09-22 起骨架规范改为'
     '「一个内容一个完整骨架」，这些作为历史安排归档保留'
     '（记录 #24-#28、#30）。',
     ['MCP Server 后续学习任务与手写骨架',
      'MCP Server 开发演进式学习顺序',
      '累计演进式代码骨架约定',
      '整体与单知识点的总—分—总闭环',
      'V0：单STDIO最小MCP协议端点骨架',
      'V1：在V0上累计加入多传输层',
      'V0/V1实现边界与细节交接',
      'V0/V1单文件累计教学骨架',
      'V1 SSE教学骨架与真实实现边界',
      'V2插件系统累计骨架']),
]

# ------------------------------------------------- course outline (简纲)
# 2026-09-24 followup：整个 A2A 的统一讲解规划。组织层，只含阶段目标与
# 待展开位置；未到的阶段不预生成小项/教案/材料。不推断完成、不重置进度。
OUTLINE = [
    {'stage_key': 's1-minimal-loop', 'seq': 1, 'status': 'current',
     'title': '最小工具调用闭环（MCP Server）',
     'goal': '必要基础（MCP/JSON-RPC/Transport）→ 最简完整骨架五模块 → '
            '真实源码对照。当前学习位置所在阶段。',
     'note': '小项与教案由教学计划（plan v2）展开；过程记录见该单元小点。'},
    {'stage_key': 's2-agent-interaction', 'seq': 2, 'status': 'pending',
     'title': 'Agent 间交互：A2A 消息与任务生命周期',
     'goal': 'A2A SDK 消息模型、任务状态机、Agent 间协作语义。',
     'note': '待展开：进入本阶段时由整体讲解窗口拆分小项与教案。'},
    {'stage_key': 's3-coordination-edge', 'seq': 3, 'status': 'pending',
     'title': '协调与外部接入：Orchestrator / Registry / gRPC 边界',
     'goal': '意图识别与候选选择、注册发现与心跳、协议适配与项目四种 '
            'RPC 模式。',
     'note': '待展开。'},
    {'stage_key': 's4-full-chain-resume', 'seq': 4, 'status': 'pending',
     'title': '完整通路与简历映射',
     'goal': '沿一次 AI 查询走通全链路；逐条核实简历主张的实现状态'
            '（已接入/示例/计划/待验证）并整理面试叙述。',
     'note': '待展开。'},
]

# --------------------------------------- topic → teaching item (按标题归位)
# 2026-09-24 讲解重构：把 46 条过程记录挂到 plan v2 的教学小项下。
# 只挂标题含义明确的；跨层或不确定的保留在主题组（item_id 为空）。
# 值 = 教学小项标题，运行时解析为当前 active plan 的 item id，不硬编码数字。
TOPIC_ITEM_MAP = {
    # → 基础知识层 · MCP 与 JSON-RPC 基础
    'MCP 与 JSON-RPC 基础': [
        'MCP Server 进程入口与传输启动',
        'initialize / tools/list / tools/call 请求分发',
        '一个工具从发现到执行的最小闭环',
        '实现状态与主链接入边界',
        'MCP 与 RPC、A2A 的协议分层关系',
        'Tools、Resources、Prompts 与工具设计边界',
        '从零实现一个工具的最小 MCP Server 纵向切片',
        'JSON-RPC 请求与响应按 id 关联',
        'MCP 请求、成功响应、错误响应与通知格式',
        '请求 id 关联与错误码',
    ],
    # → 基础知识层 · Client / Server / Host 角色
    'Client / Server / Host 角色': [
        'Host、Client、Server 的职责与项目映射',
        '项目实现与通用 MCP 的对应及差异',
        'mcp_server_integrated 的项目职责总览',
        '从业务目标推导 MCP Server 架构与构建顺序',
    ],
    # → 基础知识层 · Transport / STDIO / SSE 基础
    'Transport / STDIO / SSE 基础': [
        'MCP Server 与 Transport 的职责区别',
        'STDIO 与 SSE 的连接维护模型',
        '最小请求响应与线程边界',
    ],
    # → 骨架层 · 请求响应构建与路由分发
    '请求响应构建与路由分发': [
        '最小 MCP Server 四块骨架复述与校正',
        '最小请求处理职责链',
        '工具适配的最小含义',
        'initialize、tools/list、tools/call 的语义区分',
        'ITool：工具描述与执行接口',
        'CalculatorTool：describe 与 call 的分工',
        '工具描述字段与 inputSchema',
        '工具参数校验的边界',
        'ToolRegistry：统一存储与按名称查找',
        'ResponseBuilder：JSON-RPC 成功/错误信封',
        '传输边界前的最小请求闭环',
    ],
    # → 骨架层 · 多传输层实现
    '多传输层实现': [
        '从最小协议骨架演进到多传输层',
    ],
    # → 骨架层 · 插件系统与动态加载（首轮总览里的插件概念点）
    '插件系统与动态加载': [
        '插件扫描、动态加载与统一 C ABI',
        'PluginAPI 生命周期',
    ],
    # → 源码与简历层 · 简历主张实现状态核实
    '简历主张实现状态核实': [
        '简历五项功能的需求与最简实现映射',
        '简历插件与测试表述的实现边界',
    ],
    # 保留在主题级（不确定或跨层）：STDIO 连接维护与请求路由边界、
    # 完整重构式 MCP Server 学习骨架、骨架运行自检与边界、archive 全组。
}

# 语义校准（2026-09-24）：这些条目由「已讲解」证据被标成 done；按
# 讲义已输出≠已理解 的区分改标 presented，原 note 保留并追加说明。
PRESENTED_CORRECTION = {
    '基础知识层：MCP、JSON-RPC、Transport 与 Client/Server': None,
    'MCP 与 JSON-RPC 基础': None,
    'Client / Server / Host 角色': None,
    'Transport / STDIO / SSE 基础': None,
    '请求响应构建与路由分发': None,
    '多传输层实现': None,
}


def realign_records(conn):
    """One-shot, idempotent realignment of the A2A records onto plan v2.

    NOT called from initialize(): it asserts on real evidence (active plan
    with the expected item titles) and no-ops anywhere else. Safe to re-run:
    already-mapped titles are rewritten identically, already-presented items
    are skipped. Returns a report; never deletes or rewrites raw records."""
    from . import teaching
    report = {'applied': False, 'mapped': 0, 'missing_titles': [],
              'missing_items': [], 'presented_corrected': []}
    plan = conn.execute(
        "SELECT * FROM teaching_plans WHERE course_id=? AND status='active'",
        (COURSE_ID,)).fetchone()
    if plan is None:
        return report
    items = {r['title']: r for r in conn.execute(
        'SELECT id,title,status FROM teaching_items WHERE plan_id=?',
        (plan['id'],)).fetchall()}
    for item_title, titles in TOPIC_ITEM_MAP.items():
        it = items.get(item_title)
        if it is None:
            report['missing_items'].append(item_title)
            continue
        r = organize.map_topics_to_item(conn, COURSE_ID, SECTION, it['id'],
                                        titles, origin='realign-2026-09-24')
        report['mapped'] += r['mapped']
        report['missing_titles'] += r['missing']
    # 语义校准：done → presented（仅当当前确实标着 done；讲授证据≠验证）
    cur = teaching._cursor(conn, COURSE_ID)
    base = cur['state_version'] if cur else None
    updates = []
    for title in PRESENTED_CORRECTION:
        it = items.get(title)
        if it is not None and it['status'] == 'done':
            updates.append({'id': it['id'], 'status': 'presented'})
    if updates:
        teaching.commit(
            conn, COURSE_ID, SECTION, 'main', items_update=updates,
            handoff='2026-09-24 语义校准：讲授记录 ≠ 验证通过，以上条目按新'
                    '语义改标 presented（已讲解），待理解确认/验证后再由 main'
                    ' 标 done。原始记录与 note 未改。',
            base_state_version=base)
        report['presented_corrected'] = [u['id'] for u in updates]
    report['applied'] = True
    return report



# 2026-09-25 节层结构清理：插件单元下曾三代并存（4 个临时粗分项 +
# 8 条缺 1–4 的残缺登记 + 正式 12 小节）。作废留痕不物理删除；正式 12 项
# 去掉标题硬序号、按 3 节 × 4 小节挂好（分节方案经用户确认）。
PLUGIN_UNIT_TITLE = '插件系统与动态加载'
PLUGIN_SECTIONS = ['概念与生命周期', 'ABI 契约与宿主注册表', '路由分发与边界闭环']


def restructure_plugin_unit(conn):
    """One-shot, idempotent restructure of the plugin unit into sections.

    Same discipline as realign_records: asserts on real evidence (active plan
    + the expected unit title), no-ops elsewhere; everything goes through
    teaching.commit(role='main') so the audit stream records the change."""
    import re
    from . import teaching
    report = {'applied': False, 'retracted': [], 'sections': [],
              'renamed': [], 'reparented': [], 'skipped': []}
    plan = conn.execute(
        "SELECT * FROM teaching_plans WHERE course_id=? AND status='active'",
        (COURSE_ID,)).fetchone()
    if plan is None:
        return report
    items = [dict(r) for r in conn.execute(
        'SELECT * FROM teaching_items WHERE plan_id=?', (plan['id'],))]
    unit = next((i for i in items
                 if i['title'] == PLUGIN_UNIT_TITLE), None)
    if unit is None:
        return report
    kids = [i for i in items if i['parent_id'] == unit['id']]
    numbered = [(int(re.match(r'^(\d+)\.\s*', i['title']).group(1)), i)
                for i in kids if i['status'] != 'retracted'
                and re.match(r'^\d+\.\s*', i['title'])]
    if not numbered:
        # 没有带硬序号的子项：若节已存在说明已清理过，幂等空转
        report['applied'] = any(i['kind'] == 'section' for i in kids)
        return report
    by_num = {}
    for n, i in numbered:
        by_num.setdefault(n, []).append(i)
    if any(len(g) > 2 for g in by_num.values()):
        report['skipped'].append('unexpected: >2 items share one number')
        return report
    # 同号两条时，id 小的是残缺首登（先登记的只有 5–12），id 大的是正式项。
    formal, broken = [], []
    for n, g in sorted(by_num.items()):
        g.sort(key=lambda i: i['id'])
        if len(g) == 1:
            formal.append((n, g[0]))
        else:
            broken.append(g[0])
            formal.append((n, g[-1]))
    if len(formal) != 12:
        report['skipped'].append(
            'expected 12 formal numbered items, found %d' % len(formal))
        return report
    broken_note_merge = {}  # 残缺项的材料备注并入正式项，内容不丢
    for b in broken:
        n = int(re.match(r'^(\d+)\.\s*', b['title']).group(1))
        f = next((i for nn, i in formal if nn == n), None)
        if b['note'].strip() and f is not None \
                and b['note'] not in f['note']:
            broken_note_merge[f['id']] = b['note']
    temp = [i for i in kids
            if '上一轮临时拆分项' in i['note'] and not re.match(
                r'^\d+\.\s*', i['title'])]
    cur = teaching._cursor(conn, COURSE_ID)
    base = cur['state_version'] if cur else None
    sections = {i['title']: i for i in kids if i['kind'] == 'section'}
    missing = [t for t in PLUGIN_SECTIONS if t not in sections]
    if missing:
        r = teaching.commit(
            conn, COURSE_ID, SECTION, 'main',
            items_add=[{'kind': 'section', 'title': t, 'parent_id': unit['id'],
                        'seq': PLUGIN_SECTIONS.index(t) + 1}
                       for t in missing],
            handoff='2026-09-25 插件单元分节（节层上线）：' + '、'.join(missing),
            base_state_version=base)
        base = r['state_version']
        kids = [dict(r2) for r2 in conn.execute(
            'SELECT * FROM teaching_items WHERE parent_id=?', (unit['id'],))]
        sections = {i['title']: i for i in kids if i['kind'] == 'section'}
        report['sections'] = [sections[t]['id'] for t in PLUGIN_SECTIONS]
    updates = []
    for i in temp + broken:
        if i['status'] != 'retracted':
            updates.append({'id': i['id'], 'status': 'retracted',
                            'note': i['note'] + ' [2026-09-25 结构清理作废：'
                                    '已由节层+正式12小节替代]'})
            report['retracted'].append(i['id'])
    for n, i in sorted(formal, key=lambda t: t[0]):
        sec_title = PLUGIN_SECTIONS[(n - 1) // 4]
        new_title = re.sub(r'^\d+\.\s*', '', i['title'])
        u = {'id': i['id']}
        if i['status'] == 'retracted':
            u['status'] = 'pending'  # 防御：正式项不应处于作废态
        if i['title'] != new_title:
            u['title'] = new_title
            report['renamed'].append(i['id'])
        merged_note = broken_note_merge.get(i['id'])
        if merged_note:
            u['note'] = i['note'] + ' 材料：' + merged_note
        if i['parent_id'] != sections[sec_title]['id']:
            u['parent_id'] = sections[sec_title]['id']
            report['reparented'].append(i['id'])
        if i['seq'] != (n - 1) % 4 + 1:
            u['seq'] = (n - 1) % 4 + 1
        if len(u) > 1:
            updates.append(u)
    if updates:
        teaching.commit(
            conn, COURSE_ID, SECTION, 'main', items_update=updates,
            handoff='2026-09-25 插件单元结构清理：作废临时/残缺重复项（留痕），'
                    '正式 12 小节去硬序号并按 3 节×4 小节归位。',
            base_state_version=base)
    report['applied'] = True
    return report


# ----------------------------------------------------------------- links
_SKEL_SRC = 'skel-986c17128e'


def _k(anchor):
    return '%s#%s' % (_SKEL_SRC, anchor)


LINKS = [
    # 代码模块 ↔ 学习位置（单元同时是主链步骤：mcp 段的 unit 均在 sequence 链上）
    ('code_module', 'toolserver', 'node', 'a2a:u:mcp-plugins',
     'source-confirmed', 'MCP Server 骨架与插件讲解单元；映射依据 skeleton_map'
     ' real_ref → mcp_server_integrated/src/server/Server.cpp'),
    ('code_module', 'plugins', 'node', 'a2a:u:mcp-plugins',
     'source-confirmed', 'PluginsLoader.cpp:34 动态加载讲解所在单元'),
    ('code_module', 'mcp', 'node', 'a2a:u:mcp-agent-loop',
     'source-confirmed', 'MCPAgentIntegration 所在讲解单元'
     '（mcp/src/mcp_agent_integration.cpp:32）'),
    ('code_module', 'mcp', 'node', 'a2a:u:mcp-client',
     'source-confirmed', 'mcp_client.cpp:153 callTool；385-387 STDIO/SSE 传输选择'),
    # 代码模块 ↔ 知识锚点（骨架锚点；对应关系出自 skeleton_map 的 real_ref）
    ('code_module', 'toolserver', 'knowledge', _k('Response / MCPServer::handle'),
     'source-confirmed', 'skeleton_map → src/server/Server.cpp:L34-L58,L267-L306'),
    ('code_module', 'toolserver', 'knowledge', _k('ITransport / StdioTransport / SseTransport'),
     'source-confirmed', 'skeleton_map → ITransport.h / main.cpp / SseTransport.cpp'),
    ('code_module', 'plugins', 'knowledge', _k('plugin_api.h / PluginHost'),
     'source-confirmed', 'skeleton_map → PluginAPI.h:L38-L86; PluginsLoader.cpp:L34-L164'),
    ('code_module', 'plugins', 'knowledge', _k('example_plugin.cpp'),
     'source-confirmed', 'skeleton_map → plugins/calculator 等示例插件'),
    ('code_module', 'toolserver', 'knowledge', _k('demo()'),
     'manual', '骨架自检入口；Cherry Studio 结果需独立核验（skeleton_map 边界）'),
    # 学习位置 ↔ 知识锚点（同一 skeleton_map 事实的另一入口，程序可双向查询）
    ('node', 'a2a:u:mcp-plugins', 'knowledge', _k('Response / MCPServer::handle'),
     'source-confirmed', 'skeleton_map'),
    ('node', 'a2a:u:mcp-plugins', 'knowledge', _k('ITransport / StdioTransport / SseTransport'),
     'source-confirmed', 'skeleton_map'),
    ('node', 'a2a:u:mcp-plugins', 'knowledge', _k('plugin_api.h / PluginHost'),
     'source-confirmed', 'skeleton_map'),
    ('node', 'a2a:u:mcp-plugins', 'knowledge', _k('example_plugin.cpp'),
     'source-confirmed', 'skeleton_map'),
    ('node', 'a2a:u:mcp-plugins', 'knowledge', _k('demo()'),
     'source-confirmed', 'skeleton_map'),
    # 主题（后补归类） ↔ 代码模块
    ('theme', SECTION + '#t1-overview', 'code_module', 'toolserver',
     'source-confirmed', '六小点内容即 Server/Transport/请求分发'),
    ('theme', SECTION + '#t1-overview', 'code_module', 'plugins',
     'source-confirmed', '六小点含插件扫描/动态加载/PluginAPI'),
    ('theme', SECTION + '#t2-arch', 'code_module', 'mcp',
     'manual', '协议分层概念映射到 MCP 工具接入模块'),
    ('theme', SECTION + '#t2-arch', 'code_module', 'toolserver',
     'manual', 'Server/Transport 职责区别的讲解对象'),
    ('theme', SECTION + '#t3-retell', 'code_module', 'toolserver',
     'manual', '四块骨架复述的对象是 Server/Transport/工具/响应'),
    ('theme', SECTION + '#t4-tools', 'code_module', 'toolserver',
     'source-confirmed', 'ITool/ResponseBuilder 对应 Server.cpp 分发与信封'),
    ('theme', SECTION + '#t5-resume-skeleton', 'code_module', 'toolserver',
     'source-confirmed', '当前骨架即本模块的教学重构'),
    ('theme', SECTION + '#t5-resume-skeleton', 'code_module', 'plugins',
     'source-confirmed', '简历条目3/4：插件系统与示例插件'),
]

# ------------------------------------------------------- code map enrichment
# Authored from previews/a2a-archify/README.md source evidence (verified
# against the working tree 2026-09-23). basis 区分源码确认与配置/示例接线。
DETAILS = {
    'client': {
        'role': '查询客户端：封装 Stub/Channel/Context，发起 Query / QueryStream。',
        'io': {'input': '上层调用的查询文本与请求参数',
               'process': '构造 AIQueryRequest，经 gRPC stub 同步/流式调用',
               'output': 'gRPC 响应 / AIStreamEvent 流'},
        'files': ['client/src/ai_query_client.cpp',
                  'client/include/agent_rpc/client/ai_query_client.h'],
        'basis': 'source-confirmed'},
    'gateway': {
        'role': 'gRPC 服务入口：入口防护、取消、熔断与指标。',
        'io': {'input': '客户端 Query / QueryStream 请求',
               'process': '取消与熔断判断后在 L111 调用适配层，并记录指标',
               'output': 'gRPC 响应 / 流式回包'},
        'files': ['server/src/ai_query_service.cpp:71 (Query)、:146 (QueryStream)'],
        'basis': 'source-confirmed'},
    'adapter': {
        'role': '协议适配：gRPC 侧请求 ↔ A2A 消息。',
        'io': {'input': '来自服务入口的结构化请求',
               'process': 'L86-93 转换请求 → send_message → 转换响应',
               'output': '发给协调端点的 A2A HTTP 消息'},
        'files': ['a2a_adapter/src/a2a_adapter.cpp:29 (initialize 使用配置的'
                  ' orchestrator_url)、:86-93'],
        'basis': 'config-example',
        'note': '目标端点由配置接线，不是运行时部署证明。'},
    'router': {
        'role': '协调 Agent（示例入口）：意图分类后分派任务。',
        'io': {'input': '适配层转来的 A2A 消息',
               'process': 'L389 意图分类 → L415-449 按标签发现端点并 HTTP 发送；'
                          '通用问答分支 L457-521 可选调用 MCP 工具',
               'output': '给专业 Agent 的任务 / 工具调用结果'},
        'files': ['examples/ai_orchestrator/orchestrator_main.cpp:389、415-449、457-521'],
        'basis': 'config-example',
        'note': 'MCP 是示例协调端的可选分支，并非每次请求必经。'},
    'registry': {
        'role': '注册中心：按标签发现可用 Agent 端点。',
        'io': {'input': '协调端的端点查询',
               'process': '按标签匹配已登记端点',
               'output': '目标 Agent 的端点信息'},
        'files': ['registry/（端点登记与发现）'],
        'basis': 'manual',
        'note': '发现端点，不作为任务转发的一跳（预览 README 说明）。'},
    'agent': {
        'role': '专业 Agent：独立 A2A HTTP 端点，承接具体任务。',
        'io': {'input': '协调端发来的 A2A 任务消息',
               'process': '各自领域处理',
               'output': 'A2A 任务结果'},
        'files': ['（端点由配置接线，示例外 Agent 未逐一绘制）'],
        'basis': 'manual'},
    'mcp': {
        'role': 'MCP 工具接入：协调端接入 MCP 工具的可选通道。',
        'io': {'input': '通用问答分支的工具调用决定',
               'process': 'enable_mcp 与 server 路径配置（:32）；callTool（:153）；'
                          'STDIO/SSE 传输选择（:385-387）；工具不可用可降级，'
                          '不阻塞初始化',
               'output': '工具调用结果'},
        'files': ['mcp/src/mcp_agent_integration.cpp:32',
                  'mcp/src/mcp_client.cpp:153、385-387'],
        'basis': 'source-confirmed'},
    'toolserver': {
        'role': 'MCP 工具服务：Server 按方法分发，Transport 维护连接。',
        'io': {'input': 'STDIO / SSE 上的 JSON-RPC 请求',
               'process': 'method→handler 映射（initialize / tools/list / '
                          'tools/call 等）分发处理',
               'output': 'JSON-RPC 成功/错误响应'},
        'files': ['mcp_server_integrated/src/server/Server.cpp:36'],
        'basis': 'source-confirmed'},
    'plugins': {
        'role': '动态插件：Tools · Prompts · Resources 的扫描、加载与执行。',
        'io': {'input': '插件目录与统一 C ABI 约定',
               'process': '递归扫描共享库并动态加载（:34）',
               'output': '注册到 Server 的工具/提示/资源'},
        'files': ['mcp_server_integrated/src/loader/PluginsLoader.cpp:34'],
        'basis': 'source-confirmed'},
}

RESPONSE_NOTE = ('响应沿原路返回（ResponseAdapter 转回 gRPC），图中不重复'
                 '画反向箭头（预览 README 说明）。')


def seed(conn, preview_json=None):
    """Idempotent overlay seed: topic org + links + enriched code map."""
    organize.setup(conn)
    for key, title, kind, note, titles in TOPIC_ORG:
        organize.add_topic_org(conn, COURSE_ID, SECTION, key, title, titles,
                               kind=kind, note=note, origin=ORIGIN)
    organize.add_links(conn, COURSE_ID, LINKS, origin_note=ORIGIN)
    organize.save_outline(conn, COURSE_ID, OUTLINE, origin=ORIGIN)

    path = Path(preview_json) if preview_json else PREVIEW_JSON
    seeded_map = False
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf-8'))
        for comp in data.get('components', []):
            comp['detail'] = DETAILS.get(comp['id'], {'basis': 'manual'})
        data['response_note'] = RESPONSE_NOTE
        organize.save_code_map(conn, COURSE_ID,
                               data.get('meta', {}).get('title', ''), data,
                               origin='archify-preview-2026-09-23')
        seeded_map = True
    return {'topics_organized': sum(len(t) for *_x, t in TOPIC_ORG),
            'links': len(LINKS), 'code_map': seeded_map,
            'outline': len(OUTLINE)}
