#!/usr/bin/env bash
# DevForge PostToolUse hook (advisory only — always exits 0).
# After a `git commit`, it (a) warns if a model change looks like it's missing a
# migration, and (b) reminds to push. It never blocks or fails the tool.
set +e
input="$(cat)"
cmd="$(printf '%s' "$input" | python3 -c 'import sys,json;
try:
    print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception:
    print("")' 2>/dev/null)"

case "$cmd" in
  *"git commit"*)
    root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
    py="$root/../env/bin/python"   # shared interpreter lives one level above the repo
    if [ -d "$root/backend" ] && [ -x "$py" ]; then
      if ! ( cd "$root/backend" && "$py" manage.py makemigrations --check --dry-run >/dev/null 2>&1 ); then
        echo "⚠ DevForge: a model change may be missing a migration (makemigrations --check failed). Run makemigrations before pushing."
      fi
    fi
    echo "ℹ DevForge: commit made — remember 'git push origin main' and verify it's in sync."
    ;;
esac
exit 0
