import asyncio
import aiohttp
import os
import subprocess
from datetime import datetime

SONAR_TOKEN = os.getenv("SONAR_TOKEN")
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")
DEVIN_API_BASE = "https://api.devin.ai/v1"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

async def get_sonarcloud_issues():
    url = "https://sonarcloud.io/api/issues/search"
    headers = {"Authorization": f"Bearer {SONAR_TOKEN}"}
    params = {
        "types": "VULNERABILITY",
        "statuses": "OPEN"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            result = await response.json()
            print(f"Found {len(result.get('issues', []))} issues")
            return result.get('issues', [])

async def create_devin_session(issue):
    # Create branch name from issue
    safe_issue_name = issue['message'].lower().replace(' ', '-')[:50]
    branch_name = f"fix/{safe_issue_name}"
    
    print(f"Creating branch: {branch_name}")
    
    # Create and checkout new branch
    subprocess.run(["git", "checkout", "-b", branch_name])
    
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {DEVIN_API_KEY}"}
        data = {
            "prompt": f"Fix the following vulnerability: {issue['message']} in file {issue['component']}. Implement the fix and provide a detailed commit message explaining the changes.",
            "idempotent": True
        }
        
        print(f"Creating Devin session for issue: {issue['message']}")
        
        async with session.post(f"{DEVIN_API_BASE}/sessions", json=data, headers=headers) as response:
            result = await response.json()
            print(f"Devin session created: {result}")
            return result

async def get_devin_result(session_id):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {DEVIN_API_KEY}"}
        async with session.get(f"{DEVIN_API_BASE}/session/{session_id}", headers=headers) as response:
            return await response.json()

async def commit_changes(issue):
    # Add all changes
    subprocess.run(["git", "add", "."])
    
    # Create commit message
    commit_message = f"fix: Remediate vulnerability - {issue['message']}\n\n"
    commit_message += f"Issue Key: {issue['key']}\n"
    commit_message += f"Component: {issue['component']}\n"
    commit_message += f"Fixed by Devin AI at {datetime.now().isoformat()}"
    
    # Commit changes
    subprocess.run(["git", "commit", "-m", commit_message])
    
    # Push changes
    subprocess.run(["git", "push", "origin", f"HEAD"])

async def main():
    try:
        issues = await get_sonarcloud_issues()
        
        for issue in issues:
            print(f"Processing issue: {issue['key']}")
            
            session_data = await create_devin_session(issue)
            session_id = session_data["session_id"]
            
            while True:
                result = await get_devin_result(session_id)
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
