import os
import re
import subprocess
from core.models import Task, TaskStatus
from core.task_manager import update_task_status
from core.pm_llm import _call_pm_llm
from core.git_agent import GitAgent

def extract_code_blocks(text: str, default_filename: str = "src/app.js") -> dict[str, str]:
    """
    Extract file paths and code blocks from LLM markdown output.
    Handles varied LLM formatting (spaces in header, language tags, colon syntax, inline comments).
    """
    files = {}
    pattern = r"```([^\n]*)\n(.*?)```"
    matches = list(re.finditer(pattern, text, re.DOTALL))
    
    for match in matches:
        header = match.group(1).strip()
        code = match.group(2)
        header_lower = header.lower()
        
        # If header is purely a shell command tag with shell code, skip it
        if header_lower in ("bash", "sh", "shell", "console", "terminal", "powershell", "cmd"):
            lines = [l.strip() for l in code.strip().split('\n') if l.strip()]
            if all(l.startswith(("npm ", "npx ", "pip ", "yarn ", "git ", "cd ", "mkdir ", "node ", "#", "//", "$ ")) for l in lines):
                continue

        filepath = ""
        # 1. Check if header has a path (e.g. 'javascript tests/task.test.js' or 'src/main.py' or 'js:src/test.js')
        tokens = header.replace(":", " ").replace("=", " ").replace('"', '').replace("'", "").split()
        for tok in tokens:
            if "/" in tok or "\\" in tok or ("." in tok and not tok.startswith(".")):
                filepath = tok
                break
        
        # 2. Check if first line of code specifies filepath (e.g. '// tests/task.test.js')
        if not filepath and code:
            first_line = code.strip().split('\n')[0].strip()
            if first_line.startswith(("//", "#", "/*", "<!--")):
                for tok in first_line.split():
                    if ("/" in tok or "." in tok) and not tok.startswith(("http", "www")):
                        cleaned = tok.strip("/*#<!- '\"")
                        if "." in cleaned and not cleaned.startswith("."):
                            filepath = cleaned
                            break

        # 3. If still no filepath, synthesize an appropriate filename based on language or default
        if not filepath:
            ext = ".js"
            if "html" in header_lower:
                ext = ".html"
            elif "css" in header_lower:
                ext = ".css"
            elif "python" in header_lower or "py" in header_lower:
                ext = ".py"
            elif "json" in header_lower:
                ext = ".json"
            elif "ts" in header_lower:
                ext = ".ts"
            elif "sql" in header_lower:
                ext = ".sql"
            elif "md" in header_lower:
                ext = ".md"

            if len(files) == 0 and default_filename:
                base, _ = os.path.splitext(default_filename)
                filepath = f"{base}{ext}"
            else:
                filepath = f"src/file_{len(files) + 1}{ext}"

        files[filepath] = code

    # Fallback: if no code blocks found at all, but raw text looks like code, save to default_filename
    if not files and text.strip():
        code_indicators = ["function ", "const ", "let ", "var ", "import ", "export ", "class ", "describe(", "test(", "assert", "<!DOCTYPE", "<html>", "def "]
        if any(ind in text for ind in code_indicators):
            files[default_filename] = text.strip()

    return files

