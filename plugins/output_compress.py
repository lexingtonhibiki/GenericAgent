"""output_compress — rtk 式命令输出压缩插件（零核心代码改动）

背景：GA 的 `code_run` 只做 `smart_format` 头尾各半的**盲截断**（默认 maxlen=10000）。
pytest 的 500 行 passing 会挤掉那 1 行 FAILED；pip 的进度条会挤掉真正的报错。

本插件实现 rtk-ai/rtk（Apache-2.0）的 4 条策略，**自行重写、不抄其代码**：
  1. Smart Filtering  去掉噪音（进度条/下载日志/重复告警/空白）
  2. Grouping         同类行按目录前缀归并
  3. Truncation       超长单行保留头尾
  4. Deduplication    连续重复行折叠为 (×N)

安全底线（比 rtk 更保守）：
  - stdout 小于阈值（默认 2500 字符）**完全不动**
  - 任何含 error/fail/traceback/assert/warn 的行**永远保留**
  - 尾部 60 行**永远保留**（栈底/退出信息通常在尾部）
  - 只压缩 `code_run` 的 stdout 字段，其余工具一律不碰

关闭方式：环境变量 `GA_OUTPUT_COMPRESS=0`

机制：注册 agent_loop.py 的 `tool_after` hook。该 hook 的 ctx 是 `locals()`，
其中 `ret` 是 StepOutcome 对象本身，**原地 mutate ret.data 即可改变最终喂给 LLM 的
工具结果**（参考 plugins/project_mode.py 的"零核心改动"先例）。
"""
import os
import re

try:
    import plugins.hooks as hooks
except ImportError:
    hooks = None

# ---------------- 可调参数 ----------------
MIN_CHARS = 2500      # 小于此长度直接原样返回
BUDGET_CHARS = 6000   # 压缩后目标上限
TAIL_KEEP = 60        # 尾部强制保留行数
HEAD_KEEP = 40        # 超预算时头部保留行数
MAX_LINE = 300        # 单行超过此长度则头尾截断
GROUP_MIN_FILES = 8   # 同一目录至少这么多文件才归并
GROUP_MIN_TOTAL = 30  # 至少这么多"文件行"才触发归并

KEEP_RE = re.compile(
    r"(?i)(error|fail|failed|failure|exception|traceback|panic|fatal|critical"
    r"|assert|not ok|denied|refused|timeout|timed out|killed|❌|✗|×)"
)
# 纯噪音：进度条 / 下载日志 / pip 例行提示
NOISE_RE = [
    re.compile(r"\d+%\|"),                                   # tqdm 进度条
    re.compile(r"\[\s*[=#>\-. ]{6,}\s*\]"),                  # [====>    ]
    re.compile(r"\b\d+(\.\d+)?\s*(it|B|KB|MB|GB)/s\]"),      # ...it/s] ...MB/s]
    re.compile(r"^\s*(Collecting|Downloading|Installing collected packages|"
               r"Using cached|Requirement already satisfied|"
               r"Successfully installed|Building wheel for|Preparing metadata)\b", re.I),
    re.compile(r"^\s*(npm|yarn|pnpm)\s+(WARN|notice)\b", re.I),
    re.compile(r"^\s*\d+\s+packages? (are )?looking for funding", re.I),
    re.compile(r"^\s*$"),
]
# 测试通过行的归并（只有数量巨大时才折叠）
PASS_LINE_RE = re.compile(
    r"^\s*(\S+\.py)?\s*[\.sxX]+\s*\[\s*\d+%\]\s*$"      # pytest 点线
    r"|^\s*(PASSED|passed|ok\b|OK\b|\.\.\.ok)\s*$"       # 各种 PASSED
)
FILE_LINE_RE = re.compile(r"^(\s*)([^\s:]+/)([^\s/]+)\s*$")


def _dedup(lines):
    """策略 4：连续重复行折叠为 (×N)。"""
    out, i, n = [], 0, len(lines)
    while i < n:
        j = i
        while j + 1 < n and lines[j + 1] == lines[i]:
            j += 1
        cnt = j - i + 1
        if cnt >= 3:
            out.append(f"{lines[i]}   [x{cnt}]")
        else:
            out.extend(lines[i:j + 1])
        i = j + 1
    return out


def _filter_noise(lines):
    """策略 1：去噪音，但保留任何 KEEP_RE 命中的行。"""
    out, skipped = [], 0
    for ln in lines:
        if KEEP_RE.search(ln):
            out.append(ln)
            continue
        if any(r.search(ln) for r in NOISE_RE):
            skipped += 1
            continue
        out.append(ln)
    return out, skipped


def _collapse_pass(lines):
    """策略 2 变体：大量"通过"行折叠为计数，失败行原样保留。"""
    if not lines:
        return lines, 0
    idx = [i for i, l in enumerate(lines) if PASS_LINE_RE.search(l) and not KEEP_RE.search(l)]
    if len(idx) < 20:
        return lines, 0
    keep = [l for i, l in enumerate(lines) if i not in set(idx)]
    return keep, len(idx)


def _group_files(lines):
    """策略 2：同目录文件行归并（目录内 >= GROUP_MIN_FILES 且总数够多才做）。"""
    fileidx = [i for i, l in enumerate(lines) if FILE_LINE_RE.match(l)]
    if len(fileidx) < GROUP_MIN_TOTAL:
        return lines, 0
    groups = {}
    for i in fileidx:
        m = FILE_LINE_RE.match(lines[i])
        groups.setdefault(m.group(2), []).append(i)
    drop, merged = set(), 0
    for d, idxs in groups.items():
        if len(idxs) < GROUP_MIN_FILES:
            continue
        # 保留前 3 个真实文件名作样本，用第 4 行位置放折叠说明，其余丢弃
        lines[idxs[3]] = f"{d}  (共 {len(idxs)} 个文件，其余 {len(idxs) - 3} 个已折叠)"
        for i in idxs[4:]:
            drop.add(i)
        merged += len(idxs) - 3
    if not drop:
        return lines, 0
    return [l for i, l in enumerate(lines) if i not in drop], merged


