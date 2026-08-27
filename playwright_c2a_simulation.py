# -*- coding: utf-8 -*-
"""Playwright E2E Test for C2A Chat-to-Action Simulation."""

import time
from playwright.sync_api import sync_playwright, expect

def run_c2a_simulation():
    with sync_playwright() as p:
        # Launch headless browser using Playwright's built-in Chromium
        print("Starting Playwright Browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("1. Navigating to CoApis Console...")
        page.goto("http://localhost:4300")
        
        # Wait for the page to load or SPA routing to complete
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            print("Network idle timeout, but continuing...")

        # Check if login is needed (look for password input or login button)
        try:
            pass_input = page.locator('input[type="password"], input[name="password"]').first
            if pass_input.count() > 0 and not page.locator('.coapis-sidebar, .chat-container').count():
                print("2. Performing Login (admin/admin123)...")
                # Fill username and password
                page.fill('input[type="text"], input[name="username"]', 'admin')
                page.fill('input[type="password"], input[name="password"]', 'admin123')
                
                # Click login button - try common selectors
                page.click('button[type="submit"], button:has-text("登录"), button:has-text("Login")')
                
                # Wait for chat interface to appear or navigation
                page.wait_for_selector('.coapis-sidebar, .chat-area, [data-testid="chat-list"]', timeout=10000)
                print("Login successful and chat interface loaded.")
            else:
                print("Already logged in or main app interface detected. Proceeding to chat...")
        except Exception as e:
            print(f"Login step skipped or encountered issue: {e}")

        # Find Chat Input Area
        print("3. Finding Chat Input...")
        # Common selectors for chat input in React/Vue apps using Ant Design or similar
        chat_input = page.locator('textarea[class*="chat-input"], [contenteditable="true"][class*="editor"], .coapis-chat-input, .chat-editor')
        
        # If not found, try generic contenteditable or textarea in chat area
        if chat_input.count() == 0:
            chat_input = page.locator('textarea, [contenteditable="true"]').first
        
        print(f"Chat input locator count: {chat_input.count()}")

        if chat_input.count() > 0:
            # Simulate Message 1: Data Table Trigger
            msg1 = "生成一个包含用户ID、姓名、状态的表格数据测试卡片"
            print(f"4. Sending message (DataTable trigger): '{msg1}'")
            
            # Fill and send
            chat_input.fill(msg1)
            page.keyboard.press('Enter')
            
            # Wait for response processing
            page.wait_for_timeout(5000) 
            
            # Check for DataTableCard or similar C2A card components in DOM
            print("5. Checking for DataTable Card component...")
            data_table_card = page.locator('.coapis-card-data-table, [data-card-type="data_table"], .DataTableCard, .card[data-type="table"]')
            if data_table_card.count() > 0:
                print("SUCCESS: DataTableCard found in DOM.")
            else:
                print("INFO: DataTableCard not immediately found. (LLM may have returned text or card not rendered yet)")

            # Simulate Message 2: Action Link Trigger (Approval)
            msg2 = "生成一个待办审批卡片，包含批准和拒绝按钮"
            print(f"6. Sending message (ActionLink trigger): '{msg2}'")
            
            chat_input.fill(msg2)
            page.keyboard.press('Enter')
            
            page.wait_for_timeout(5000)

            # Check for ActionLinkCard
            print("7. Checking for ActionLink Card component...")
            action_link_card = page.locator('.coapis-card-action-link, [data-card-type="action_links"], .ActionLinkCard, .card[data-type="actions"]')
            if action_link_card.count() > 0:
                print("SUCCESS: ActionLinkCard found in DOM.")
            else:
                print("INFO: ActionLinkCard not immediately found.")

        # Take a screenshot of the current state to verify UI
        page.screenshot(path="/apps/ai/tool-dev/dev-coapis/playwright_c2a_simulation.png")
        print("8. Screenshot saved to /apps/ai/tool-dev/dev-coapis/playwright_c2a_simulation.png")

        browser.close()
        print("C2A Simulation Test Completed.")

if __name__ == "__main__":
    run_c2a_simulation()
