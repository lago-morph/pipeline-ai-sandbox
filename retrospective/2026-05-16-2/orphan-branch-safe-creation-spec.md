# Spec: `orphan-branch-safe-creation`

## Intent

`git checkout --orphan <branch>` creates a new branch with no history but preserves the working tree contents. The conventional follow-up is `git rm -rf . && git commit -m "<init>"` to start the orphan with a clean root commit. But: if the original branch had **untracked** work (files newly written but not yet staged), and the recipe is `git checkout --orphan && git rm -rf . && git clean -fdx`, the `git clean -fdx` step **deletes the untracked files from the filesystem**. When the agent switches back to the original branch, `git checkout` restores tracked files, but the unstaged untracked files are gone. `git status` then shows a clean working tree, perfectly hiding the loss.

This bit the `pipeline-ai-sandbox` run in Phase 2: the dispatcher had just copied `.agent/` and three workflow files from a vendored bundle into the working tree, hadn't committed yet, and then created the `_agent_runs` orphan branch using the procedure in the skill's own SKILL.md. `git clean -fdx` removed the just-copied files. The mishap was caught only because `ls .agent/` came back empty after the round-trip.

## Trigger

**Direct triggers:**
- "Create an orphan branch for logs / artifacts / runs."
- "Add a `gh-pages` branch."
- "Set up `_agent_runs`."
- "Why did my files disappear after `git checkout --orphan`?"

**Proactive triggers:**
- An agent is following a documented procedure that includes `git checkout --orphan` followed by `git clean -fdx`.
- An agent has unstaged or untracked work and is about to switch branches.

**Negative triggers:**
- Initial repo setup with no other commits or content; orphan-on-empty is always safe.

## Inputs

- Current branch name and HEAD SHA.
- Whether the working tree has uncommitted work (staged or untracked).
- Target orphan branch name (e.g., `_agent_runs`, `gh-pages`, `dist`).
- Optional: initial content for the orphan's first commit (typically a single `README.md` sentinel).

## Outputs

- A new orphan branch with a single root commit.
- The orphan branch pushed to origin.
- The original branch and its working-tree state restored exactly as before — no lost files, no lost edits.

## Workflow

**Pick exactly one of the three strategies below. Don't mix.** All three are safe; choose by ergonomics.

### Strategy A — detached worktree (recommended)

```bash
# From repo root, with possibly-dirty working tree:
git worktree add --detach /tmp/orphan-work
cd /tmp/orphan-work
git checkout --orphan <branch>
git rm -rf . 2>/dev/null || true   # idempotent
echo "# <branch>" > README.md
echo "" >> README.md
echo "This orphan branch stores <purpose>. Created by <procedure>." >> README.md
git add README.md
git -c user.email="agent@example.com" -c user.name="agent" commit -m "init <branch> orphan branch"
git push -u origin <branch>
cd - >/dev/null
git worktree remove /tmp/orphan-work
```

The original working tree is **untouched** because the orphan branch's work happens in a separate worktree on disk. No risk of `git clean` running against the wrong directory.

### Strategy B — stash + restore (when a separate worktree isn't possible)

```bash
ORIG_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git stash push --include-untracked --message "pre-orphan-stash-$(date +%s)"
git checkout --orphan <branch>
git rm -rf . 2>/dev/null || true
git clean -fdx
echo "# <branch>" > README.md
git add README.md
git -c user.email="agent@example.com" -c user.name="agent" commit -m "init <branch> orphan branch"
git push -u origin <branch>
git checkout "$ORIG_BRANCH"
git stash pop                       # restores untracked + staged files
```

Risk: if stash-pop hits a conflict the user must resolve manually. Acceptable for interactive use; less acceptable for unattended.

### Strategy C — orphan via low-level commit object (no checkout)

```bash
# Build the orphan's first commit object without touching the working tree:
tree_sha=$(git hash-object -w --stdin < <(echo "# <branch>") | xargs -I{} git update-index --add --cacheinfo 100644,{},README.md)
# (Simpler: create the file in a temp dir, build the tree there.)
TMP=$(mktemp -d)
echo "# <branch>" > "$TMP/README.md"
GIT_INDEX_FILE="$TMP/index" git --git-dir="$(git rev-parse --git-dir)" add "$TMP/README.md"
tree=$(GIT_INDEX_FILE="$TMP/index" git --git-dir="$(git rev-parse --git-dir)" write-tree)
commit=$(echo "init <branch> orphan branch" | git commit-tree "$tree")
git update-ref refs/heads/<branch> "$commit"
git push origin <branch>
rm -rf "$TMP"
```

