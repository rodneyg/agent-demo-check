#!/usr/bin/env python3
"""Read-only, heuristic demo-readiness scan. Python standard library only."""
import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path
import re

SKIP = {'node_modules', '.git', 'dist', 'build', '.venv', 'venv', '__pycache__'}
JS_EXT = {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.mts', '.cts'}
EXT = {'.py'} | JS_EXT
RETRY = re.compile(r'tenacity|backoff|retry|maxRetries|max_retries|exponential', re.I)
RATE = re.compile(r'429|RateLimitError|rate_limit|insufficient_quota', re.I)
KEY = re.compile(r'\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b|Bearer\s+(?!\$|\{|[\x27\"])[A-Za-z0-9_.-]{12,}')
CALL = re.compile(r'(?:\b(?:OpenAI|AsyncOpenAI|Anthropic|AsyncAnthropic)\s*\(|\b(?:openai|anthropic)\.(?:OpenAI|AsyncOpenAI|Anthropic|AsyncAnthropic)\s*\(|\bnew\s+(?:OpenAI|Anthropic)\s*\(|\b(?:\w+\.)*(?:chat\.completions|responses|messages|completions)\.create\s*\(|\brequests\.(?:get|post)\s*\(|\bhttpx\.(?:get|post|Client|AsyncClient)\s*\(|\bfetch\s*\()')
CLIENT_KEY = re.compile(r'dangerouslyAllowBrowser\s*:\s*true|\b(?:NEXT_PUBLIC|EXPO_PUBLIC|VITE|REACT_APP)_[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN)\b')
AI_TEXT_CALLS = {'generateText', 'streamText'}
JS_TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|([\w$]+|"(?:\\[\s\S]|[^"\\])*"|\x27(?:\\[\s\S]|[^\x27\\])*\x27|`(?:\\[\s\S]|[^`\\])*`|[^\s])')
JS_DELIMITERS = {'(': ')', '[': ']', '{': '}'}
AI_MODULE = {'"ai"', "'ai'"}


def is_ai_require(tokens):
    return (len(tokens) == 4 and tokens[:2] == ['require', '(']
            and tokens[2] in AI_MODULE and tokens[3] == ')')


def ai_sdk_bindings(tokens):
    """Find named and namespace bindings from the AI SDK's root package."""
    names, namespaces = set(), set()
    for i, token in enumerate(tokens):
        if token not in {'import', 'const', 'let', 'var'}:
            continue
        start = i + 1
        if token == 'import' and tokens[start:start + 1] == ['type']:
            continue
        if token == 'import' and tokens[start + 1:start + 2] == [',']:
            start += 2  # Skip an optional default import.
        if tokens[start:start + 2] == ['*', 'as']:
            if tokens[start + 3:start + 5] in (['from', '"ai"'], ['from', "'ai'"]):
                namespaces.add(tokens[start + 2])
        if tokens[start:start + 1] != ['{']:
            if tokens[start + 1:start + 2] == ['='] and is_ai_require(tokens[start + 2:start + 6]):
                namespaces.add(tokens[start])
            continue
        try:
            end = tokens.index('}', start + 1)
        except ValueError:
            continue
        if token == 'import':
            from_ai = (end + 2 < len(tokens) and tokens[end + 1] == 'from'
                       and tokens[end + 2] in AI_MODULE)
        else:
            from_ai = tokens[end + 1:end + 2] == ['='] and is_ai_require(tokens[end + 2:end + 6])
        if not from_ai:
            continue
        specifier = []
        for part in tokens[start + 1:end] + [',']:
            if part == ',':
                if specifier and specifier[0] in AI_TEXT_CALLS:
                    names.add(specifier[-1])
                specifier.clear()
            else:
                specifier.append(part)
    return names, namespaces


def has_ai_sdk_timeout(tokens, start):
    """Look for a timeout or signal at the top level of an inline options object."""
    if tokens[start:start + 1] != ['{']:
        return False
    stack = ['}']
    for i in range(start + 1, len(tokens)):
        token = tokens[i]
        if len(stack) == 1 and tokens[i - 1] in {'{', ','}:
            if token.strip('"\x27') in {'timeout', 'abortSignal'}:
                following = tokens[i + 1:i + 3]
                if following[:1] in ([','], ['}']):
                    return True  # Shorthand option.
                if len(following) == 2 and following[0] == ':' and following[1] not in {'undefined', 'null'}:
                    return True
        if token in JS_DELIMITERS:
            stack.append(JS_DELIMITERS[token])
        elif token == stack[-1]:
            stack.pop()
            if not stack:
                break
    return False


