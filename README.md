# Agent demo check

A Claude skill that checks Python and JS/TS AI projects for common demo failures:
missing timeouts, retries, quota handling, safe JSON parsing, logging, setup,
evals, possible hardcoded keys, and provider keys shipped to the browser. It reads files only and needs Python 3.9+.
Claude confirms findings and reviews the demo documentation before reporting.

## Install

For Claude Code, clone the public repository directly into your skills folder:

```sh
mkdir -p ~/.claude/skills
git clone https://github.com/rodneyg/agent-demo-check.git ~/.claude/skills/agent-demo-check
```

For Claude.ai, make a ZIP from a local clone by running this command inside the clone:

```sh
git archive --format=zip --prefix=agent-demo-check/ --output=../agent-demo-check.zip HEAD
```

Upload the ZIP under **Customize → Skills → + Create skill → Upload a skill**.
The scanner needs access to the repository in Claude's execution environment.

Ask: “Use agent-demo-check to review this repo before my interview demo.”
Or run from this folder:

```sh
python3 scripts/scan.py /path/to/repo
python3 scripts/scan.py /path/to/repo --md
python3 -m unittest discover -s tests -v
```

Example table excerpt (the default output is JSON):

| Severity | Finding | Location |
| --- | --- | --- |
| high | no-timeout | agent.py:4 |
| medium | unguarded-json | agent.py:5 |

For Vercel AI SDK calls, the scanner recognizes named and namespace bindings
from `ai` through ES module imports and CommonJS `require`. It checks for
`timeout` and `abortSignal` on each
call's inline options object. Review shared options, object spreads, wrappers,
and caller deadlines before confirming a candidate. Check whether a supplied
signal imposes a deadline or only enables cancellation. The scanner uses static
heuristics and runs without project dependencies or API keys.
Suspected keys are redacted. `.env` tracking detection supports ordinary Git indexes;
worktrees, split indexes, and full gitignore semantics need manual verification.
