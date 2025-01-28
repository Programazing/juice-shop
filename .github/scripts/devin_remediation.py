import asyncio
import aiohttp
import os
import subprocess
from datetime import datetime

# GitHub Actions specific environment variables
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GITHUB_ACTOR = os.getenv("GITHUB_ACTOR")
GITHUB_REF = os.getenv("GITHUB_REF")
GITHUB_SHA = os.getenv("GITHUB_SHA")

# API tokens and URLs
SONAR_TOKEN = os.getenv("SONAR_TOKEN")
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEVIN_API_BASE = "https://api.devin.ai/v1"

# SonarCloud organization and project key from secrets
SONAR_ORG = os.getenv("ORG")
SONAR_PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY")

async def get_sonarcloud_issues():
    url = "https://sonarcloud.io/api/issues/search"
    headers = {"Authorization": f"Bearer {SONAR_TOKEN}"}
    params = {
        "organization": SONAR_ORG,
        "projectKeys": SONAR_PROJECT_KEY,
        "types": "VULNERABILITY",
        "statuses": "OPEN"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status != 200:
                print(f"Error getting SonarCloud issues: {await response.text()}")
                return []
            result = await response.json()
            print(f"Found {len(result.get('issues', []))} issues")
            return result.get('issues', [])

async def create_devin_session(issue):
    # Create a safe branch name from issue
    safe_issue_name = issue['message'].lower()
    safe_issue_name = ''.join(c if c.isalnum() or c in '-_ ' else '' for c in safe_issue_name)
    safe_issue_name = safe_issue_name.replace(' ', '-')[:50]
    branch_name = f"fix/devin/{safe_issue_name}"
    
    print(f"Creating branch: {branch_name}")
    
    # Configure git for GitHub Actions
    subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"])
    subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"])
    
    # Create and checkout new branch
    subprocess.run(["git", "checkout", "-b", branch_name])
    
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {DEVIN_API_KEY}"}
        data = {
            "prompt": (
                f"Fix the following vulnerability in {GITHUB_REPOSITORY}: "
                f"{issue['message']} in file {issue['component']}. "
                f"Implement the fix and provide a detailed commit message explaining the changes."
            ),
            "idempotent": True
        }
        
        print(f"Creating Devin session for issue: {issue['message']}")
        
        async with session.post(f"{DEVIN_API_BASE}/sessions", json=data, headers=headers) as response:
            if response.status != 200:
                print(f"Error creating Devin session: {await response.text()}")
                return None
            result = await response.json()
            print(f"Devin session created: {result}")
            return result

async def get_devin_result(session_id):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {DEVIN_API_KEY}"}
        async with session.get(f"{DEVIN_API_BASE}/session/{session_id}", headers=headers) as response:
            if response.status != 200:
                print(f"Error getting Devin result: {await response.text()}")
                return None
            return await response.json()

async def commit_changes(issue):
    # Add all changes
    subprocess.run(["git", "add", "."])
    
    # Create commit message
    commit_message = f"fix: Remediate vulnerability - {issue['message']}\n\n"
    commit_message += f"Issue Key: {issue['key']}\n"
    commit_message += f"Component: {issue['component']}\n"
    commit_message += f"Fixed by Devin AI at {datetime.now().isoformat()}\n"
    commit_message += f"\nCo-authored-by: github-actions[bot] <github-actions[bot]@users.noreply.github.com>"
    
    # Commit changes
    subprocess.run(["git", "commit", "-m", commit_message])
    
    # Set up remote with token for push
    remote_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPOSITORY}.git"
    subprocess.run(["git", "remote", "set-url", "origin", remote_url])
    
    # Push changes
    result = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error pushing changes: {result.stderr}")
    else:
        print(f"Successfully pushed changes: {result.stdout}")

async def main():
    try:
        issues = await get_sonarcloud_issues()
        
        for issue in issues:
            print(f"Processing issue: {issue['key']}")
            
            session_data = await create_devin_session(issue)
            if not session_data:
                continue
                
            session_id = session_data["session_id"]
            
            while True:
                result = await get_devin_result(session_id)
                if not result:
                    break
                    
                if result["status_enum"] in ["blocked", "stopped"]:
                    if "structured_output" in result and "fix" in result["structured_output"]:
                        await commit_changes(issue)
                    break
                await asyncio.sleep(5)
                
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