def ai_sdk_calls(text):
    matches = [match for match in JS_TOKEN.finditer(text) if match.group(1)]
    tokens = [match.group(1) for match in matches]
    names, namespaces = ai_sdk_bindings(tokens)
    for i, token in enumerate(tokens):
        if i and tokens[i - 1] in {'.', 'function'}:
            continue
        if token in names and tokens[i + 1:i + 2] == ['(']:
            args = i + 2
        elif (token in namespaces and tokens[i + 3:i + 4] == ['(']
              and tokens[i + 1] == '.' and tokens[i + 2] in AI_TEXT_CALLS):
            args = i + 4
        else:
            continue
        line = text.count('\n', 0, matches[i].start()) + 1
        yield line, has_ai_sdk_timeout(tokens, args)


def call_end(text, start):
    """Balance calls across lines, ignoring delimiters inside strings/comments."""
    depth, quote, escape = 0, None, False
    i = text.find('(', start)
    for j in range(i, len(text)):
        c = text[j]
        if quote:
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == quote:
                quote = None
        elif c in '\x27\"`':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


def scan(repo):
    repo = Path(repo).resolve()
    findings, repo_findings, paths, dirs = [], [], [], []
    for root, children, names in os.walk(repo, followlinks=False):
        children[:] = sorted(d for d in children if d not in SKIP and not Path(root, d).is_symlink())
        dirs.extend(Path(root, d).relative_to(repo).as_posix() for d in children)
        paths.extend(Path(root, n) for n in sorted(names) if not Path(root, n).is_symlink())
    sources = {p: p.read_text(errors='replace') for p in paths if p.suffix in EXT}
    def add(id_, severity, p, line, evidence, why, fix, level=False):
        item = dict(id=id_, severity=severity, file=p.relative_to(repo).as_posix() if p else '.', line=line,
                    evidence=KEY.sub('[REDACTED]', evidence.strip())[:240], why=why, fix=fix)
        (repo_findings if level else findings).append(item)
    all_text = '\n'.join(sources.values())
    for p, text in sources.items():
        lines = text.splitlines()
        # Use Python syntax to distinguish guarded parsing from an unrelated try.
        guarded = set()
        if p.suffix == '.py':
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Try) and node.handlers:
                        for stmt in node.body:
                            guarded.update(range(stmt.lineno, stmt.end_lineno + 1))
            except SyntaxError:
                pass
        calls = []
        for m in CALL.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            if lines[line - 1].lstrip().startswith(('#', '//', '*')):
                continue
            chunk = text[m.start():call_end(text, m.start())]
            fetch = m.group().startswith('fetch')
            if fetch and not re.search(r'api\.(?:openai|anthropic)\.com', chunk):
                continue
            llm = not m.group().startswith(('requests.', 'httpx.'))
            calls.append((line, llm))
            # Explicit SDK defaults apply to calls in this file; confirm ownership manually.
            timeout = re.search(r'\btimeout\s*[:=]', chunk)
            if llm and not fetch:
                timeout = timeout or re.search(r'\btimeout\s*[:=]', text)
            if fetch:
                timeout = re.search(r'\bsignal\s*[:,}]', chunk)
            if not timeout and llm:
                # Promise.race against a timer, or AbortSignal.timeout, within the next ~40 lines.
                after = '\n'.join(lines[line-1:line+40])
                timeout = re.search(r'Promise\.race|AbortSignal\.timeout|asyncio\.wait_for', after)
            if not timeout:
                add('no-timeout', 'high', p, line, lines[line-1], 'A stalled provider can freeze the demo.', 'Set an explicit timeout; for fetch pass an AbortController or AbortSignal timeout signal.')
        for line, llm in calls:
            if not llm:
                continue
            if not RETRY.search(text):
                add('no-retry', 'medium', p, line, lines[line-1], 'Transient provider failures stop the request.', 'Add bounded retries with exponential backoff and jitter; do not retry permanent quota failures.')
            if not re.search(r'\blogger\b|\blogging\b|console\.error', text):
                add('no-logging', 'medium', p, line, lines[line-1], 'Failures will be hard to explain during a demo.', 'Log request ids and errors without prompts, tokens, or private data.')
        sdk_calls = list(ai_sdk_calls(text)) if p.suffix in JS_EXT else []
        for line, has_timeout in sdk_calls:
            if not has_timeout:
                add('no-timeout', 'high', p, line, lines[line-1],
                    'No call-level AI SDK timeout or abort signal is visible. A stalled provider can delay the demo.',
                    'Set a timeout or pass an abortSignal. Check shared options and caller deadlines before reporting.')
        model_context = bool(sdk_calls or re.search(r'openai|anthropic|\bllm\b|output_text|chat\.completions', text, re.I))
        for i, line in enumerate(lines, 1):
            if CLIENT_KEY.search(line) and not line.lstrip().startswith(('#', '//', '*')):
                add('client-side-key', 'high', p, i, line, 'A provider key used from browser or app code ships to every user, who can copy it and run up your bill.', 'Move model calls behind a server route you control, keep the key server-side only, rotate the exposed key, and add per-user rate limits.')
            if KEY.search(line):
                add('hardcoded-key', 'high', p, i, '[potential credential redacted]', 'A source credential can leak or be abused.', 'Revoke any real exposed key and load its replacement from the environment.')
            parse = re.search(r'\b(?:json\.loads|JSON\.parse)\s*\((.*)', line)
            # Only model-related parsing: ordinary config/DB/test JSON is outside scope.
            test_file = any(x in {'test', 'tests', 'evals'} for x in p.relative_to(repo).parts) or '.test.' in p.name or p.name.startswith('test_')
            likely_output = parse and re.search(r'response|output|completion|content|\btext\b', parse.group(1), re.I)
            if parse and model_context and likely_output and not test_file:
                safe = i in guarded if p.suffix == '.py' else bool(re.search(r'\btry\s*\{', '\n'.join(lines[max(0,i-9):i])) and re.search(r'\bcatch\s*(?:\(|\{)', '\n'.join(lines[i-1:i+9])))
                if not safe:
                    add('unguarded-json', 'medium', p, i, line, 'Malformed model output can crash the demo.', 'Catch parse failures, validate the schema, and return a clear fallback or bounded repair attempt.')
    if not RATE.search(all_text):
        add('no-rate-limit-handling', 'high', None, 1, 'No rate-limit/quota marker found.', 'A throttled or exhausted account can stop every demo request.', 'Handle rate limits with bounded backoff and quota exhaustion with a clear actionable message.', True)
    if not any(Path(d).name in {'tests', 'evals'} for d in dirs) and not any('eval' in p.name.lower() for p in paths):
        add('no-evals', 'medium', None, 1, 'No tests/, evals/, or *eval* file found.', 'Model quality has no visible regression check.', 'Add representative inputs, expected properties, and at least one failure case.', True)
    if not any(p.name == '.env.example' for p in paths):
        add('missing-env-example', 'low', None, 1, '.env.example absent.', 'A fresh checkout may be hard to configure.', 'Add a .env.example with placeholder values.', True)
    readmes = [p for p in paths if p.name.lower().startswith('readme')]
    if not any(re.search(r'^#{1,6}[ \t]+.*(?:setup|installation|getting started|quickstart|run(?:ning)? locally)', p.read_text(errors='replace'), re.I | re.M) for p in readmes):
        add('missing-readme-setup', 'low', None, 1, 'No README setup heading found.', 'A reviewer may not be able to run the project.', 'Document prerequisites, environment variables, installation, and the run command under Setup.', True)
    # Git index is inspected directly (no subprocess, no repository changes).
    # Without index evidence, an existing .env is only a candidate, not proven committed.
    index = repo / '.git' / 'index'
    index_bytes = index.read_bytes() if index.is_file() else b''
    for p in paths:
        if p.name == '.env' or (p.name.startswith('.env.') and p.name != '.env.example'):
            rel = p.relative_to(repo).as_posix()
            tracked = b'\0' + rel.encode() + b'\0' in index_bytes or rel.encode() + b'\0' in index_bytes
            ignored = False
            for base in [repo] + [repo / Path(*p.relative_to(repo).parts[:i]) for i in range(1, len(p.relative_to(repo).parts))]:
                ignore = base / '.gitignore'
                if ignore.is_file():
                    local = p.relative_to(base).as_posix()
                    for rule in ignore.read_text(errors='replace').splitlines():
                        rule = rule.strip()
                        if not rule or rule.startswith('#'):
                            continue
                        negative = rule.startswith('!')
                        rule = rule.lstrip('!').lstrip('/')
                        if fnmatch.fnmatch(local, rule) or ('/' not in rule and fnmatch.fnmatch(p.name, rule)):
                            ignored = not negative
            if tracked and not ignored:
                add('committed-env', 'high', p, 1, '[environment contents redacted]', 'A tracked environment file may expose secrets.', 'Remove secrets from the index, rotate exposed keys, and add an appropriate .gitignore rule.')
    return dict(repo=str(repo), files_scanned=len(sources), findings=findings, repo_findings=repo_findings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path)
    parser.add_argument('--md', action='store_true')
    args = parser.parse_args()
    if not args.repo.is_dir():
        parser.error('repo must be an existing directory')
    result = scan(args.repo)
    if args.md:
        print('| Severity | Finding | Location | Evidence | Why | Fix |')
        print('| --- | --- | --- | --- | --- | --- |')
        for f in result['findings'] + result['repo_findings']:
            cells = [f['severity'], f['id'], f"{f['file']}:{f['line']}", f['evidence'], f['why'], f['fix']]
            print('| ' + ' | '.join(str(c).replace('|', '\\|').replace('\n', ' ') for c in cells) + ' |')
    else:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