Most surgical; no checkout happens at any point. Hardest to read. Use only when scripted.

### What never to do

```bash
# DON'T:
git checkout --orphan <branch>
git rm -rf .
git clean -fdx     # ← this deletes untracked work from the ORIGINAL branch
# (the working tree is the same files until you checkout back)
```

This is the procedure in many skill / handler scripts. It is unsafe **whenever the original branch had untracked work**. If the agent must use this exact sequence, the agent must first verify with `git status` that there is no untracked work — and abort if there is.

## Concrete examples

### Example 1 — `_agent_runs` orphan in `pipeline-ai-sandbox`

Context: working branch had freshly-copied `.agent/` and 3 workflow YAMLs as untracked files.

**Wrong path (what happened):**
```bash
git checkout --orphan _agent_runs   # ok
git rm -rf .                        # ok, removes tracked
git clean -fdx                      # WIPED .agent/ and workflows
# commit, push, checkout back to working branch
# git status: clean (lie)
# ls .agent: empty (truth)
```

**Right path (Strategy A):**
```bash
git worktree add --detach /tmp/orphan-Vs1aL
cd /tmp/orphan-Vs1aL
git checkout --orphan _agent_runs
git rm -rf . 2>/dev/null || true
cat > README.md <<EOF
# _agent_runs orphan branch
Stores artifacts produced by batch-job runners (logs, summary.json per run, etc).
EOF
git add README.md
git -c user.email=agent@pipeline-ai-sandbox -c user.name=pipeline-ai-sandbox-agent commit -m "init _agent_runs orphan branch"
git push -u origin _agent_runs
cd - >/dev/null
git worktree remove /tmp/orphan-Vs1aL
# Working tree on the original branch is untouched.
```

### Example 2 — `gh-pages` after a docs build

Context: just ran a docs build that produced an untracked `dist/` directory. Want to push that to a fresh `gh-pages` orphan.

Strategy A applied:
```bash
git worktree add --detach /tmp/gh-pages-work
cd /tmp/gh-pages-work
git checkout --orphan gh-pages
git rm -rf .
# Copy the freshly-built dist tree from the original worktree
cp -r "$OLDPWD/dist/." .
git add .
git commit -m "publish gh-pages"
git push -u origin gh-pages --force-with-lease
cd - >/dev/null
git worktree remove /tmp/gh-pages-work
```

The original worktree's `dist/` directory is untouched.

## Anti-patterns

- **`git clean -fdx` immediately after `git checkout --orphan` on a tree with untracked work.** This is the bug at the heart of this skill.
- **Trusting `git status: clean` after a `--orphan` round-trip.** The check restores tracked files; it doesn't tell you what was wiped from untracked.
- **Documenting the unsafe procedure in a skill's SKILL.md without flagging the precondition.** (Source of this session's mishap.)
- **Stashing without `--include-untracked`.** Stash by default omits untracked files; for this scenario, untracked is what you must save.
- **Force-pushing the orphan to overwrite an existing one without a sentinel commit check.** `_agent_runs` and `gh-pages` accumulate history; force-push obliterates audit trail.

## Acceptance criteria

1. After the procedure, `git diff <original-branch>@{1} <original-branch>` is empty (no inadvertent edits).
2. After the procedure, `git status` on the original branch shows the same untracked + staged + working-tree state it had before.
3. The orphan branch exists on origin with at least one commit.
4. The orphan branch's first commit has a sentinel `README.md` documenting its purpose.
5. The procedure is idempotent: running it again when the orphan already exists is a no-op (or surfaces "branch already exists" clearly).

## Files this skill creates / modifies

- A new branch ref `refs/heads/<orphan-branch>` (local + remote).
- A single root commit on that branch, typically containing only `README.md`.
- **No** modification to the original branch, its working tree, its staging area, or any other ref.
