"""Test ToolCallMonitor blocking capability."""
import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from coapis.security.tool_monitor import ToolCallMonitor, ToolCallRecord

monitor = ToolCallMonitor()
monitor._block_duration = 2  # 2 seconds for fast testing
monitor._critical_block_threshold = 3
monitor._high_freq_block_threshold = 3

# Test 1: Normal usage → no block
record = ToolCallRecord(user_id="alice", tool_name="read_file", args_summary="{}", timestamp=time.time(), success=True, duration_ms=100)
monitor.record_call(record)
blocked, reason = monitor.should_block("alice")
assert not blocked, f"Test 1 failed: should not be blocked, got {reason}"
print("✅ Test 1: Normal usage → not blocked")

# Test 2: 3 critical alerts (different types to avoid dedup) → block
for i, atype in enumerate(["crit_a", "crit_b", "crit_c"]):
    monitor._add_alert("bob", atype, f"Critical #{i}", "critical")
blocked, reason = monitor.should_block("bob")
assert blocked, "Test 2 failed: should be blocked after 3 critical alerts"
print(f"✅ Test 2: 3 critical alerts → blocked ({reason})")

# Test 3: Blocked user stays blocked within window
blocked, _ = monitor.should_block("bob")
assert blocked, "Test 3 failed: should still be blocked within window"
print("✅ Test 3: Still blocked within window")

# Test 4: Unblocked after expiry
time.sleep(2.1)
blocked, _ = monitor.should_block("bob")
assert not blocked, "Test 4 failed: should be unblocked after expiry"
print("✅ Test 4: Auto-unblocked after 2s")

# Test 5: Manual unblock
monitor._blocked_users["charlie"] = time.time() + 300
assert monitor.is_blocked("charlie"), "Test 5a failed"
assert monitor.unblock_user("charlie"), "Test 5b failed"
assert not monitor.is_blocked("charlie"), "Test 5c failed"
print("✅ Test 5: Manual unblock works")

# Test 6: total anomaly threshold triggers block (8+ events)
for i in range(8):
    monitor._add_alert("dave", f"anomaly_{i}", f"Anomaly #{i}", "warning")
blocked, reason = monitor.should_block("dave")
assert blocked, "Test 6 failed: should block on total anomaly threshold"
print(f"✅ Test 6: Total anomaly threshold block ({reason})")

# Test 7: get_tool_call_monitor singleton
from coapis.security.tool_monitor import get_tool_call_monitor
m1 = get_tool_call_monitor()
m2 = get_tool_call_monitor()
assert m1 is m2, "Test 7 failed: singleton mismatch"
print("✅ Test 7: Singleton works")

print(f"\n{'='*50}")
print(f"All 7 tests passed ✅")
