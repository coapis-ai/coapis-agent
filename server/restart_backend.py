#!/usr/bin/env python3
"""CoApis Backend Restart Script"""
import os
import signal
import time
import subprocess
import shutil
import sys

BACKEND_DIR = "/apps/ai/tool-dev/devs/eater-claw"
LOG_DIR = "/var/log/coapis"
LOG_FILE = "/var/log/coapis/backend.log"
BACKEND_PORT = 4103


def find_backend_pid():
    """Find backend process PID from port"""
    result = subprocess.run(
        ["ss", "-tlnp"],
        capture_output=True,
        text=True
    )
    for line in result.stdout.split("\n"):
        if f":{BACKEND_PORT}" in line:
            import re
            m = re.search(r"pid=(\d+)", line)
            if m:
                return int(m.group(1))
    return None


def stop_backend():
    """Stop backend process"""
    pid = find_backend_pid()
    if not pid:
        print("✅ No backend process running")
        return True
    
    print(f"🛑 Found backend PID: {pid}")
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"   Sent SIGTERM to {pid}")
    except ProcessLookupError:
        print(f"   PID {pid} already gone")
        return True
    except PermissionError:
        print(f"   ⚠️ Permission denied for PID {pid}")
        return False
    
    # Wait for process to exit
    time.sleep(3)
    
    # Check if still running
    if find_backend_pid():
        print(f"   ⚠️ Process still running, sending SIGKILL")
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
        except:
            pass
    
    if find_backend_pid():
        print(f"❌ Failed to stop backend")
        return False
    
    print("✅ Backend stopped")
    return True


def clear_cache():
    """Clear __pycache__ directories"""
    count = 0
    for root, dirs, files in os.walk(BACKEND_DIR):
        if "__pycache__" in dirs:
            p = os.path.join(root, "__pycache__")
            shutil.rmtree(p, ignore_errors=True)
            count += 1
    print(f"🧹 Cleared {count} __pycache__ directories")


def start_backend():
    """Start backend"""
    print("🚀 Starting CoApis backend...")
    
    # Ensure log directory exists
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # Clear old log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    
    # Start in background
    cmd = ["bash", "start.sh"]
    
    log_fd = os.open(LOG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    
    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        cwd=BACKEND_DIR,
        env=os.environ.copy()
    )
    
    os.close(log_fd)
    
    print(f"✅ Backend started with PID {proc.pid}")
    
    # Wait for backend to be ready
    print("⏳ Waiting for backend to start...")
    for i in range(30):
        time.sleep(1)
        pid = find_backend_pid()
        if pid:
            print(f"✅ Backend is ready (PID {pid})")
            # Show log
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE) as f:
                    log_content = f.read()
                    print(f"\n📋 Log output:\n{log_content[-500:]}")
            return True
    
    print("❌ Backend failed to start within 30 seconds")
    # Show log
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            print(f.read())
    return False


def main():
    print("=" * 50)
    print("CoApis Backend Restart")
    print("=" * 50)
    
    # Stop
    print("\n🛑 Stopping backend...")
    if not stop_backend():
        print("⚠️ Continuing anyway...")
    
    # Clear cache
    print("\n🧹 Clearing cache...")
    clear_cache()
    
    # Start
    print("\n🚀 Starting backend...")
    if start_backend():
        print("\n✅ Backend restarted successfully!")
        return 0
    else:
        print("\n❌ Backend failed to start")
        return 1


if __name__ == "__main__":
    sys.exit(main())
