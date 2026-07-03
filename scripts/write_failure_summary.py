import os
import json
import datetime
from pathlib import Path

def main():
    run_id = os.environ.get('GITHUB_RUN_ID', 'unknown')
    event_name = os.environ.get('GITHUB_EVENT_NAME', 'unknown')
    head_sha = os.environ.get('GITHUB_SHA', 'unknown')
    server_url = os.environ.get('GITHUB_SERVER_URL', 'https://github.com')
    repo = os.environ.get('GITHUB_REPOSITORY', 'unknown')
    workflow_url = f"{server_url}/{repo}/actions/runs/{run_id}"

    utc_now = datetime.datetime.now(datetime.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        ro_now = utc_now.astimezone(ZoneInfo("Europe/Bucharest"))
        ro_str = ro_now.strftime('%Y-%m-%dT%H:%M:%S%z')
    except Exception:
        ro_str = 'unknown'

    utc_str = utc_now.strftime('%Y-%m-%dT%H:%M:%SZ')

    summary = {
        "run_id": run_id,
        "event": event_name,
        "created_at_utc": utc_str,
        "created_at_ro": ro_str,
        "conclusion": "failure",
        "failed_step": "unknown",
        "category": "unknown",
        "message_excerpt": "See GitHub Actions logs",
        "head_sha": head_sha,
        "workflow_url": workflow_url
    }

    out_dir = Path("public/debug/workflow_failures")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    date_str = utc_now.strftime('%Y-%m-%d')
    file_name = f"{date_str}_{run_id}.json"
    file_path = out_dir / file_name
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    index_path = out_dir / "index.json"
    index_data = []
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception:
            pass
    
    index_data.insert(0, summary)
    index_data = index_data[:50]
    
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

if __name__ == "__main__":
    main()
