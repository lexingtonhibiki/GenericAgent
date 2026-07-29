# [SPECKIT] local feature — remove with spec_sop.md
import os

_SPEC_SOP = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'memory', 'spec_sop.md')


def _read_sop():
    if not os.path.isfile(_SPEC_SOP):
        return '(SOP 文件不存在: memory/spec_sop.md)'
    try:
        with open(_SPEC_SOP, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f'(SOP 读取失败: {e})'


def _dispatch(agent, phase, args):
    sop = _read_sop()
    parts = [
        f"请按照以下 SOP 执行 **{phase}** 阶段:\n",
        f"--- SOP ---\n{sop}\n--- SOP END ---\n",
    ]
    if args:
        parts.append(f"用户输入: {args}")
    return '\n'.join(parts)


def handle_frontend_command(agent, query):
    s = (query or '').strip()
    if s.startswith('/specify'):
        desc = s[len('/specify'):].strip()
        if not desc:
            return '用法: /specify <功能描述>\n例: /specify 构建一个照片相册管理应用'
        return _dispatch(agent, 'specify', desc)
    if s.startswith('/plan'):
        tech = s[len('/plan'):].strip()
        if not tech:
            return '用法: /plan <技术栈描述>\n例: /plan Python + FastAPI + SQLite'
        return _dispatch(agent, 'plan', tech)
    if s == '/tasks':
        return _dispatch(agent, 'tasks', '')
    if s.startswith('/constitution'):
        principles = s[len('/constitution'):].strip()
        if not principles:
            return '用法: /constitution <原则描述>\n例: /constitution 所有API必须有错误处理'
        return _dispatch(agent, 'constitution', principles)
    return None


def handle(agent, query, display_queue):
    s = (query or '').strip()
    for cmd in ('/specify', '/plan', '/tasks', '/constitution'):
        if s.startswith(cmd):
            result = handle_frontend_command(agent, s)
            if result:
                display_queue.put({'done': result, 'source': 'system'})
                return None
    return query


def install(cls):
    orig = cls._handle_slash_cmd
    if getattr(orig, '_spec_patched', False):
        return
    def patched(self, raw_query, display_queue):
        if any((raw_query or '').strip().startswith(c)
               for c in ('/specify', '/plan', '/tasks', '/constitution')):
            r = handle(self, raw_query, display_queue)
            if r is None:
                return None
        return orig(self, raw_query, display_queue)
    patched._spec_patched = True
    cls._handle_slash_cmd = patched
