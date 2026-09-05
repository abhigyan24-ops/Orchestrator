import os
import re
import sys
import glob
import subprocess
from typing import Tuple, List, Dict, Optional

# Patterns for identifying test files
TEST_FILE_PATTERNS = [
    r"tests?[/\\].+\.(js|ts|py|mjs|cjs)$",
    r"__tests__[/\\].+\.(js|ts|py|mjs|cjs)$",
    r".+[._-](test|spec)\.(js|ts|py|mjs|cjs)$",
    r".+[/\\].+[._-](test|spec)\.(js|ts|py|mjs|cjs)$",
    r".+[/\\]test_.+\.py$",
]

# Patterns for detecting non-trivial assertions
ASSERTION_PATTERNS = [
    r"\bassert\b\s*\(",
    r"\bassert\.[a-zA-Z]+\s*\(",
    r"\bassert\s+[^\n;]+",
    r"\bexpect\s*\(.+?\)\s*\.[a-zA-Z]+",
    r"\bself\.assert[a-zA-Z]+\s*\(",
    r"\bassertEqual\s*\(",
    r"\bassertTrue\s*\(",
    r"\bassertFalse\s*\(",
]

# Trivial / fake assertions that don't verify real logic
TRIVIAL_ASSERTION_PATTERNS = [
    r"assert\s+(True|1|1\s*==\s*1)\s*$",
    r"assert\s*\(\s*(true|True|1|1\s*==\s*1)\s*\)",
    r"assert\s*\.\s*(ok|strictEqual|equal)\s*\(\s*(true|1)\s*,\s*(true|1)?\s*\)",
    r"expect\s*\(\s*(true|1|'a')\s*\)\s*\.\s*(toBe|toEqual)\s*\(\s*(true|1|'a')\s*\)",
]


def is_test_file(filepath: str) -> bool:
    """Check if a filepath matches common test naming conventions."""
    norm = filepath.replace("\\", "/")
    return any(re.search(pat, norm, re.IGNORECASE) for pat in TEST_FILE_PATTERNS)


def inspect_test_content(content: str) -> Tuple[bool, str]:
    """
    Inspect test code to ensure it is not empty, missing, or trivially fake.
    Returns (is_valid, reason).
    """
    stripped = content.strip()
    if not stripped or len(stripped) < 20:
        return False, "Test file is empty or too short (< 20 characters)."

    # Remove comments before checking assertions
    cleaned = re.sub(r"//.*", "", stripped)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"#.*", "", cleaned)
    cleaned = cleaned.strip()

    # Find assertions
    has_assertions = any(re.search(pat, cleaned) for pat in ASSERTION_PATTERNS)
    if not has_assertions:
        return False, "Test file contains no recognizable assertion statements (e.g. assert, expect, assertEqual)."

    # Check for trivially fake assertions
    trivial_matches = sum(len(re.findall(pat, cleaned, re.IGNORECASE)) for pat in TRIVIAL_ASSERTION_PATTERNS)
    # Count total assertion-like occurrences
    total_assertions = sum(len(re.findall(pat, cleaned)) for pat in ASSERTION_PATTERNS)

    if trivial_matches >= total_assertions and total_assertions > 0:
        return False, "Test file only contains trivially fake assertions (e.g. assert True, expect(true).toBe(true))."

    return True, "Valid test assertions found."


def find_test_files_in_dir(directory: str) -> List[str]:
    """Find all test files present on disk in the directory."""
    test_files = []
    for root, dirs, files in os.walk(directory):
        # Skip .git and node_modules
        if ".git" in root or "node_modules" in root or ".venv" in root:
            continue
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, directory)
            if is_test_file(rel):
                test_files.append(rel)
    return test_files


