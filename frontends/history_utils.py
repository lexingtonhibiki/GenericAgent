"""
Dual-Source History Utils — shared by stapp.py & qtapp.py
=== LOCAL FEATURE — PROTECTED FROM UPSTREAM MERGE ===
Remove: delete this file + 2 lines in stapp.py (search [HISTORY])
"""
import os, re, json, time, glob, hashlib

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


def merge_history():
    native = load_native_history()
    imported = scan_imported_sessions()
    import_ids = {s['id'] for s in imported}
    native = [s for s in native if s.get('id', '').startswith('import_') and s['id'] not in import_ids] + \
             [s for s in native if s.get('id', '').startswith('native_')]
    all_s = native + imported
    all_s.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return all_s[:30]


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


def render_history_section(st, extract_ui_messages, agent=None):
    _auto_save(st)

    all_sessions = merge_history()
    if not all_sessions:
        return

    with st.expander("📜 历史会话", expanded=False):
        native_count = len([s for s in all_sessions if s.get('source') == 'native'])
        import_count = len([s for s in all_sessions if s.get('source') == 'import'])
        st.caption(
            f"共 {len(all_sessions)} 个  ·  💬 {native_count}  ·  📥 {import_count}"
        )

        for i, s in enumerate(all_sessions[:20]):
            is_import = s.get('source') == 'import'
            title = s.get('title', '未命名')[:35]
            ctime = s.get('created_at', '')[:16]
            n = s.get('turns', len(s.get('messages', [])))
            icon = "📥" if is_import else "💬"

            with st.container():
                row = st.columns([7, 1, 1])
                with row[0]:
                    if agent is not None:
                        if st.button(
                            f"{icon} {title}",
                            key=f"hist_ld_{i}",
                            help="继续对话（恢复后端+UI）",
                            use_container_width=True,
                        ):
                            _do_continue(st, s, agent, extract_ui_messages)
                    else:
                        if st.button(
                            f"{icon} {title}",
                            key=f"hist_ld_{i}",
                            help="点击查看",
                            use_container_width=True,
                        ):
                            _do_view(st, s, extract_ui_messages)
                with row[1]:
                    if st.button("👁", key=f"hist_v_{i}", help="仅查看"):
                        _do_view(st, s, extract_ui_messages)
                with row[2]:
                    if st.button("🗑", key=f"hist_d_{i}", help="删除"):
                        if is_import:
                            try:
                                os.remove(s['path'])
                            except OSError:
                                pass
                        else:
                            h = load_native_history()
                            h = [x for x in h if x.get('id') != s.get('id')]
                            save_native_history(h)
                        st.rerun()

                meta_cols = st.columns([1])
                with meta_cols[0]:
                    st.caption(f"{n}轮 · {ctime}")
