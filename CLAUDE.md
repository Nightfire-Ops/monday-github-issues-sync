# Installing this skill

You are reading this because someone handed you this skill directory (or an
archive of it) and asked you to install it. This file tells you how. Follow it
directly — do not ask the user to run the steps themselves unless something
fails.

**What this is:** `monday-github-issues-sync`, a Claude Code skill that mirrors
a GitHub repository's issues and pull requests into a monday.com board.

## Install

1. **Pick a scope.** Ask the user only if it is ambiguous:
   - **Personal** (default) → `~/.claude/skills/`, available in every project
   - **Project** → `<repo>/.claude/skills/`, available in one repository and
     keeps the sync state file next to the code it describes

2. **Copy this directory in.** The directory name *is* the slash command, so it
   must stay exactly `monday-github-issues-sync`:

   ```bash
   DEST="$HOME/.claude/skills"          # or <repo>/.claude/skills
   mkdir -p "$DEST"
   rm -rf "$DEST/monday-github-issues-sync"
   cp -r . "$DEST/monday-github-issues-sync"
   chmod +x "$DEST/monday-github-issues-sync/scripts/"*.sh \
            "$DEST/monday-github-issues-sync/scripts/"*.py \
            "$DEST/monday-github-issues-sync/packaging/"*.sh
   ```

   Run it from inside this directory. If you were given a zip, unzip first.

3. **Check prerequisites** and report any that are missing:

   ```bash
   gh auth status                       # GitHub read access to the repo to sync
   jq --version                         # 1.6+
   python3 --version                    # 3.8+
   ```

4. **Verify the monday MCP server** is connected. If `/mcp` does not list one,
   tell the user to run:

   ```bash
   claude mcp add monday --transport http https://mcp.monday.com/mcp
   ```

   followed by `/mcp` to authenticate in the browser. The authenticated account
   needs write access to the target board. Do not attempt to authenticate on
   their behalf.

5. **Confirm.** Tell the user the skill is installed, that it is invoked with
   `/monday-github-issues-sync`, and that a new session may be needed for the
   command to appear. Then stop — do **not** start a sync unless asked.

## Updating

The skill checks for updates itself when invoked and asks before applying one.
To drive it manually:

```bash
~/.claude/skills/monday-github-issues-sync/scripts/update-skill.sh --check
~/.claude/skills/monday-github-issues-sync/scripts/update-skill.sh
```

The upstream is configured inside `scripts/update-skill.sh` and reached with the
user's own `gh` credentials. Do not copy that value anywhere else, and do not
put it in documentation.

The updater replaces the skill surface only and never touches `.monday-sync/`,
which holds the item mapping that prevents duplicate board rows.

## Do not

- Rename the directory — it breaks the slash command.
- Delete or edit anything under `.monday-sync/` in a user's project.
- Run a sync as part of installation. Installing and syncing are separate acts;
  syncing writes to a shared board.
- Hardcode any account, org, board, or user id into the skill files. Run
  `packaging/verify-portable.sh` if you modify it.

## Reading order, once installed

`SKILL.md` is the entry point. `references/reconciliation.md` explains why
re-running is safe; read it before changing any write logic.
