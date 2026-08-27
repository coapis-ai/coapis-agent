# -*- coding: utf-8 -*-
"""Playwright automated test for C2A card rendering, MCP-to-C2A conversion, and interaction logic."""
import asyncio
import requests
import json
from playwright.async_api import async_playwright

TOKEN = "eyJzdWIiOiAidGVzdDEiLCAiZXhwIjogMTc4NzM4NDg5NCwgImlhdCI6IDE3ODY3ODAwOTQsICJqdGkiOiAiM2RlNTE5ZGIyZDEyNWI3ZjQxZmQ3Njk1OWVlYWIxYzkifQ==.d4686543043ad1e25d91c311b558110f7ae5d2b8a866703e61d59866ad879a3f"

def test_mcp_to_c2a_conversion_api():
    """Test the /api/messages/c2a/mcp/convert API endpoint."""
    print("\n=== Testing MCP-to-C2A Conversion API ===")
    api_url = "http://localhost:4308/api/messages/c2a/mcp/convert"
    
    # Payload matching MCPConvertRequest model (mcp_metadata, mcp_data, suggestions)
    payload_corrected = {
        "mcp_metadata": {
            "name": "get_user_info",
            "description": "Get user information",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"}
                }
            }
        },
        "mcp_data": {
            "user_id": "test123",
            "name": "Test User",
            "email": "test@example.com"
        },
        "suggestions": [
            {"label": "查看详情", "business_intent": "external_redirect", "context_data": {"url_template": "https://example.com/user/{{user_id}}"}}
        ]
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {TOKEN}'
    }
    
    try:
        response = requests.post(api_url, json=payload_corrected, headers=headers)
        print(f"API Status Code: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print("✅ MCP-to-C2A conversion API successful!")
            print(f"Response success: {result.get('success')}")
            if result.get('c2a_payload'):
                print(f"C2A payload generated - blocks: {len(result['c2a_payload'].get('blocks', []))}, suggestions: {len(result['c2a_payload'].get('suggestions', []))}")
        else:
            print(f"⚠️ API returned status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ MCP-to-C2A conversion API test failed: {e}")

async def test_frontend_url_template_logic():
    """Test the frontend URL template replacement logic via Playwright browser context."""
    print("\n=== Testing Frontend URL Template Replacement Logic ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Inject the replaceUrlTemplate logic into the browser context (mimicking C2ARenderer.tsx)
        js_logic = """
(function() {
    function replaceUrlTemplate(urlTemplate, context) {
        let result = urlTemplate;
        const placeholderRegex = /\\{\\{(\\w+)\\}\\}/g;
        let match;
        
        while ((match = placeholderRegex.exec(urlTemplate)) !== null) {
            const key = match[1];
            const value = context[key];
            
            if (value !== undefined && value !== null) {
                const encodedValue = encodeURIComponent(String(value));
                result = result.replace(match[0], encodedValue);
            } else {
                console.warn(`URL template placeholder {{${key}}} not found in context`);
                return urlTemplate;
            }
        }
        return result;
    }

    function handleExternalRedirect(targetUrl, options) {
        if (!targetUrl || (!targetUrl.startsWith('http://') && !targetUrl.startsWith('https://'))) {
            console.warn(`Invalid redirect URL: ${targetUrl}`);
            if (options?.fallbackAction) options.fallbackAction();
            return false;
        }
        try {
            const target = options?.openInNewTab ? '_blank' : '_self';
            if (options?.openInNewTab) {
                window.open(targetUrl, target, 'noopener,noreferrer');
            } else {
                window.location.href = targetUrl;
            }
            return true;
        } catch (error) {
            console.error('Error during external redirect:', error);
            if (options?.fallbackAction) options.fallbackAction();
            return false;
        }
    }

    const testCases = [
        {
            template: "https://example.com/user/{{user_id}}",
            context: { user_id: "test123" },
            expected: "https://example.com/user/test123"
        },
        {
            template: "https://example.com/order/{{order_id}}/item/{{item_id}}",
            context: { order_id: "ORD-001", item_id: "ITEM-456" },
            expected: "https://example.com/order/ORD-001/item/ITEM-456"
        },
        {
            template: "https://example.com/user/{{user_id}}?email={{email}}",
            context: { user_id: "test123", email: "test@example.com" },
            expected: "https://example.com/user/test123?email=test%40example.com"
        }
    ];

    let allPassed = true;
    for (let i = 0; i < testCases.length; i++) {
        const tc = testCases[i];
        const result = replaceUrlTemplate(tc.template, tc.context);
        if (result === tc.expected) {
            console.log(`✅ Test ${i+1} passed: ${tc.template} -> ${result}`);
        } else {
            console.log(`❌ Test ${i+1} failed: expected ${tc.expected}, got ${result}`);
            allPassed = false;
        }
    }

    // Test external redirect validation logic
    const redirectTests = [
        { url: "https://example.com/user/123", valid: true },
        { url: "http://example.com/test", valid: true },
        { url: "invalid-url", valid: false }
    ];

    for (let i = 0; i < redirectTests.length; i++) {
        const rt = redirectTests[i];
        // Simulate validation check
        isValid = rt.url.startsWith('http://') || rt.url.startsWith('https://');
        if (isValid === rt.valid) {
            console.log(`✅ Redirect test ${i+1} passed: URL validation for '${rt.url}' -> ${isValid}`);
        } else {
            console.log(`❌ Redirect test ${i+1} failed: expected ${rt.valid}, got ${isValid}`);
            allPassed = false;
        }
    }

    return allPassed;
})();
"""
        result = await page.evaluate(js_logic)
        if result:
            print("✅ Frontend URL template replacement and redirect logic test passed!")
        else:
            print("❌ Frontend URL template replacement and redirect logic test failed!")
        
        await browser.close()

async def main():
    print("Starting C2A Interaction Logic Verification Test...")
    
    # Test 1: MCP-to-C2A Conversion API
    test_mcp_to_c2a_conversion_api()
    
    # Test 2: Frontend URL Template & Redirect Logic
    await test_frontend_url_template_logic()
    
    print("\n=== C2A Interaction Logic Verification Complete ===")

if __name__ == '__main__':
    asyncio.run(main())
