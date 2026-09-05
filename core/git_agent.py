import os
import subprocess
import asyncio
import aiohttp
from typing import Optional

async def _get_github_pat() -> str:
    from db.connection import get_connection
    from core.encryption import decrypt_key
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT api_key FROM api_credentials WHERE tool_name = 'GitHub PAT' LIMIT 1"
        )
        if not row:
            raise RuntimeError("GitHub PAT not found in API Credentials. Cannot push code.")
        return decrypt_key(row['api_key'])

def extract_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract owner and repo name from a github url."""
    # Example: https://github.com/user/repo or https://github.com/user/repo.git
    clean_url = repo_url.replace('.git', '')
    parts = clean_url.rstrip('/').split('/')
    return parts[-2], parts[-1]

class GitAgent:
    """The DevOps Agent responsible for safely branching, committing, and pushing code."""
    
    def __init__(self, repo_url: str, working_dir: str):
        self.repo_url = repo_url
        self.working_dir = working_dir
        self.owner, self.repo = extract_owner_repo(repo_url)

    async def clone_repo(self):
        """Clone the repository into the working directory using the PAT."""
        pat = await _get_github_pat()
        
        # Inject PAT into the URL for HTTPS authentication
        auth_url = self.repo_url.replace("https://", f"https://x-access-token:{pat}@")
        
        print(f"GitAgent: Cloning repository into {self.working_dir}...")
        subprocess.run(["git", "clone", auth_url, self.working_dir], check=True, capture_output=True)
        
        # Set git config so commits don't fail
        subprocess.run(["git", "config", "user.name", "AI DevOps Agent"], cwd=self.working_dir, check=True)
        subprocess.run(["git", "config", "user.email", "bot@orchestrator.ai"], cwd=self.working_dir, check=True)

        # Check if repo is empty (no remote branches) or missing 'main'
        result = subprocess.run(["git", "branch", "-r"], cwd=self.working_dir, capture_output=True, text=True)
        remote_output = result.stdout.strip()
        if not remote_output:
            print("GitAgent: Repository is completely empty. Initializing 'main' branch...")
            subprocess.run(["git", "checkout", "-b", "main"], cwd=self.working_dir, check=True)
            readme_path = os.path.join(self.working_dir, "README.md")
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(f"# {self.repo}\nRepository initialized by AI Swarm.")
            subprocess.run(["git", "add", "README.md"], cwd=self.working_dir, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.working_dir, check=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.working_dir, check=True)
        elif "origin/main" not in remote_output:
            print("GitAgent: Remote repository missing 'main' branch. Creating and pushing 'main'...")
            subprocess.run(["git", "checkout", "-b", "main"], cwd=self.working_dir, check=False)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.working_dir, check=False)

        # Attempt to set default branch to 'main' on GitHub via REST API
        try:
            repo_url = f"https://api.github.com/repos/{self.owner}/{self.repo}"
            headers = {"Authorization": f"token {pat}", "Accept": "application/vnd.github.v3+json"}
            async with aiohttp.ClientSession() as session:
                await session.patch(repo_url, headers=headers, json={"default_branch": "main"})
        except Exception:
            pass

        subprocess.run(["git", "checkout", "-B", "main", "origin/main"], cwd=self.working_dir, check=False)

    def create_branch(self, branch_name: str, base_branch: str = "main"):
        """Create and checkout a new branch strictly reset from origin/main."""
        print(f"GitAgent: Creating branch {branch_name} from origin/{base_branch}...")
        subprocess.run(["git", "fetch", "origin", base_branch], cwd=self.working_dir, check=False)
        subprocess.run(["git", "checkout", "-B", branch_name, f"origin/{base_branch}"], cwd=self.working_dir, check=True)

    def commit_changes(self, message: str):
        """Add all changes and commit."""
        print(f"GitAgent: Committing changes: {message}")
        subprocess.run(["git", "add", "."], cwd=self.working_dir, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.working_dir, check=True)

    def push_branch(self, branch_name: str):
        """Push the branch to the remote repository (force push to handle retries cleanly)."""
        print(f"GitAgent: Pushing branch {branch_name} to origin...")
        subprocess.run(["git", "push", "-u", "origin", branch_name, "--force"], cwd=self.working_dir, check=True)

    async def create_pull_request(self, branch_name: str, title: str, body: str, base_branch: str = "main") -> str:
        """Open a Pull Request on GitHub using the REST API."""
        pat = await _get_github_pat()
        api_url = f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls"
        
        headers = {
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = {
            "title": title,
            "body": body,
            "head": branch_name,
            "base": base_branch
        }
        
        print(f"GitAgent: Opening Pull Request for {branch_name} against {base_branch}...")
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                if resp.status != 201:
                    error_text = await resp.text()
                    # If base branch failed (e.g. 422 invalid base), query default branch and retry
                    if resp.status == 422:
                        repo_meta_url = f"https://api.github.com/repos/{self.owner}/{self.repo}"
                        async with session.get(repo_meta_url, headers=headers) as meta_resp:
                            if meta_resp.status == 200:
                                meta_data = await meta_resp.json()
                                default_b = meta_data.get("default_branch")
                                if default_b and default_b != base_branch:
                                    print(f"GitAgent: Retrying PR with default branch '{default_b}'...")
                                    payload["base"] = default_b
                                    async with session.post(api_url, headers=headers, json=payload) as retry_resp:
                                        if retry_resp.status == 201:
                                            retry_data = await retry_resp.json()
                                            return retry_data.get("html_url", "")
                    raise RuntimeError(f"Failed to create PR: {resp.status} - {error_text}")
                
                data = await resp.json()
                return data.get("html_url", "")
                
    async def auto_merge_pr(self, pr_number: int, commit_message: str):
        """Merge a PR automatically (used by the QA Agent if the code passes)."""
        pat = await _get_github_pat()
        api_url = f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls/{pr_number}/merge"
        
        headers = {
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = {
            "commit_title": commit_message,
            "merge_method": "squash"
        }
        
        print(f"GitAgent/QA: Merging Pull Request #{pr_number}...")
        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                async with session.put(api_url, headers=headers, json=payload) as resp:
                    if resp.status in (200, 201):
                        return
                    error_text = await resp.text()
                    if resp.status == 405 and attempt < 2:
                        print(f"GitAgent/QA: PR #{pr_number} merge pending (status 405), waiting 2s before retry (attempt {attempt + 1}/3)...")
                        await asyncio.sleep(2)
                        continue
                    raise RuntimeError(f"Failed to merge PR: {resp.status} - {error_text}")
