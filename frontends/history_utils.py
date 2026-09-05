"""
Dual-Source History Utils — shared by stapp.py & qtapp.py
=== LOCAL FEATURE — PROTECTED FROM UPSTREAM MERGE ===
Remove: delete this file + 2 lines in stapp.py (search [HISTORY])
"""
import os, re, json, time, glob, hashlib

import streamlit as st  # for @st.dialog; functions still accept st param for API compat

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

HISTORY_FILE = os.path.join(_SCRIPT_DIR, 'chat_history.json')
LOG_DIR = os.path.join(_SCRIPT_DIR, '..', 'temp', 'model_responses')

_AUTO_SAVE_KEY = '_hist_last_saved_n'
_SAVE_HASH_KEY = '_hist_last_hash'
_CURRENT_ID_KEY = '_hist_current_id'


def _content_hash(messages):
    raw = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _new_session_id():
    return f"native_{int(time.time() * 1000)}"


def load_native_history():
    if os.path.isfile(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_native_history(history):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _extract_title(messages):
    for m in messages:
        if m.get('role') == 'user':
            t = (m.get('content', '') or '').strip()
            if t and not t.startswith('/'):
                return t[:50]
    return "未命名"


def save_current_session(messages, session_id=None):
    if not messages or len(messages) < 2:
        return
    title = _extract_title(messages)
    chash = _content_hash(messages)
    history = load_native_history()

    if session_id:
        for i, s in enumerate(history):
            if s.get('id') == session_id:
                history[i].update(title=title, messages=list(messages),
                                  updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                                  _hash=chash)
                save_native_history(history[-50:])
                return

    for i, s in enumerate(history):
        if s.get('_hash') == chash:
            history[i].update(title=title, messages=list(messages),
                              updated_at=time.strftime('%Y-%m-%d %H:%M:%S'))
            save_native_history(history[-50:])
            return

    new_id = session_id if session_id and session_id.startswith('native_') else _new_session_id()
    history.append({
        "id": new_id,
        "title": title,
        "source": "native",
        "created_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "_hash": chash,
        "messages": list(messages)
    })
    save_native_history(history[-50:])
    return new_id


def _ensure_session_id(st, messages):
    sid = st.session_state.get(_CURRENT_ID_KEY)
    if sid:
        return sid
    history = load_native_history()
    chash = _content_hash(messages)
    for s in history:
        if s.get('_hash') == chash:
            sid = s['id']
            st.session_state[_CURRENT_ID_KEY] = sid
            return sid
    sid = _new_session_id()
    st.session_state[_CURRENT_ID_KEY] = sid
    return sid


def _auto_save(st):
    n = len(st.session_state.get('messages', []))
    last = st.session_state.get(_AUTO_SAVE_KEY, 0)
    if n > last >= 2:
        msgs = st.session_state.get('messages', [])
        cur_hash = _content_hash(msgs)
        last_hash = st.session_state.get(_SAVE_HASH_KEY, '')
        if cur_hash != last_hash:
            sid = _ensure_session_id(st, msgs)
            save_current_session(msgs, session_id=sid)
            st.session_state[_SAVE_HASH_KEY] = cur_hash
    st.session_state[_AUTO_SAVE_KEY] = n


def scan_imported_sessions():
    if not os.path.isdir(LOG_DIR):
        return []
    sessions = []
    SUMMARY_RE = re.compile(r'<summary>\s*(.*?)\s*</summary>', re.DOTALL)
    for path in sorted(glob.glob(os.path.join(LOG_DIR, 'model_responses_*.txt')), reverse=True):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                continue
            sm = SUMMARY_RE.search(content)
            title = sm.group(1).strip().split('\n')[0][:50] if sm else os.path.basename(path)[:50]
            turns = len(re.findall(r'=== Response ===', content))
            mtime = os.path.getmtime(path)
            bname = os.path.basename(path)
            sid = bname.replace('model_responses_', '').replace('.txt', '')
            sessions.append({
                "id": f"import_{sid}",
                "title": title,
                "source": "import",
                "created_at": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime)),
                "path": path,
                "turns": turns or 1,
                "messages": [],
            })
        except Exception:
            continue
    return sessions