def _trunc_long(lines):
    """策略 3：超长单行头尾保留。"""
    out, n = [], 0
    for ln in lines:
        if len(ln) > MAX_LINE:
            half = MAX_LINE // 2
            out.append(f"{ln[:half]}[...省略 {len(ln) - MAX_LINE} 字符...]{ln[-half:]}")
            n += 1
        else:
            out.append(ln)
    return out, n


def _overwrite_tail(line):
    """处理 \r 原地覆盖：只保留最后一次覆盖的内容。

    注意：入参必须是**已归一 CRLF** 的行（见 compress()）。否则 "文本\\r" 会返回空串。
    """
    segs = [s for s in line.split("\r") if s != ""]
    return segs[-1] if segs else ""


def compress(text, budget=BUDGET_CHARS):
    """返回 (压缩后文本, 统计字典)。任何异常都不能影响工具正常返回。"""
    stats = {"mode": "none"}
    if not isinstance(text, str) or len(text) < MIN_CHARS:
        return text, stats

    raw_chars, raw_lines = len(text), text.count("\n") + 1
    orig_text = text          # 兜底返回时用原文，避免 CRLF 归一改动原始输出
    # ⚠️ 必须先归一 CRLF。Windows 命令输出普遍是 \r\n，若直接对 "文本\r" 取
    # split("\r")[-1]，每行都会变成空串 —— 2026-09-17 真机实测：30000 字符输出
    # 被压成一行 `[x603]`，FAILED 行全部丢失。归一后剩下的裸 \r 才是真正的原地覆盖。
    text = text.replace("\r\n", "\n")
    lines = [_overwrite_tail(l).rstrip() for l in text.split("\n")]

    lines = _dedup(lines)
    lines, skipped = _filter_noise(lines)
    lines, passed = _collapse_pass(lines)
    lines, merged = _group_files(lines)
    lines, trunc = _trunc_long(lines)

    # 预算兜底：保留全部 KEEP 行 + 头 HEAD_KEEP + 尾 TAIL_KEEP
    if sum(len(l) + 1 for l in lines) > budget and len(lines) > HEAD_KEEP + TAIL_KEEP:
        keep_idx = {i for i, l in enumerate(lines) if KEEP_RE.search(l)}
        head = set(range(min(HEAD_KEEP, len(lines))))
        tail = set(range(max(0, len(lines) - TAIL_KEEP), len(lines)))
        keep = sorted(keep_idx | head | tail)
        omitted = len(lines) - len(keep)
        new = []
        prev = None
        for i in keep:
            if prev is not None and i != prev + 1:
                new.append(f"   [...省略 {i - prev - 1} 行...]")
            new.append(lines[i])
            prev = i
        lines = new
    else:
        omitted = 0

    out = "\n".join(lines)
    # 安全网：若压缩后只剩 1 行实义内容，且那行去掉去重计数后缀后是空的 —— 说明内容
    # 真的蒸发了（灾难性坍塌），宁可不压。2026-09-17 的 CRLF bug 就是这个形态
    # （`   [x603]`）；而「纯进度条输出」压成 `100%   [x300]` 属正常，放行。
    if raw_chars >= 1500:
        meaning = [l for l in lines if l.strip()]
        if len(meaning) <= 1 and (not meaning or not meaning[0].rsplit("   [x", 1)[0].strip()):
            return orig_text, {"mode": "none", "reason": "safety_collapse"}
    if len(out) >= raw_chars:
        return orig_text, {"mode": "none"}
    stats = {
        "mode": "rtk-style",
        "chars": f"{raw_chars}->{len(out)}",
        "lines": f"{raw_lines}->{len(lines)}",
        "noise_skipped": skipped, "pass_collapsed": passed,
        "files_merged": merged, "long_truncated": trunc, "lines_omitted": omitted,
    }
    header = (
        f"[rtk {raw_chars}→{len(out)}字符 省{100 - len(out) * 100 // max(raw_chars, 1)}%"
        f" 去噪{skipped}/折叠{passed}/归并{merged}/省略{omitted}"
        f" | error·fail与尾部{TAIL_KEEP}行已保留, 需原文请重定向到文件后file_read]\n"
        + "-" * 20 + "\n"
    )
    return header + out, stats


def _on_tool_after(ctx):
    if os.environ.get("GA_OUTPUT_COMPRESS", "1") == "0":
        return
    if not isinstance(ctx, dict):
        return
    if ctx.get("tool_name") != "code_run":
        return
    ret = ctx.get("ret")
    data = getattr(ret, "data", None)
    if not isinstance(data, dict):
        return
    so = data.get("stdout")
    if isinstance(so, str) and so:
        try:
            new, stats = compress(so)
        except Exception:
            return
        if stats.get("mode") != "none":
            data["stdout"] = new
            data["output_compress"] = stats


def _already_registered():
    """防止模块被 reload 或重复 load 时重复压缩。"""
    try:
        for fn in hooks._registry.get("tool_after", []):
            if getattr(fn, "__name__", "") == "_on_tool_after":
                return True
    except Exception:
        pass
    return False


if hooks is not None and not _already_registered():
    hooks.register("tool_after")(_on_tool_after)