def synthesize_smoke_test_if_missing(workspace_dir: str, generated_files: Dict[str, str]) -> Optional[str]:
    """
    If no test file was produced by the worker, synthesize an appropriate smoke test
    file that genuinely verifies the generated assets (HTML structure, JS parsing, exports).
    Returns relative path of created test file, or None.
    """
    has_html = any(f.endswith(".html") for f in generated_files.keys())
    has_js = any(f.endswith(".js") for f in generated_files.keys())
    has_py = any(f.endswith(".py") for f in generated_files.keys())

    tests_dir = os.path.join(workspace_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)

    if has_py:
        test_path = os.path.join(tests_dir, "test_smoke.py")
        code = '''import os
import unittest

class SmokeTest(unittest.TestCase):
    def test_python_syntax_and_imports(self):
        """Verify generated Python files exist, are non-empty, and compile without syntax errors."""
        import compileall
        compile_result = compileall.compile_dir('.', maxlevels=3, quiet=True)
        self.assertTrue(compile_result, "One or more Python files have syntax errors.")

if __name__ == '__main__':
    unittest.main()
'''
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(code)
        return "tests/test_smoke.py"

    # Default to Node/JS smoke test for web/frontend tasks
    test_path = os.path.join(tests_dir, "smoke.test.js")
    code = '''const fs = require('fs');
const path = require('path');
const assert = require('assert');

function runSmokeTests() {
    console.log("Running Frontend & Web Smoke Test Suite...");
    let checks = 0;

    // 1. Verify index.html exists and is well-formed
    const htmlPath = path.join(__dirname, '..', 'index.html');
    if (fs.existsSync(htmlPath)) {
        const html = fs.readFileSync(htmlPath, 'utf8');
        assert.ok(html.length > 50, "index.html is unexpectedly small or empty");
        assert.ok(html.includes('<html') || html.includes('<!DOCTYPE'), "index.html missing HTML root doctype/tag");
        checks++;
        console.log("✓ index.html structure verified");
    }

    // 2. Verify all JS files compile without syntax errors
    const srcDir = path.join(__dirname, '..', 'src');
    const rootDir = path.join(__dirname, '..');
    const jsFiles = [];
    
    [rootDir, srcDir].forEach(dir => {
        if (fs.existsSync(dir)) {
            fs.readdirSync(dir).forEach(f => {
                if (f.endsWith('.js') && !f.includes('test') && !f.includes('spec')) {
                    jsFiles.push(path.join(dir, f));
                }
            });
        }
    });

    assert.ok(jsFiles.length > 0 || fs.existsSync(htmlPath), "No implementation files found to verify");

    jsFiles.forEach(file => {
        const code = fs.readFileSync(file, 'utf8');
        assert.ok(code.trim().length > 0, `JS file ${file} is empty`);
        // Test parsing via Function constructor
        try {
            new Function(code);
        } catch (e) {
            // Function constructor might fail on top-level imports/exports, which is normal for ES modules
            if (!e.message.includes('import') && !e.message.includes('export')) {
                throw new Error(`Syntax error in ${path.basename(file)}: ${e.message}`);
            }
        }
        checks++;
        console.log(`✓ ${path.basename(file)} syntax validated`);
    });

    // 3. Verify CSS if present
    const cssPath = path.join(__dirname, '..', 'style.css');
    const srcCss = path.join(srcDir, 'style.css');
    const activeCss = fs.existsSync(cssPath) ? cssPath : (fs.existsSync(srcCss) ? srcCss : null);
    if (activeCss) {
        const css = fs.readFileSync(activeCss, 'utf8');
        assert.ok(css.length > 10, "CSS file is empty");
        checks++;
        console.log("✓ CSS styling verified");
    }

    assert.ok(checks > 0, "No smoke checks were executed");
    console.log(`Smoke test suite passed with ${checks} verification checks.`);
}

try {
    runSmokeTests();
    process.exit(0);
} catch (err) {
    console.error("SMOKE TEST FAILED:", err.message);
    process.exit(1);
}
'''
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(code)
    return "tests/smoke.test.js"


