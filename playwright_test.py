# -*- coding: utf-8 -*-
"""Playwright E2E Test for C2A Messages and Cards."""

import asyncio
from playwright.sync_api import sync_playwright, BrowserContext, Page

def test_c2a_cards_e2e():
    with sync_playwright() as p:
        # Launch headless browser using Playwright's built-in Chromium
        browser = p.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context()
        page: Page = context.new_page()

        print("1. Navigating to CoApis Console...")
        page.goto("http://localhost:4300")
        
        # Wait for the page to load
        page.wait_for_load_state("networkidle")
        print("Page loaded successfully.")

        # Check if we're on the login page or already logged in
        page_title = page.title()
        print(f"Current page title: {page_title}")

        # Try to find a login form or check if we need to log in
        # Look for common login elements
        has_login_form = page.locator('input[type="password"]').count() > 0 or \
                         page.locator('input[name="password"]').count() > 0
        
        if has_login_form:
            print("2. Logging in with admin/admin123...")
            # Fill username and password
            page.fill('input[type="text"], input[name="username"]', 'admin')
            page.fill('input[type="password"], input[name="password"]', 'admin123')
            
            # Click login button
            page.click('button[type="submit"], button:has-text("登录"), button:has-text("Login")')
            page.wait_for_load_state("networkidle")
            print("Login completed.")

        print("3. Checking for chat interface and C2A card components...")
        # Check if chat interface is available
        chat_container_exists = page.locator('.coapis-chat, .chat-container, [data-testid="chat"]').count() > 0
        
        if chat_container_exists:
            print("Chat interface found.")
        else:
            print("Chat interface not found or still loading.")

        # Take a screenshot of the current state
        page.screenshot(path="/apps/ai/tool-dev/dev-coapis/playwright_test_screenshot.png")
        print("Screenshot saved to /apps/ai/tool-dev/dev-coapis/playwright_test_screenshot.png")

        browser.close()
        print("Test completed.")

if __name__ == "__main__":
    test_c2a_cards_e2e()
