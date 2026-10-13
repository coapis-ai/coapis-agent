#!/usr/bin/env python3
"""测试场景会话延续功能"""

import requests
import json

import os

BASE_URL = os.environ.get("COAPIS_TEST_BASE_URL", "http://localhost:4300")

def test_scene_session():
    """测试场景会话延续"""
    
    # 测试1：第一次进入场景
    print("【测试1：第一次进入会议纪要场景】")
    r1 = requests.post(
        f"{BASE_URL}/api/scenes/meeting-minutes/enter",
        json={},
        headers={"X-User-ID": "admin"}
    )
    
    if r1.status_code == 401:
        print("❌ 需要认证，尝试使用公开路径...")
        # 尝试使用公开的工作台API
        r1 = requests.post(
            f"{BASE_URL}/api/scenes/workbench/meeting-minutes/enter",
            json={}
        )
        if r1.status_code == 404:
            print("❌ 公开API不存在")
            return
        elif r1.status_code == 200:
            data1 = r1.json()
            print(f"✅ chat_id: {data1.get('chat_id')}")
            print(f"   session_id: {data1.get('session_id')}")
        else:
            print(f"❌ 状态码: {r1.status_code}")
            print(f"   响应: {r1.text[:200]}")
            return
    else:
        data1 = r1.json()
        print(f"✅ chat_id: {data1.get('chat_id')}")
        print(f"   session_id: {data1.get('session_id')}")
    
    # 测试2：第二次进入场景（应该返回相同的会话）
    print("\n【测试2：第二次进入会议纪要场景】")
    r2 = requests.post(
        f"{BASE_URL}/api/scenes/meeting-minutes/enter",
        json={},
        headers={"X-User-ID": "admin"}
    )
    
    if r2.status_code == 200:
        data2 = r2.json()
        print(f"✅ chat_id: {data2.get('chat_id')}")
        print(f"   session_id: {data2.get('session_id')}")
        
        # 检查是否相同
        if data1.get('chat_id') == data2.get('chat_id'):
            print("✅ 会话ID相同，会话已延续！")
        else:
            print("❌ 会话ID不同，创建了新会话")
    else:
        print(f"❌ 状态码: {r2.status_code}")
    
    # 测试3：强制创建新会话
    print("\n【测试3：强制创建新会话 (force_new=true)】")
    r3 = requests.post(
        f"{BASE_URL}/api/scenes/meeting-minutes/enter",
        json={"force_new": True},
        headers={"X-User-ID": "admin"}
    )
    
    if r3.status_code == 200:
        data3 = r3.json()
        print(f"✅ chat_id: {data3.get('chat_id')}")
        print(f"   session_id: {data3.get('session_id')}")
        print("✅ 强制创建新会话成功")
    else:
        print(f"❌ 状态码: {r3.status_code}")

if __name__ == "__main__":
    test_scene_session()