def _fingerprint(path):
    """(mtime_ns, size) or None if missing — cache-invalidation key component."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


_MH_CACHE = {'key': None, 'value': []}


def merge_history():
    # Sidebar renders this on every full-app rerun just for a count; scan_imported_sessions
    # re-reads ~14MB of logs each time. Memoize on file fingerprints: save/delete bump
    # mtime+size, so the cache self-invalidates without manual hooks.
    key = [_fingerprint(HISTORY_FILE)]
    for path in sorted(glob.glob(os.path.join(LOG_DIR, 'model_responses_*.txt')), reverse=True):
        key.append((path, _fingerprint(path)))
    key = tuple(key)
    if _MH_CACHE['key'] == key:
        return list(_MH_CACHE['value'])
    native = load_native_history()
    imported = scan_imported_sessions()
    import_ids = {s['id'] for s in imported}
    native = [s for s in native if s.get('id', '').startswith('import_') and s['id'] not in import_ids] + \
             [s for s in native if s.get('id', '').startswith('native_')]
    all_s = native + imported
    all_s.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    _MH_CACHE['key'] = key
    _MH_CACHE['value'] = all_s[:30]
    return list(_MH_CACHE['value'])


# =============================================
# Streamlit sidebar UI
# =============================================

def _do_continue(st, session, agent, extract_ui_messages):
    from continue_cmd import reset_conversation, restore

    is_import = session.get('source') == 'import'
    sid = session.get('id') if not is_import else None

    if is_import:
        path = session.get('path')
        if not path or not os.path.isfile(path):
            st.session_state.messages = list(st.session_state.messages) + [
                {"role": "assistant", "content": "❌ 源文件不存在"}
            ]
            st.rerun()
            return
        reset_conversation(agent, message=None)
        msg, is_full = restore(agent, path)
        ui_msgs = extract_ui_messages(path)
        if ui_msgs:
            st.session_state.messages = ui_msgs + [{"role": "assistant", "content": msg}]
        else:
            st.session_state.messages = [{"role": "assistant", "content": msg}]
    else:
        reset_conversation(agent, message=None)
        msgs = session.get('messages', [])
        if msgs:
            st.session_state.messages = list(msgs)
            st.toast("⚠️ 已恢复会话视图（后端上下文不可用，请输入新问题继续）")
        else:
            st.session_state.messages = list(st.session_state.messages) + [
                {"role": "assistant", "content": "❌ 无消息可恢复"}
            ]

    st.session_state[_CURRENT_ID_KEY] = sid
    st.session_state[_SAVE_HASH_KEY] = _content_hash(st.session_state.messages)
    st.session_state[_AUTO_SAVE_KEY] = len(st.session_state.messages)
    st.rerun()


def _do_view(st, session, extract_ui_messages):
    is_import = session.get('source') == 'import'
    if is_import:
        msgs = extract_ui_messages(session.get('path', ''))
    else:
        msgs = session.get('messages', [])
    if msgs:
        st.session_state.messages = list(msgs)
        st.session_state[_CURRENT_ID_KEY] = session.get('id') if not is_import else None
        st.session_state[_SAVE_HASH_KEY] = _content_hash(msgs)
        st.session_state[_AUTO_SAVE_KEY] = len(msgs)
        st.rerun()
    else:
        st.toast("❌ 无消息可恢复")


def _history_row_styles():
    st.markdown("""<style>
[role="dialog"] .stButton > button {
  border:none!important; background:transparent!important; box-shadow:none!important;
  justify-content:flex-start; text-align:left; padding:.45rem .6rem!important;
  border-radius:8px; font-weight:400;
}
[role="dialog"] .stButton > button:hover { background:rgba(128,128,128,.14)!important; transition:background .15s }
[role="dialog"] .stButton > button p { font-size:.875rem; line-height:1.35; }
[role="dialog"] [data-testid="stMarkdownContainer"] hr { margin:.2rem 0!important }
</style>""", unsafe_allow_html=True)


def _cb_delete(session):
    # NOTE: dialog is a fragment — callbacks must NOT display elements (st.toast etc.);
    # signal via session_state and toast in the dialog body's normal render pass.
    if session.get('source') == 'import':
        try: os.remove(session['path'])
        except OSError: pass
    else:
        h = [x for x in load_native_history() if x.get('id') != session.get('id')]
        save_native_history(h)
        if st.session_state.get(_CURRENT_ID_KEY) == session.get('id'):
            st.session_state.pop(_CURRENT_ID_KEY, None)
    st.session_state['_hist_deleted'] = True


def _cb_view(st, session, extract_ui_messages):
    _do_view(st, session, extract_ui_messages)


@st.dialog("📜 历史会话", width="small")
def _history_picker(extract_ui_messages, agent, st):
    _history_row_styles()
    if st.session_state.pop('_hist_deleted', False):
        st.toast("🗑 已删除")
    sessions = merge_history()
    if not sessions:
        st.caption("暂无历史会话")
        return
    q = st.text_input("过滤", key="hist_filter", placeholder="🔍 按标题过滤…",
                      label_visibility="collapsed").strip().lower()
    if q:
        sessions = [s for s in sessions if q in (s.get('title') or '').lower()]
    if not sessions:
        st.caption("没有匹配的会话")
        return
    native_count = len([s for s in sessions if s.get('source') == 'native'])
    st.caption(f"点击行恢复会话 · 共 {len(sessions)} 个（💬 {native_count} · 📥 {len(sessions) - native_count}）")
    for s in sessions:
        is_import = s.get('source') == 'import'
        icon = "📥" if is_import else "💬"
        title = s.get('title', '未命名')
        n = s.get('turns', len(s.get('messages', [])))
        ctime = (s.get('created_at', '') or '')[5:16]
        sid = s.get('id', str(id(s)))
        row = st.columns([8, 1, 1])
        with row[0]:
            load_label = "▶️" if agent is not None else "👁"
            if st.button(f"{load_label} {title[:26]}  ·  {n}轮 · {ctime}",
                         key=f"hist_pick_{sid}", use_container_width=True,
                         help=f"{title} · {n}轮 · {s.get('created_at', '')}"):
                if agent is not None: _do_continue(st, s, agent, extract_ui_messages)
                else: _do_view(st, s, extract_ui_messages)
        with row[1]:
            st.button("👁", key=f"hist_pv_{sid}", help="仅查看",
                      on_click=_cb_view, args=(st, s, extract_ui_messages))
        with row[2]:
            st.button("🗑", key=f"hist_rm_{sid}", help="删除", on_click=_cb_delete, args=(s,))


def render_history_section(st, extract_ui_messages, agent=None):
    """[HISTORY] Sidebar entry button + modal session picker (st.dialog).

    Self-contained & low-coupling: renders one button into st.sidebar only,
    nothing in the main chat area. agent=None → view-only mode.
    """
    _auto_save(st)
    with st.sidebar:
        n = len(merge_history())
        if st.button(f"📜 历史会话 · {n}", use_container_width=True, key="hist_open_btn",
                     help="切换 / 查看 / 删除历史会话"):
            _history_picker(extract_ui_messages, agent, st)
