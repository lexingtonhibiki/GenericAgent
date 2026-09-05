"""
GenericAgent — 安全合并上游脚本
用法: python scripts/merge_upstream.py [--dry-run] [--force] [--push]

功能:
  1. fetch upstream
  2. 预览上游新提交
  3. 保存本地补丁到 local_patches/
  4. 执行 merge（保留本地特性）
  5. 检测冲突，提示解决
  6. 验证关键本地特性标记 [HISTORY] [SPECKIT] 仍存在
  7. --push: 验证通过后普通推送 origin/main（fast-forward；被拒即停，绝不 force）

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
    'frontends/tests/test_data_backup.py',
    'frontends/tests/test_release_qualification.py',
    'memory/goal_hive_sop.md',
    '.gitignore',
]

# 纯本地文件（上游不存在，不会冲突）
LOCAL_ONLY = [
    'frontends/history_utils.py',
    'frontends/spec_cmd.py',
    'memory/spec_sop.md',
    'ga_bridge.cmd',
    'ga_tui.cmd',
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


def push_main():
    """普通 fast-forward 推送；被拒即停（远端可能有异动，需人工核对，绝不 force）。"""
    print("\n[PUSH] git push origin main ...")
    r = _git('push', 'origin', 'main', check=False)
    out = (r.stdout.strip() or r.stderr.strip())
    if out:
        print('  ' + out.replace('\n', '\n  '))
    if r.returncode != 0:
        print("  PUSH REJECTED — 先 git fetch 人工核对远端，勿直接 force。")
        return False
    return True


def main():
    dry_run = '--dry-run' in sys.argv
    force = '--force' in sys.argv
    push = '--push' in sys.argv

    print("=== GenericAgent Safe Merge ===\n")

    # 1. Fetch
    print("[1/6] Fetching upstream...")
    _git('fetch', 'upstream')

    # 2. Preview
    print("\n[2/6] Preview upstream changes:")
    r = _git('log', '--oneline', 'HEAD..upstream/main', check=False)
    if not r.stdout.strip():
        print("  Already up to date. No new commits from upstream.")
        if push:
            push_main()  # 显式 --push 时即使无新提交也执行（解决冲突后重跑的场景）
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
            print(f"  Then push:            python {sys.argv[0]} --push")
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

    if push and not push_main():
        sys.exit(1)

    print("\n[6/6] Done! Run `git log --oneline -5` to verify.")


if __name__ == '__main__':
    if '--verify' in sys.argv:
        print("Verifying local features...")
        ok = verify_markers()
        sys.exit(0 if ok else 1)
    main()
