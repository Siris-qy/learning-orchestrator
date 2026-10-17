"""Question-bank taxonomy is independent of knowledge availability and mastery."""
import re

LABELS = {'cpp':'C++', 'algorithms':'数据结构与算法', 'network':'网络与通信',
          'os':'操作系统与并发', 'database':'数据库与缓存', 'agent':'Agent / AI',
          'engineering':'工程与工具', 'project':'项目设计与实践', 'other':'待分类'}
RULES = [
    ('cpp', r'C\+\+|cpp|shared_ptr|unique_ptr|weak_ptr|RAII|STL|vector|unordered|左值|右值|虚函数|多态|析构|构造|模板|lambda|智能指针|移动语义|完美转发|引用折叠'),
    ('algorithms', r'算法|复杂度|链表|二叉|红黑树|B\+?树|排序|二分|动态规划|哈希|hash|堆|递归|滑动窗口|回溯|图论|并查集|最短路径|LRU|手撕'),
    ('network', r'TCP|UDP|HTTP|TLS|SSL|DNS|RPC|gRPC|protobuf|socket|epoll|select|poll|Reactor|Proactor|SSE|QUIC|网络|握手|挥手|粘包|拥塞|传输|报文|长连接|心跳'),
    ('os', r'操作系统|内核|进程|线程|协程|死锁|互斥|自旋|原子|并发|信号量|共享内存|虚拟内存|页表|缺页|mmap|fork|exec|IPC|调度|中断|文件系统|零拷贝'),
    ('database', r'MySQL|Redis|SQL|数据库|缓存|事务|索引|MVCC|持久化|主从|分库|分表|锁粒度'),
    ('agent', r'Agent|RAG|MCP|LLM|Transformer|Tokenizer|Embedding|Prompt|LangChain|LangGraph|LoRA|模型|向量|检索增强|提示词|幻觉|微调|大语言|多智能体|工具调用|skills?'),
    ('engineering', r'Docker|Kubernetes|k8s|Git\b|GDB|CMake|编译|链接|调试|性能分析|压测|部署|CI/CD|监控|Linux命令'),
    ('project', r'项目|设计模式|架构|设计一个|系统设计|幂等|熔断|负载均衡|高可用|业务|瓶颈|优化|难点|重构'),
]


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS question_categories(
      question_id TEXT NOT NULL REFERENCES questions(id),
      category TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'auto-title',
      PRIMARY KEY(question_id, category))''')


def suggest(stem, question_id='', course_id=''):
    """Conservative broad tags; multiple categories are allowed, not coverage claims."""
    tags=[key for key, pattern in RULES if re.search(pattern, stem, re.I)]
    for prefix,key in [('q-c','cpp'),('q-n','network'),('q-agent-','agent'),('q-algorithms-','algorithms'),('q-xiaolin-','agent')]:
        if question_id.startswith(prefix) and (prefix not in ('q-c','q-n') or re.match(prefix+r'\d',question_id)):
            tags.append(key)
    if course_id=='knowledge-system:agent':tags.append('agent')
    return list(dict.fromkeys(tags)) or ['other']


def for_question(conn, qid, stem):
    present = conn.execute("SELECT 1 FROM sqlite_master WHERE name='question_categories'").fetchone()
    rows = [r[0] for r in conn.execute('SELECT category FROM question_categories WHERE question_id=? ORDER BY category', (qid,))] if present else []
    return rows or suggest(stem, qid)
