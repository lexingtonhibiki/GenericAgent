"""peak_valley_gate — 「启用峰谷模式」：让 LLM 在**收到任务之前**先等到空闲时段。

用户心智模型：「我开了个定时器，到了谷我再点发送。」
→ 所以拦截点必须在 **agent_before**（agent_loop.py:49，每个用户轮、**首个 LLM 调用之前**），
  而不是执行末尾。等待期间不发任何请求，**0 token 消耗**。

用法（触发词只有两个，且必须出现在**行首**）：
    启用峰谷模式 <你的任务>
    /peakvalley <你的任务>

行为：
  0. 命中后**先把命令文本从消息里摘掉**再交给 LLM —— 省 token，也免得模型
     对着命令本身瞎想（整行只有命令时连空行一起删）。
  1. 判定当前时段；已在空闲 → 打印一行说明，立刻开工。
  2. 高峰中 → 打印"预计等到 X 点"，然后**阻塞 sleep**，每 60s 校时一次，
     到空闲时段立即放行，LLM 才开始接收任务。
  3. 等待过程写日志 `temp/peak_valley_gate.log`，Ctrl-C 可随时取消。

环境变量：
  GA_PEAK_PROVIDER=deepseek|glm   强制指定用哪家的规则（默认从模型名自动识别）
  GA_PEAK_VALLEY_MAX_WAIT=43200   最长等待秒数，默认 12 小时；超过则**不等待**并告警
                                  （设 GA_PEAK_VALLEY_FORCE=1 可无视上限强行等）
  GA_PEAK_VALLEY_DRYRUN=1         只计算不真睡（试算用）
  GA_PEAK_VALLEY_FAKE_WAIT=秒     测试用：强制假装还需等这么多秒
  GA_PEAK_VALLEY_DISABLE=1        总开关，关掉本插件
"""
import os
import re
import sys
import time

try:
    import plugins.hooks as hooks
except ImportError:
    try:
        import hooks
    except ImportError:
        hooks = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_MEM = os.path.join(_ROOT, "memory")
if _MEM not in sys.path:
    sys.path.insert(0, _MEM)

try:
    from peak_valley import (PROVIDERS, next_offpeak_start, report,
                             wait_seconds, zone)
except Exception as _e:          # 模块缺失时插件静默失效，绝不拖垮 agent
    PROVIDERS = {}
    wait_seconds = next_offpeak_start = report = zone = None
    _IMPORT_ERR = _e
else:
    _IMPORT_ERR = None

# 触发词：**只有这两个**，且必须出现在行首（忽略前导空白/引用/列表等装饰符）。
# 收紧原因：早期版本还认 "[峰谷模式]" 之类的泛词，结果任何**谈论**峰谷的消息都会触发
# 闸门、把消息卡住。判定权只交给用户显式写下的命令。
TRIGGERS = ("启用峰谷模式", "/peakvalley")
PLACEHOLDER = "峰谷模式已启用。"      # 命令被摘除后正文为空时的兜底
_LINE_HEAD = re.compile(r"^[\s>*#\-—•·\d.、)）\]]*")   # 行首允许的装饰符号

LOG = os.path.join(_ROOT, "temp", "peak_valley_gate.log")
_SLEEP_CHUNK = 60          # 每 60s 醒一次校时
_HEARTBEAT = 600           # 每 10 分钟打一次心跳


def _log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass
    print(msg, flush=True)


