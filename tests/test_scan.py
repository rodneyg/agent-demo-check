import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from textwrap import dedent
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scan', ROOT / 'scripts/scan.py')
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)

class ScanTests(unittest.TestCase):
    def ids(self, name):
        result = scanner.scan(ROOT / 'tests/fixtures' / name)
        return {f['id'] for f in result['findings'] + result['repo_findings']}

    def test_bad_python(self):
        self.assertTrue({'no-timeout', 'no-retry', 'hardcoded-key', 'unguarded-json',
                         'no-logging', 'no-rate-limit-handling', 'no-evals',
                         'missing-env-example', 'missing-readme-setup'} <= self.ids('bad_py'))

    def test_bad_typescript(self):
        self.assertTrue({'no-timeout', 'no-retry', 'unguarded-json', 'no-logging', 'client-side-key'} <= self.ids('bad_ts'))

    def test_good_python(self):
        result = scanner.scan(ROOT / 'tests/fixtures/good_py')
        self.assertEqual([], [f for f in result['findings'] + result['repo_findings'] if f['severity'] == 'high'])
        self.assertNotIn('unguarded-json', self.ids('good_py'))

    def test_json_cli_and_redaction(self):
        run = subprocess.run([sys.executable, str(ROOT/'scripts/scan.py'), str(ROOT/'tests/fixtures/bad_py')], capture_output=True, text=True)
        self.assertEqual(0, run.returncode)
        self.assertNotIn('sk-test-', run.stdout)
        self.assertGreater(json.loads(run.stdout)['files_scanned'], 0)

    def test_timeout_signal_and_skipped_dirs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = Path(tmp)
            (p/'node_modules').mkdir()
            (p/'node_modules/leak.py').write_text('KEY = "sk-test-FAKEFAKEFAKEFAKEFAKE1234"')
            (p/'app.ts').write_text('fetch("https://api.openai.com/v1/responses", {signal: AbortSignal.timeout(1000)});')
            result = scanner.scan(p)
            self.assertEqual(1, result['files_scanned'])
            self.assertNotIn('no-timeout', {f['id'] for f in result['findings']})
            self.assertNotIn('hardcoded-key', {f['id'] for f in result['findings']})

    def test_requests_timeout_per_call(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = Path(tmp)
            (p/'app.py').write_text('import requests\nrequests.get("https://example.com", timeout=2)\nrequests.post("https://example.com")\n')
            findings = scanner.scan(p)['findings']
            self.assertEqual([3], [f['line'] for f in findings if f['id'] == 'no-timeout'])

    def test_ai_sdk_timeout_per_call(self):
        source = dedent("""\
            import { generateText, streamText as stream } from "ai";
            import * as sdk from 'ai';
            const unrelated = { timeout: 500 };
            generateText({
                providerOptions: { gateway: { timeout: 500 } },
                prompt: "timeout: 123)",
                /* abortSignal: request.signal */
            });
            stream({ timeout: { totalMs: 5000 } });
            generateText({ 'abortSignal': AbortSignal.timeout(5000) });
            stream({ abortSignal });
            sdk.streamText({ abortSignal: request.signal });
            sdk.generateText({ abortSignal: undefined, timeout: null });
            sdk.streamText({ prompt: "hi" });
            generateText(sharedOptions);
        """)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'model.mts').write_text(source)
            findings = scanner.scan(tmp)['findings']
        self.assertEqual([4, 13, 14, 15], [f['line'] for f in findings if f['id'] == 'no-timeout'])
        self.assertNotIn('no-retry', {f['id'] for f in findings})

    def test_ai_sdk_calls_ignore_non_sdk_names_comments_and_strings(self):
        source = dedent("""\
            import { generateText } from "./local";
            import { streamText } from 'ai';
            generateText({});
            local.streamText({});
            // streamText({});
            /* streamText({}); */
            const example = 'streamText({})';
            const multiline = `import { generateText } from "ai";`;
            streamText({});
        """)
        self.assertEqual([(9, False)], list(scanner.ai_sdk_calls(source)))

    def test_ai_sdk_commonjs_calls(self):
        source = dedent("""\
            const { generateText: generate } = require('ai');
            const ai = require("ai");
            const local = require("./ai");
            generate({});
            ai.streamText({ timeout: 3000 });
            local.streamText({});
        """)
        self.assertEqual([(4, False), (5, True)], list(scanner.ai_sdk_calls(source)))

    def test_running_locally_counts_as_readme_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'README.md').write_text('# Project\n\n## Running locally\n\nRun the app.\n')
            findings = scanner.scan(tmp)['repo_findings']
        self.assertNotIn('missing-readme-setup', {f['id'] for f in findings})

    def test_non_model_json_and_optional_catch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = Path(tmp)
            (p/'config.py').write_text('import json\nvalue = json.loads(config)\n')
            (p/'app.ts').write_text('const endpoint = "https://api.openai.com";\ntry { const data = JSON.parse(response.text); } catch { console.error("invalid"); }\n')
            self.assertNotIn('unguarded-json', {f['id'] for f in scanner.scan(p)['findings']})

    def test_markdown_cli(self):
        run = subprocess.run([sys.executable, str(ROOT/'scripts/scan.py'), str(ROOT/'tests/fixtures/bad_ts'), '--md'], capture_output=True, text=True)
        self.assertEqual(0, run.returncode)
        self.assertIn('| high | no-timeout | agent.ts:2 |', run.stdout)

    def test_tracked_env_ignore(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = Path(tmp)
            (p/'.git').mkdir()
            (p/'.git/index').write_bytes(b'DIRC\0.env\0')
            (p/'.env').write_text('SECRET=fake')
            self.assertIn('committed-env', {f['id'] for f in scanner.scan(p)['findings']})
            (p/'.gitignore').write_text('.env\n')
            self.assertNotIn('committed-env', {f['id'] for f in scanner.scan(p)['findings']})

if __name__ == '__main__':
    unittest.main()
