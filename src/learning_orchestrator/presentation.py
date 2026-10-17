"""Shared display names. Source titles/ids remain intact for citations.
Existing aliases shorten legacy labels; new authored titles stay author-controlled.
"""
import re

SOURCE_NAMES = {
    'bagu-s1-kb-network': ('网络分层与寻址', '协议分层、IP、端口与路由'),
    'bagu-s1-kb-dns': ('DNS', '域名解析、缓存与故障定位'),
    'bagu-s1-kb-tcp': ('TCP', '连接管理、可靠传输与流量控制'),
    'bagu-s1-kb-tls': ('TLS 与 HTTPS', '加密通道、证书信任与故障定位'),
    'bagu-s1-kb-http': ('HTTP', '报文解析、路由、状态码与持久连接'),
    'bagu-s1-kb-reactor': ('I/O 与 Reactor', 'socket、非阻塞 I/O、epoll 与 Buffer'),
    'bagu-s1-kb-upstream': ('服务间调用', 'HTTP 转发、异步响应、超时与任务受理'),
    'bagu-s1-kb-project': ('muduo 与 HttpServer', '框架接收、HTTP 处理与接口实现'),
}
MODULE_NAMES = {
    'project:M01': ('连接接入与回调', 'muduo 把接收字节交给 HTTP 层'),
    'project:M02': ('连接与解析上下文', '每条连接保存自己的 HTTP 解析进度'),
    'project:M03': ('HTTP 增量解析', '区分完整报文、半包与格式错误'),
    'project:M04': ('路由分发', '按 Method 与 Path 选择处理器'),
    'project:M05': ('业务处理与异步执行', '中间件、处理器与慢业务调度'),
    'project:M06': ('响应构建与发送', '序列化 HTTP 响应并交给连接发送'),
    'project:M07': ('异步完成与连接边界', '超时、断连与一次性响应'),
    'project:M08': ('连接复用与关闭', '重置解析状态，处理后续请求与连接去留'),
}
COURSE_NAMES = {'bagu-agent1-backend': 'Agent1 · HttpServer',
                'a2a-agent-communication': 'A2A · 多 Agent 通信',
                'cmu-15-445-f2025': 'CMU 15-445 · 数据库系统'}
PROJECTS = {'bagu-agent1-backend', 'a2a-agent-communication'}


def source_name(source_id, title):
    name, description = SOURCE_NAMES.get(source_id, (title, ''))
    return {'title': name, 'description': description, 'original_title': title}


def module_name(item_id, title):
    name, description = MODULE_NAMES.get(item_id, (title, ''))
    return {'title': name, 'description': description, 'original_title': title}


def point_title(title):
    return re.sub(r'^[NDTSHRUM]\d+\s*[｜|·：:\s]\s*', '', title)


def course_title(course_id, title):
    return COURSE_NAMES.get(course_id, title)
