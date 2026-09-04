import os
import subprocess
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

    def create_branch(self, branch_name: str):
        """Create and checkout a new branch."""
        print(f"GitAgent: Creating branch {branch_name}...")
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=self.working_dir, check=True, capture_output=True)

    def commit_changes(self, message: str):
        """Add all changes and commit."""
        print(f"GitAgent: Committing changes: {message}")
        subprocess.run(["git", "add", "."], cwd=self.working_dir, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.working_dir, check=True)

    def push_branch(self, branch_name: str):
        """Push the branch to the remote repository."""
        print(f"GitAgent: Pushing branch {branch_name} to origin...")
        subprocess.run(["git", "push", "-u", "origin", branch_name], cwd=self.working_dir, check=True, capture_output=True)

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
        
        print(f"GitAgent: Opening Pull Request for {branch_name}...")
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                if resp.status != 201:
                    error_text = await resp.text()
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
            async with session.put(api_url, headers=headers, json=payload) as resp:
                if resp.status not in (200, 201):
                    error_text = await resp.text()
                    raise RuntimeError(f"Failed to merge PR: {resp.status} - {error_text}")
