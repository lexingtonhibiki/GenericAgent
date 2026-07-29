"""
GenericAgent — 安全合并上游脚本
用法: python scripts/merge_upstream.py [--dry-run] [--force]

功能:
  1. fetch upstream
  2. 预览上游新提交
  3. 保存本地补丁到 local_patches/
  4. 执行 merge（保留本地特性）
  5. 检测冲突，提示解决
  6. 验证关键本地特性标记 [HISTORY] [SPECKIT] 仍存在

依赖: git rerere（已启用，自动记忆冲突解决方案）
"""
import subprocess, sys, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCHES_DIR = os.path.join(ROOT, 'local_patches')

# 本地修改的文件（与上游共享，可能冲突）
CONFLICT_PRONE = [
    'frontends/tuiapp_v2.py',
    'frontends/continue_cmd.py',
    'frontends/stapp.py',
    'frontends/chatapp_common.py',
    '.gitignore',
]

# 纯本地文件（上游不存在，不会冲突）
LOCAL_ONLY = [
    'frontends/history_utils.py',
    'frontends/spec_cmd.py',
    'memory/spec_sop.md',
]

# 关键标记（验证本地特性未被覆盖）
MARKERS = {
    'frontends/stapp.py': ['[HISTORY]'],
    'frontends/chatapp_common.py': ['[SPECKIT]'],
    'frontends/tuiapp_v2.py': ['[HISTORY]'],
}


def _git(*args, check=True):
    r = subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and r.returncode != 0:
        print(f"  ERROR: git {' '.join(args)}")
        print(f"  {r.stderr.strip()}")
        sys.exit(1)
    return r


def save_patches():
    """保存当前本地补丁"""
    os.makedirs(PATCHES_DIR, exist_ok=True)
    for f in CONFLICT_PRONE:
        r = _git('diff', 'upstream/main', '--', f, check=False)
        patch_file = os.path.join(PATCHES_DIR, f.replace('/', '_').replace('\\', '_') + '.patch')
        with open(patch_file, 'w', encoding='utf-8') as pf:
            pf.write(r.stdout)
        lines = r.stdout.strip().split('\n')
        changed = sum(1 for l in lines if l.startswith('+') and not l.startswith('+++'))
        print(f"  {f}: {changed} lines changed")
    print(f"  Patches saved to {PATCHES_DIR}/")


def verify_markers():
    """验证本地特性标记仍存在"""
    ok = True
    for filepath, markers in MARKERS.items():
        full = os.path.join(ROOT, filepath)
        if not os.path.isfile(full):
            print(f"  MISSING: {filepath}")
            ok = False
            continue
        with open(full, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        for m in markers:
            if m not in content:
                print(f"  LOST MARKER: {m} not found in {filepath}")
                ok = False
            else:
                print(f"  OK: {m} in {filepath}")
    for f in LOCAL_ONLY:
        full = os.path.join(ROOT, f)
        if os.path.isfile(full):
            print(f"  OK: {f} exists (local-only)")
        else:
            print(f"  MISSING: {f}")
            ok = False
    return ok


def main():
    dry_run = '--dry-run' in sys.argv
    force = '--force' in sys.argv

    print("=== GenericAgent Safe Merge ===\n")

    # 1. Fetch
    print("[1/6] Fetching upstream...")
    _git('fetch', 'upstream')

    # 2. Preview
    print("\n[2/6] Preview upstream changes:")
    r = _git('log', '--oneline', 'HEAD..upstream/main', check=False)
    if not r.stdout.strip():
        print("  Already up to date. No new commits from upstream.")
        return
    commits = r.stdout.strip().split('\n')
    print(f"  {len(commits)} new commits:")
    for c in commits[:20]:
        print(f"    {c}")
    if len(commits) > 20:
        print(f"    ... and {len(commits)-20} more")

    # 3. Save patches
    print("\n[3/6] Saving local patches...")
    save_patches()

    # 4. Dry run
    if dry_run:
        print("\n[DRY-RUN] Would merge upstream/main. Stopping here.")
        r = _git('merge', '--no-commit', '--no-ff', 'upstream/main', check=False)
        if r.returncode != 0:
            print("  Conflicts detected (dry-run):")
            for line in r.stdout.split('\n') + r.stderr.split('\n'):
                if 'CONFLICT' in line:
                    print(f"    {line.strip()}")
        _git('merge', '--abort')
        print("  Dry-run merge aborted.")
        return

    # 5. Merge
    print("\n[4/6] Merging upstream/main...")
    r = _git('merge', 'upstream/main', check=False)
    if r.returncode != 0:
        # Check for conflicts
        r2 = _git('diff', '--name-only', '--diff-filter=U', check=False)
        conflicts = r2.stdout.strip().split('\n') if r2.stdout.strip() else []
        if conflicts:
            print(f"\n  CONFLICTS in {len(conflicts)} file(s):")
            for c in conflicts:
                print(f"    {c}")
            print("\n  Resolve conflicts manually, then:")
            print("    git add .")
            print("    git commit")
            print(f"\n  After resolving, run: python {sys.argv[0]} --verify")
            return
        else:
            print(f"  Merge failed: {r.stderr.strip()}")
            return

    print("  Merge successful (no conflicts)!")

    # 6. Verify
    print("\n[5/6] Verifying local features...")
    if not verify_markers():
        print("\n  WARNING: Some local features may have been lost!")
        print("  Check local_patches/ for reference patches.")
        if not force:
            print("  Use --force to skip this check, or manually restore from patches.")
            return
    else:
        print("  All local features intact.")

    print("\n[6/6] Done! Run `git log --oneline -5` to verify.")


if __name__ == '__main__':
    if '--verify' in sys.argv:
        print("Verifying local features...")
        ok = verify_markers()
        sys.exit(0 if ok else 1)
    main()
