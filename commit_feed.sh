#!/usr/bin/env bash
# 健壮的 data 提交：切 main -> 清理残留 -> fetch -> 合并 -> commit -> rebase push
set -u
MSG="${1:-data: feed update}"
# 切到 main 分支（checkout 默认 detached HEAD）
if git show-ref --verify --quiet refs/heads/main; then
  git checkout main >/dev/null 2>&1
else
  git checkout -b main >/dev/null 2>&1
fi
# 清理任何残留的 rebase/merge 状态
git rebase --abort >/dev/null 2>&1 || true
git merge --abort >/dev/null 2>&1 || true
rm -rf .git/rebase-merge .git/rebase-apply .git/MERGE_HEAD
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git fetch origin main >/dev/null 2>&1 || true
# 合并 origin 与工作区 data（按 url 等主键去重，工作区优先）
python3 merge_feed.py || true
git add data
if git diff --staged --quiet; then
  echo "no new content"; exit 0
fi
git commit -m "$MSG" >/dev/null
for i in 1 2 3 4 5; do
  git rebase --abort >/dev/null 2>&1 || true
  rm -rf .git/rebase-merge .git/rebase-apply
  if git pull --rebase -X theirs origin main >/dev/null 2>&1 && git push >/dev/null 2>&1; then
    echo "PUSHED"; exit 0
  fi
  echo "push retry $i"; sleep 8
done
echo "PUSH FAILED"; exit 1
