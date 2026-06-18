#!/usr/bin/env python3
"""MuGA API Integration Test"""
import asyncio
import aiohttp
import json

async def test_all_operations():
    base_url = "http://127.0.0.1:4103"
    
    async with aiohttp.ClientSession() as session:
        # Login
        async with session.post(f"{base_url}/api/auth/login",
            json={"username": "admin", "password": "admin123"}) as resp:
            data = await resp.json()
            token = data.get("token")
            print(f"✅ Login successful")
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test 1: List files
        async with session.get(f"{base_url}/myfiles/list", 
            params={"path": "/", "category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"✅ List: {len(result.get('items', []))} files found")
            for item in result.get('items', []):
                print(f"   - {item['name']} ({item['size']}B)")
        
        # Test 2: Upload file
        from aiohttp import FormData
        form = FormData()
        form.add_field('file', b'Upload test content', filename='upload_test.txt')
        async with session.post(f"{base_url}/myfiles/upload",
            data=form,
            params={"path": "/", "category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"✅ Upload: {result.get('message', 'unknown')}")
        
        # Test 3: Create directory
        async with session.post(f"{base_url}/myfiles/mkdir",
            json={"path": "/", "name": "test_dir"},
            params={"category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"✅ Mkdir: {result.get('message', 'unknown')}")
        
        # Test 4: Preview file
        async with session.get(f"{base_url}/myfiles/preview",
            params={"path": "/upload_test.txt", "category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"✅ Preview: content={result.get('content', '')[:30]}")
        
        # Test 5: Download file
        async with session.get(f"{base_url}/myfiles/download",
            params={"path": "/upload_test.txt", "category": "files"},
            headers=headers) as resp:
            content = await resp.read()
            print(f"✅ Download: {len(content)} bytes")
        
        # Test 6: Rename file
        async with session.put(f"{base_url}/myfiles/rename",
            json={"path": "/upload_test.txt", "newName": "renamed_upload.txt"},
            params={"category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"✅ Rename: {result.get('message', 'unknown')}")
        
        # Test 7: Delete directory
        async with session.delete(f"{base_url}/myfiles/delete",
            params={"path": "/test_dir", "category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"✅ Delete: {result.get('message', 'unknown')}")
        
        # Final list
        async with session.get(f"{base_url}/myfiles/list", 
            params={"path": "/", "category": "files"},
            headers=headers) as resp:
            result = await resp.json()
            print(f"\n📋 Final state: {len(result.get('items', []))} files")
            for item in result.get('items', []):
                print(f"   - {item['name']} ({item['size']}B)")

asyncio.run(test_all_operations())
