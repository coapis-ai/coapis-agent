"""Test namespace isolation in Docker container."""
import ctypes, ctypes.util, os, subprocess, tempfile, sys

libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
CLONE_NEWNS = 0x00020000
MS_REMOUNT = 32
MS_BIND = 4096
MS_REC = 0x4000
MS_RDONLY = 1
MS_SLAVE = 1 << 19

def do_mount(source, target, fstype, flags, data=None):
    ret = libc.mount(source, target, fstype, flags, data)
    err = ctypes.get_errno()
    return ret, err

test_dir = tempfile.mkdtemp(prefix="ns_dbg_")

# Step 1: unshare
ret = libc.unshare(CLONE_NEWNS)
err = ctypes.get_errno()
print(f"unshare ret={ret} errno={err}")

# Step 2: bind workspace
target = test_dir.encode()
ret, err = do_mount(target, target, b"", MS_BIND)
print(f"bind workspace ret={ret} errno={err}")

# Step 3: make / slave
ret, err = do_mount(b"", b"/", b"", MS_REC | MS_SLAVE)
print(f"MS_SLAVE / ret={ret} errno={err}")

# Step 4: remount / read-only
ret, err = do_mount(b"/", b"/", b"", MS_REMOUNT | MS_REC | MS_RDONLY)
print(f"remount / ret={ret} errno={err}")

# Test write to /
r = subprocess.run(["sh", "-c", "touch /ns_test_123 2>&1 && echo WRITABLE || echo READONLY"],
    capture_output=True, text=True, timeout=3)
print(f"Write /: {r.stdout.strip()}")

# Test write to workspace
r = subprocess.run(["sh", "-c", f"touch {test_dir}/ok 2>&1 && echo WRITABLE || echo READONLY"],
    capture_output=True, text=True, timeout=3)
print(f"Write workspace: {r.stdout.strip()}")
