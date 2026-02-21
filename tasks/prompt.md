### US-007: Railway Deployment
**Description:** As the operator, I need to deploy the bot to Railway so it runs 24/7 without a personal machine.

**Acceptance Criteria:**
- [ ] `Dockerfile` present in repo root that:
  - Uses `python:3.11-slim` base
  - Installs system dependencies for Chromium (required by Playwright)
  - Installs Python dependencies from `requirements.txt`
  - Runs `playwright install chromium` during build
  - Sets `CMD ["python", "main.py"]`
- [ ] `requirements.txt` includes: `playwright`, `playwright-stealth`, `python-dotenv`, `Pillow` (for screenshot handling), `pytz`
- [ ] `.env.example` file documents all environment variables with example values
- [ ] `README.md` includes step-by-step setup: local run instructions, Railway deploy instructions, how to set env vars in Railway dashboard
- [ ] Bot logs to stdout only (Railway captures stdout for its logging dashboard)
- [ ] No local file writes required for production operation (screenshots sent via email attachment, not saved to disk permanently)

## Workflow

1. Study the PRD context: tasks/prd-stubhub-edc-shuttle-monitor.md to understand the bigger picture
2. Study `progress.md` to understand overall status, implementation progress and learnings including codebase patterns and gotchas
3. Implement this single story following acceptance criteria
4. Run quality checks: typecheck, lint, etc.
5. Do NOT create git commits. Changes will be committed automatically by the engine after task completion.
6. Document learnings (see below)
7. Signal completion

## Before Completing

APPEND to `progress.md`:

```
## [Date] - US-079
- What was implemented
- Files changed
- **Learnings:**
  - Patterns discovered
  - Gotchas encountered
---
```

If you discovered a **reusable pattern**, also add it to the `## Codebase Patterns` section at the TOP of progress.md.

## Stop Condition

**IMPORTANT**: If the work is already complete (implemented in a previous iteration or already exists), verify it meets the acceptance criteria and signal completion immediately.

When finished (or if already complete), signal completion with:

```
<promise>COMPLETE</promise>
```
