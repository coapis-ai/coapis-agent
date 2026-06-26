import urllib.request, json

def login(username, password="admin123"):
    req = urllib.request.Request('http://localhost:8000/api/auth/login',
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        resp = json.loads(urllib.request.urlopen(req).read())
        return resp.get("token")
    except Exception as e:
        return None

def api_get(path, token):
    req = urllib.request.Request(f'http://localhost:8000{path}',
        headers={"Authorization": f"Bearer {token}"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        return {"error": str(e)}

# Login as admin
token = login("admin")
if not token:
    print("Login failed")
    exit(1)
print("Login OK")

# List cron jobs
jobs = api_get("/api/cron/jobs", token)
print(f"Cron jobs: {type(jobs).__name__}, count={len(jobs) if isinstance(jobs, list) else 'N/A'}")

# Create a test cron job
import urllib.request
create_req = urllib.request.Request('http://localhost:8000/api/cron/jobs',
    data=json.dumps({
        "name": "test-heartbeat",
        "schedule": {"cron": "*/5 * * * *"},
        "task_type": "text",
        "text": "heartbeat test",
        "dispatch": {
            "channel": "console",
            "target": {"user_id": "admin", "session_id": "test"}
        },
        "enabled": True,
        "runtime": {"max_concurrency": 1}
    }).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
try:
    created = json.loads(urllib.request.urlopen(create_req).read())
    print(f"Created job: id={created.get('id','?')}, name={created.get('name','?')}")
except Exception as e:
    print(f"Create job failed: {e}")

# List again
jobs2 = api_get("/api/cron/jobs", token)
print(f"Cron jobs after create: count={len(jobs2) if isinstance(jobs2, list) else 'N/A'}")
if isinstance(jobs2, list):
    for j in jobs2:
        print(f"  - {j.get('id','?')[:8]}: {j.get('name','?')} ({j.get('schedule',{}).get('cron','?')})")