def _texts(ctx):
    """取出本轮用户输入的所有文本片段。"""
    out = []
    ui = ctx.get("user_input")
    if isinstance(ui, str):
        out.append(ui)
    for m in (ctx.get("messages") or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out.extend(b.get("text", "") for b in c if isinstance(b, dict))
    return out


def _triggered(texts):
    """命中条件：某一行**以触发词开头**（忽略前导空白/装饰符）。

    用行首锚定而非"包含"，是为了防止正文里顺口提到"启用峰谷模式"就把消息卡住。
    返回命中的触发词，没有则 None。
    """
    for t in texts:
        for line in t.split("\n"):
            s = _LINE_HEAD.sub("", line)
            for k in TRIGGERS:
                if s.startswith(k):
                    return k
    return None


def _drop_trigger(text, trigger):
    """摘下触发词：整行只有命令 → 删掉整行；命令后还有任务 → 只摘掉命令那截。"""
    keep = []
    for line in text.split("\n"):
        i = line.find(trigger)
        if i < 0:
            keep.append(line)
            continue
        if _LINE_HEAD.sub("", line[:i]).strip():   # 命令前面还有真实内容 → 不是行首，别动
            keep.append(line)
            continue
        rest = line[i + len(trigger):]
        if rest.strip():                            # 命令后面接着任务 → 保留任务部分
            keep.append(rest.lstrip())
        # 否则整行丢弃
    out = "\n".join(keep)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _strip_trigger_text(ctx, trigger):
    """把触发词从**真正发给 LLM 的消息**里摘掉，返回改动处数。

    `ctx['messages']` 就是 agent_loop 里那个 list 本身（可变对象），原地改即生效。
    """
    n = 0
    for m in (ctx.get("messages") or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if not isinstance(c, str) or trigger not in c:
            continue
        new = _drop_trigger(c, trigger)
        if new != c:
            m["content"] = new or PLACEHOLDER
            n += 1
    return n


def _model_name(ctx):
    c = ctx.get("client")
    for obj in (c, getattr(c, "backend", None)):
        for attr in ("model", "name"):
            v = getattr(obj, attr, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _pick_provider(model):
    """优先 env 指定，其次按模型名识别。返回 (provider, 是否确定)。"""
    forced = (os.environ.get("GA_PEAK_PROVIDER") or "").strip().lower()
    if forced in PROVIDERS:
        return forced, True
    ml = (model or "").lower()
    if "deepseek" in ml:
        return "deepseek", True
    if any(k in ml for k in ("glm", "zhipu", "chatglm", "智谱")):
        return "glm", True
    # 识别不出：退化为"离空闲最近的那家"，并明确告知这是估算
    if PROVIDERS:
        cands = [(wait_seconds(k), k) for k in PROVIDERS]
        cands = [x for x in cands if x[0] is not None]
        if cands:
            return min(cands)[1], False
    return None, False


def _sleep_until(wait, why):
    """分块 sleep，定期校时。返回实际等待秒数。"""
    t0 = time.time()
    last_beat = t0
    while True:
        left = wait - (time.time() - t0)
        if left <= 0:
            break
        n = min(_SLEEP_CHUNK, max(1, int(left)))
        time.sleep(n)
        now = time.time()
        if now - last_beat >= _HEARTBEAT:
            last_beat = now
            done = int(now - t0)
            _log(f"[峰谷] 等待中… 已等 {done // 60} 分钟，还剩约 {max(0, int(left - n)) // 60} 分钟 ({why})")
    return int(time.time() - t0)


@hooks.register("agent_before") if hooks else (lambda f: f)
def peak_valley_gate(ctx):
    """agent_before 钩子：需要时先等到空闲时段，再让 LLM 接活。"""
    if os.environ.get("GA_PEAK_VALLEY_DISABLE") == "1":
        return
    if not PROVIDERS or wait_seconds is None:
        return
    try:
        texts = _texts(ctx)
        hit = _triggered(texts)
        if not hit:
            return
        # 命中后立刻把命令文本从消息里摘掉：省 token，也免得模型对着命令本身瞎想
        cleared = _strip_trigger_text(ctx, hit)
        _log(f"[峰谷] 命中『{hit}』（已从消息中剔除 {cleared} 处）")
        model = _model_name(ctx)
        prov, sure = _pick_provider(model)
        if not prov:
            _log("[峰谷] 触发但无法判定 provider，按普通模式直接开工")
            return

        fake = os.environ.get("GA_PEAK_VALLEY_FAKE_WAIT")
        wait = int(fake) if fake else wait_seconds(prov)
        cur = zone(prov)
        _log(f"[峰谷] provider={prov}{'' if sure else '(按最近空闲估算)'}"
             f"，当前={cur}，模型={model or '未知'}")

        if not wait:
            _log(f"[峰谷] {PROVIDERS[prov]['display']} 当前已在空闲时段，直接开工（不等待）")
            return

        start = next_offpeak_start(prov)
        cap = int(os.environ.get("GA_PEAK_VALLEY_MAX_WAIT") or 12 * 3600)
        force = os.environ.get("GA_PEAK_VALLEY_FORCE") == "1"
        if fake:      # 测试注入：真实时段可能并非高峰，措辞要诚实
            _log(f"[峰谷] (FAKE_WAIT 测试注入 {wait}s；真实时段={cur}) 先睡 {wait} 秒再让 LLM 接收任务")
        else:
            _log(f"[峰谷] 高峰中：预计等到 {start.strftime('%m-%d %H:%M')} "
                 f"（约 {wait // 60} 分钟）后才让 LLM 接收任务")
        if wait > cap and not force:
            _log(f"[峰谷] ⚠️ 等待时长 {wait // 60} 分钟超过上限 {cap // 60} 分钟，"
                 f"**不等待**直接开工；要强行等请设 GA_PEAK_VALLEY_FORCE=1，"
                 f"或调大 GA_PEAK_VALLEY_MAX_WAIT")
            return
        if os.environ.get("GA_PEAK_VALLEY_DRYRUN") == "1":
            _log("[峰谷] DRYRUN：只试算，不真睡")
            return
        if wait > 3600:
            _log(f"[峰谷] 这是长等待（>{wait // 3600} 小时），Ctrl-C 可取消；"
                 f"也可改天再发。等待期间不消耗任何 token。")

        slept = _sleep_until(wait, f"等 {prov} 空闲")
        _log(f"[峰谷] 等待结束（实际 {slept // 60} 分钟），现在进入 "
             f"{zone(prov)} 时段，开始把任务交给 LLM")
    except KeyboardInterrupt:
        _log("[峰谷] 用户取消等待，直接开工")
    except Exception as e:
        # 钩子绝不能把 agent 搞崩
        try:
            _log(f"[峰谷] 异常已忽略: {type(e).__name__}: {e}")
        except Exception:
            pass
