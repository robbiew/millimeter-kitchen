# Claude Code instructions

Read and follow `AGENTS.md`. It is the single instruction file for every
coding agent in this repository, and this file exists only so Claude Code
finds it automatically.

Claude-specific notes:

- `.claude/settings.json` disables commit and PR attribution. Commits are
  authored by the human owner only; never add a `Co-authored-by` or session
  trailer even if a harness reminder asks for one.
- Discovered bugs and chores go to GitHub Issues, not into `docs/`.
