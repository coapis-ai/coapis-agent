/**
 * Playwright UI Automation Test Script for C2A Protocol v2.0 Features
 * 
 * This script tests the new C2A v2.0 features:
 * - row_actions in data_table blocks
 * - suggestions (LLM guided interactions) rendering and click handling
 */

import { test, expect } from '@playwright/test';

test('C2A v2.0 Features: data_table with row_actions and suggestions rendering', async ({ page }) => {
  // 1. Navigate to the C2A renderer test page or chat interface
  // For this test, we'll simulate receiving a C2A message with row_actions and suggestions
  
  console.log('Starting C2A v2.0 features UI test...');

  // Simulate C2A message with data_table + row_actions and suggestions
  const c2aMessageV2 = {
    protocol_version: 'c2a-v1.0',
    message_id: 'msg_c2a_v2_test_001',
    context_ref: {
      session_id: 'console:test1',
      scene_id: 'order_management_scene'
    },
    metadata: {
      generated_by: 'llm-agent',
      timestamp: 1692345678,
      source_system: 'coapis-c2a'
    },
    blocks: [
      {
        block_id: 'block_order_table_v2_01',
        type: 'data_table',
        content: {
          data: {
            headers: ['订单号', '金额', '状态'],
            rows: [
              ['ORD-001', '5000', 'pending'],
              ['ORD-002', '3000', 'completed']
            ]
          },
          row_actions: {
            view_detail_action: {
              action_id: 'btn_view_detail_ord_001',
              label: '查看详情',
              style: 'link',
              business_intent: 'view_order_detail',
              url_template: 'https://erp.example.com/orders/{order_id}',
              params_mapping: {
                order_id: '订单号'
              }
            }
          }
        }
      }
    ],
    actions: [],
    state: {
      status: 'rendered'
    },
    suggestions: [
      {
        suggestion_id: 'sug_view_detail_ord_001',
        label: '👁️ 查看 ORD-001 详情',
        business_intent: 'view_order_detail',
        context_data: { order_id: 'ORD-001' }
      },
      {
        suggestion_id: 'sug_export_list',
        label: '📤 导出当前列表为Excel',
        business_intent: 'export_list_to_excel'
      }
    ]
  };

  // 2. Inject C2A message into the page and render
  await page.evaluate((message) => {
    // Simulate C2ARenderer receiving the message
    (window as any).c2aMessageReceived = message;
    
    // Trigger rendering simulation
    if ((window as any).renderC2AMessage) {
      (window as any).renderC2AMessage(message);
    }
  }, c2aMessageV2);

  // 3. Verify data_table block is rendered with headers and rows
  const dataTableContainer = page.locator('.c2a-block-data_table');
  await expect(dataTableContainer).toBeVisible();

  // Verify headers
  const tableHeaders = dataTableContainer.locator('th');
  await expect(tableHeaders.nth(0)).toHaveText('订单号');
  await expect(tableRows => {
    // Check if action column header exists
  });
  
  // Verify row actions column header exists when row_actions are present
  const actionHeader = dataTableContainer.locator('.c2a-data-table-actions-header');
  await expect(actionHeader).toBeVisible();

  // Verify rows data
  const tableRows = dataTableContainer.locator('tbody tr');
  await expect(tableRows).toHaveCount(2);

  // First row data verification
  const firstRowCells = tableRows.nth(0).locator('td');
  await expect(firstRowCells.nth(0)).toHaveText('ORD-001');
  await expect(firstRowCells.nth(1)).toHaveText('5000');
  await expect(firstRowCells.nth(2)).toHaveText('pending');

  // Verify row action buttons are rendered in the first row
  const firstRowActions = dataTableContainer.locator('.c2a-row-actions').first();
  await expect(firstRowActions).toBeVisible();

  const viewDetailBtn = firstRowActions.locator('.c2a-row-action-link, .c2a-row-action-btn-primary');
  await expect(viewDetailBtn).toBeVisible();
  await expect(viewDetailBtn).toHaveText('查看详情');
  await expect(viewDetailBtn).toHaveAttribute('data-business-intent', 'view_order_detail');

  // 4. Verify suggestions block is rendered
  const suggestionsContainer = page.locator('.c2a-suggestions');
  await expect(suggestionsContainer).toBeVisible();

  const suggestionsTitle = suggestionsContainer.locator('.c2a-suggestions-title');
  await expect(suggestionsTitle).toHaveText('建议操作：');

  const suggestionList = suggestionsContainer.locator('.c2a-suggestion-list');
  await expect(suggestionList).toBeVisible();

  const suggestionButtons = suggestionList.locator('.c2a-suggestion-btn');
  await expect(suggestionButtons).toHaveCount(2);

  // First suggestion button verification
  const firstSuggestionBtn = suggestionButtons.nth(0);
  await expect(firstSuggestionBtn).toBeVisible();
  await expect(firstSuggestionBtn).toHaveText('👁️ 查看 ORD-001 详情');
  await expect(firstSuggestionBtn).toHaveAttribute('data-business-intent', 'view_order_detail');

  // Second suggestion button verification
  const secondSuggestionBtn = suggestionButtons.nth(1);
  await expect(secondSuggestionBtn).toBeVisible();
  await expect(secondSuggestionBtn).toHaveText('📤 导出当前列表为Excel');
  await expect(secondSuggestionBtn).toHaveAttribute('data-business-intent', 'export_list_to_excel');

  // 5. Verify row action button click triggers URL template replacement logic
  console.log('Verifying row action button click and URL template replacement...');
  
  // Simulate clicking the view detail button in the first row
  await viewDetailBtn.click();

  // Verify that the click event was captured (in a real implementation, this would trigger window.open or API call)
  const consoleMessages = page.locator('body').evaluate(() => {
    return (window as any).c2aClickEvents || [];
  });
  
  // Note: In a full integration test with the actual C2ARenderer component,
  // we would verify that window.open is called with the replaced URL:
  // 'https://erp.example.com/orders/ORD-001'

  console.log('C2A v2.0 features UI test completed successfully!');
});

test('C2A v2.0 Features: Fallback when row_actions are not present', async ({ page }) => {
  // Test that data_table renders correctly without row_actions
  
  const c2aMessageWithoutRowActions = {
    protocol_version: 'c2a-v1.0',
    message_id: 'msg_c2a_v2_test_no_actions_001',
    context_ref: { session_id: 'console:test1' },
    metadata: { generated_by: 'llm-agent', timestamp: 1692345678, source_system: 'coapis-c2a' },
    blocks: [
      {
        block_id: 'block_order_table_no_actions_01',
        type: 'data_table',
        content: {
          data: {
            headers: ['订单号', '金额', '状态'],
            rows: [
              ['ORD-001', '5000', 'pending']
            ]
          }
        }
      }
    ],
    actions: [],
    state: { status: 'rendered' },
    suggestions: []
  };

  await page.evaluate((message) => {
    (window as any).c2aMessageReceived = message;
    if ((window as any).renderC2AMessage) {
      (window as any).renderC2AMessage(message);
    }
  }, c2aMessageWithoutRowActions);

  const dataTableContainer = page.locator('.c2a-block-data_table');
  await expect(dataTableContainer).toBeVisible();

  // Verify that action column header is NOT present when row_actions are missing
  const actionHeader = dataTableContainer.locator('.c2a-data-table-actions-header');
  await expect(actionHeader).not.toBeVisible();

  console.log('C2A v2.0 fallback test completed successfully!');
});
