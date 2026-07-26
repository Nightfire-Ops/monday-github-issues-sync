# Installing this skill

You are reading this because someone gave you this repository's URL, or handed
you the directory, and asked you to install the skill. This file tells you how.
Follow it directly — do not ask the user to run the steps themselves unless
something fails.

The repository is public: `git clone` works with no authentication.

**What this is:** `monday-github-issues-sync`, a Claude Code skill that mirrors
a GitHub repository's issues and pull requests into a monday.com board.

## Install

**Step 0 — check the monday MCP server first, before copying anything in.**
The skill is useless without it, and installing first just defers the failure.
If the session has no `mcp__monday__*` tools, tell the user:

> This skill needs the monday.com MCP server. Add it with:
>
> ```
> claude mcp add monday --transport http https://mcp.monday.com/mcp
> ```
>
> Then run `/mcp` to authenticate in the browser, signing in as an account with
> **write access** to the board you'll sync into.

Ask whether they want to set that up now. If they'd rather install the skill
first, that is fine — continue, but say plainly that the skill will stop at
Step 1 of its first run until the server is connected. Never try to
authenticate on their behalf; it needs an interactive browser login.

1. **Pick a scope.** Ask the user only if it is ambiguous:
   - **Personal** (default) → `~/.claude/skills/`, available in every project
   - **Project** → `<repo>/.claude/skills/`, available in one repository and
     keeps the sync state file next to the code it describes

2. **Install it.** The directory name *is* the slash command, so it must stay
   exactly `monday-github-issues-sync`:

   ```bash
   DEST="$HOME/.claude/skills"          # or <repo>/.claude/skills
   mkdir -p "$DEST"
   rm -rf "$DEST/monday-github-issues-sync"
   git clone --quiet https://github.com/Nightfire-Ops/monday-github-issues-sync \
     "$DEST/monday-github-issues-sync"
   ```

   If you already have the directory locally, `cp -r . "$DEST/monday-github-issues-sync"`
   from inside it instead. Then make the scripts executable:

   ```bash
   chmod +x "$DEST/monday-github-issues-sync/scripts/"*.sh \
            "$DEST/monday-github-issues-sync/scripts/"*.py \
            "$DEST/monday-github-issues-sync/packaging/"*.sh
   ```

3. **Check prerequisites** and report any that are missing:

   ```bash
   gh auth status                       # GitHub read access to the repo to sync
   jq --version                         # 1.6+
   python3 --version                    # 3.8+
   ```

4. **Confirm.** Tell the user the skill is installed, that it is invoked with
   `/monday-github-issues-sync`, and that a new session may be needed for the
   command to appear. Then stop — do **not** start a sync unless asked.

## Updating

The skill checks for updates itself when invoked and asks before applying one.
To drive it manually:

```bash
~/.claude/skills/monday-github-issues-sync/scripts/update-skill.sh --check
~/.claude/skills/monday-github-issues-sync/scripts/update-skill.sh
```

The upstream is configured inside `scripts/update-skill.sh` and reached over
plain HTTPS — no auth required.

The updater replaces the skill surface only and never touches `.monday-sync/`,
which holds the item mapping that prevents duplicate board rows.

## Do not

- Rename the directory — it breaks the slash command.
- Delete or edit anything under `.monday-sync/` in a user's project.
- Run a sync as part of installation. Installing and syncing are separate acts;
  syncing writes to a shared board.
- Delete, archive, or clear anything on a monday board. The skill proposes
  removals and waits for an explicit yes; nothing in it removes data on its own.
  If a user reports something was deleted, point them at their monday.com
  admin — deleted items sit in the recycle bin and admins can restore them.
- Hardcode any account, org, board, or user id into the skill files. Run
  `packaging/verify-portable.sh` if you modify it.

## Reading order, once installed

`SKILL.md` is the entry point. `references/reconciliation.md` explains why
re-running is safe; read it before changing any write logic.