async def execute_task_with_swarm(task_id: int):
    """
    Spins up the Worker Agent for the task, generates code, 
    and uses the GitAgent to PR it.
    """
    print(f"Swarm: Assigning Task #{task_id} to a Worker Agent...")
    
    # 1. Fetch Task Info
    from db.connection import get_connection
    async with get_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        if not row:
            raise ValueError(f"Task {task_id} not found.")
        task = dict(row)

    project_id = task['project_id']
    title = task['title']
    brief = task['brief']
    ac = task['acceptance_criteria']
    repo_url = task.get('repo_url')
    
    if not repo_url:
        print(f"Swarm: Task #{task_id} has no repo_url. Cannot run DevOps agent.")
        await update_task_status(task_id, TaskStatus.FAILED, assigned_agent="Swarm Error")
        return

    category = task.get('category', '').lower()
    default_name = "src/app.js"
    if category == "testing":
        default_name = "tests/task.test.js"
    elif category == "boilerplate":
        default_name = "index.html"
    elif category in ("frontend", "ui"):
        default_name = "src/app.js"
    elif category == "css":
        default_name = "src/style.css"
    elif category in ("infra", "devops"):
        default_name = ".github/workflows/deploy.yml"

    # 2. Worker Agent LLM Call
    system_prompt = f"""You are an elite Autonomous AI Developer specializing in {task['category']} tasks.
Your job is to read the task description and write ALL the necessary implementation code to fulfill the acceptance criteria.

CRITICAL INSTRUCTIONS:
- You MUST output the actual runnable code inside standard markdown code blocks.
- Place the relative file path on the first line after the backticks (e.g. ```{default_name}).
- Do NOT output bash command snippets or setup advice like 'npm install'. Write the actual source file code.
- Write all files needed to complete this task."""

    user_prompt = f"""Project ID: {project_id}
Task: {title}
Description: {brief}

Acceptance Criteria:
{ac}

Please write the code for this task:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    await update_task_status(task_id, TaskStatus.IN_PROGRESS, assigned_agent="Worker Agent")
    print(f"Swarm: Worker Agent is coding...")
    
    try:
        raw_code_response = _call_pm_llm(messages)
        files_to_write = extract_code_blocks(raw_code_response, default_filename=default_name)
        
        if not files_to_write:
            raise ValueError("LLM returned no code blocks.")
            
        print(f"Swarm: Worker Agent generated {len(files_to_write)} files.")
        
        # 3. DevOps Agent Pipeline
        workspace_dir = f"/tmp/orchestrator_workspace_{project_id}"
        devops = GitAgent(repo_url=repo_url, working_dir=workspace_dir)
        
        # Clone repo or sync to latest main
        if not os.path.exists(workspace_dir):
            await devops.clone_repo()
        else:
            subprocess.run(["git", "fetch", "origin", "main"], cwd=workspace_dir, check=False)
            subprocess.run(["git", "clean", "-fd"], cwd=workspace_dir, check=False)
            subprocess.run(["git", "checkout", "-f", "-B", "main", "origin/main"], cwd=workspace_dir, check=False)
            subprocess.run(["git", "pull", "origin", "main"], cwd=workspace_dir, check=False)
            
        branch_name = f"feature/task-{task_id}-{title.lower().replace(' ', '-')}"
        devops.create_branch(branch_name, "main")
        
        # Write files
        for filepath, code in files_to_write.items():
            full_path = os.path.join(workspace_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(code)
                
        # Commit and Push
        commit_msg = f"Task #{task_id}: {title}\n\n{brief}"
        devops.commit_changes(commit_msg)
        devops.push_branch(branch_name)
        
        # Open PR
        pr_url = await devops.create_pull_request(
            branch_name=branch_name,
            title=f"Feature: {title} (Task #{task_id})",
            body=f"This PR was automatically generated by the Autonomous Swarm.\n\n**Brief:**\n{brief}\n\n**Acceptance Criteria:**\n{ac}"
        )
        print(f"Swarm: PR Created! {pr_url}")
        
        # 4. QA Agent (Optional Auto-Merge for low tier tasks)
        if task['complexity_score'] <= 3:
            print("Swarm: QA Agent Auto-Approving PR...")
            # In a real system, the QA agent would read the diff here. 
            # We assume it passes for MVP.
            pr_number = int(pr_url.split('/')[-1])
            await devops.auto_merge_pr(pr_number, commit_msg)
            
        await update_task_status(task_id, TaskStatus.DONE)
        
    except Exception as e:
        print(f"Swarm Error on Task #{task_id}: {e}")
        await update_task_status(task_id, TaskStatus.FAILED)