def execute_test_command(cmd: List[str], cwd: str, timeout: int = 45) -> Tuple[int, str]:
    """Run a test command with timeout, capturing stdout and stderr combined."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True if sys.platform == "win32" else False
        )
        output = proc.stdout
        if proc.stderr:
            output += "\n--- STDERR ---\n" + proc.stderr
        return proc.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return 124, f"ERROR: Test execution timed out after {timeout} seconds."
    except Exception as e:
        return 1, f"ERROR executing command {' '.join(cmd)}: {e}"


def run_test_suite(workspace_dir: str) -> Tuple[bool, str]:
    """
    Locates and executes all appropriate tests in the workspace.
    Enforces the zero-tolerance policy: ANY failure blocks the merge.
    Returns (passed: bool, output: str).
    """
    test_files = find_test_files_in_dir(workspace_dir)
    
    if not test_files:
        return False, "FAILED: No test files found in workspace."

    # Validate that at least one test file has non-trivial assertions
    valid_tests_count = 0
    validation_failures = []
    for tf in test_files:
        full_path = os.path.join(workspace_dir, tf)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            is_valid, reason = inspect_test_content(content)
            if is_valid:
                valid_tests_count += 1
            else:
                validation_failures.append(f"{tf}: {reason}")
        except Exception as e:
            validation_failures.append(f"{tf}: Error reading file - {e}")

    if valid_tests_count == 0:
        return False, "FAILED: All test files were rejected as empty, missing, or trivially fake:\n" + "\n".join(validation_failures)

    all_outputs = []
    has_failures = False

    # 1. If package.json has test script, try npm test
    pkg_json = os.path.join(workspace_dir, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                content = f.read()
            if '"test"' in content and 'no test specified' not in content:
                code, out = execute_test_command(["npm", "test"], cwd=workspace_dir)
                all_outputs.append(f"=== npm test ===\n{out}")
                if code != 0:
                    has_failures = True
        except Exception as e:
            all_outputs.append(f"npm test check error: {e}")

    # 2. Run Node.js tests
    js_tests = [tf for tf in test_files if tf.endswith((".js", ".mjs", ".cjs"))]
    for tf in js_tests:
        # First try node built-in test runner or direct node execution
        code, out = execute_test_command(["node", tf], cwd=workspace_dir)
        all_outputs.append(f"=== node {tf} ===\n{out}")
        if code != 0:
            has_failures = True

    # 3. Run Python tests
    py_tests = [tf for tf in test_files if tf.endswith(".py")]
    if py_tests:
        code, out = execute_test_command([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=workspace_dir)
        all_outputs.append(f"=== python unittest ===\n{out}")
        if code != 0:
            has_failures = True

    full_output = "\n\n".join(all_outputs)
    
    if has_failures:
        return False, f"TEST EXECUTION FAILED (One or more test suites failed with non-zero exit code):\n\n{full_output}"

    return True, f"ALL TESTS PASSED (Zero failures across {len(test_files)} test files):\n\n{full_output}"


async def verify_and_run_task_tests(workspace_dir: str, files_written: Dict[str, str]) -> Tuple[bool, str]:
    """
    Main entry point for QA Agent to verify task code before merging.
    1. Ensures tests exist or synthesizes a smoke test.
    2. Inspects test quality (rejecting fake/empty tests).
    3. Runs the test suite against the checked-out branch.
    """
    # 1. Check if any written files were test files
    written_test_files = [k for k in files_written.keys() if is_test_file(k)]
    
    # If the task produced code but no test files, synthesize an appropriate smoke test
    if not written_test_files:
        synthesized = synthesize_smoke_test_if_missing(workspace_dir, files_written)
        if synthesized:
            print(f"QA Agent: Synthesized smoke test at {synthesized} for verification.")

    # 2. Run full test suite
    passed, output = run_test_suite(workspace_dir)
    return passed, output


async def check_cascading_dependency_health(workspace_dir: str, depends_on_id: int) -> Tuple[bool, str]:
    """
    Cascading failure containment:
    Before dispatching a task whose depends_on task merged, re-verify that current main
    still passes all tests. This prevents broken combined code from cascading into new tasks.
    """
    print(f"QA Agent: Running Cascading Failure Containment check for Dependency Task #{depends_on_id} on main...")
    
    # Sync workspace to latest main
    subprocess.run(["git", "fetch", "origin", "main"], cwd=workspace_dir, check=False)
    subprocess.run(["git", "checkout", "-f", "-B", "main", "origin/main"], cwd=workspace_dir, check=False)
    subprocess.run(["git", "pull", "origin", "main"], cwd=workspace_dir, check=False)
    
    passed, output = run_test_suite(workspace_dir)
    if not passed:
        return False, (
            f"CASCADING FAILURE CONTAINMENT BLOCKED DISPATCH:\n"
            f"Dependency Task #{depends_on_id} merged code is failing tests on current main branch.\n"
            f"Halting task dispatch until main is fixed.\n\n"
            f"Test Output on main:\n{output}"
        )
    
    return True, "Dependency verified: main branch tests passed cleanly."
