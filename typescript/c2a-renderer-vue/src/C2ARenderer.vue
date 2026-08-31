<template>
  <div class="c2a-renderer" :class="`state-${currentState.status}`">
    <!-- State Indicators -->
    <div v-if="currentState.status === 'generating'" class="c2a-state-generating">
      <div class="loading-spinner"></div>
      <span>Generating response...</span>
    </div>
    
    <div v-else-if="currentState.status === 'failed'" class="c2a-state-failed">
      <span class="error-icon">⚠️</span>
      <span>{{ currentState.error_message || 'Failed to render message' }}</span>
    </div>

    <!-- Blocks Rendering -->
    <div v-else-if="currentState.status === 'rendered' || currentState.status === 'interactive'" class="c2a-blocks-container">
      <template v-for="block in c2aMessage.blocks" :key="block.block_id">
        <!-- Text Markdown Block -->
        <div v-if="block.type === 'text_markdown'" class="c2a-block text-markdown-block" v-html="renderMarkdown(block.content.data.markdown)"></div>
        
        <!-- Data Table Block -->
        <div v-else-if="block.type === 'data_table'" class="c2a-block data-table-block">
          <table class="c2a-data-table">
            <thead>
              <tr>
                <th v-for="(header, index) in block.content.data.headers" :key="index">{{ header }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rowIndex) in block.content.data.rows" :key="rowIndex">
                <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Data List Block -->
        <div v-else-if="block.type === 'data_list'" class="c2a-block data-list-block">
          <ul class="c2a-data-list">
            <li v-for="(item, index) in block.content.data.items" :key="index">{{ item }}</li>
          </ul>
        </div>

        <!-- Form Definition Block -->
        <div v-else-if="block.type === 'form_definition'" class="c2a-block form-definition-block">
          <form class="c2a-form" @submit.prevent="handleFormSubmit">
            <div v-for="(field, index) in block.content.data.fields" :key="index" class="form-field">
              <label>{{ field.label }}</label>
              <input 
                v-if="field.type === 'text'" 
                type="text" 
                :name="field.name"
                :placeholder="field.placeholder"
              />
            </div>
          </form>
        </div>
      </template>
    </div>

    <!-- Actions Rendering -->
    <div v-if="currentState.status === 'interactive' && c2aMessage.actions.length > 0" class="c2a-actions-container">
      <button 
        v-for="action in c2aMessage.actions" 
        :key="action.action_id"
        :class="['c2a-action-button', `style-${action.style}`, { disabled: action.disabled }]"
        :disabled="action.disabled"
        @click="handleActionClick(action)"
      >
        <span v-if="action.icon">{{ action.icon }}</span>
        {{ action.label }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { C2AMessage, State, Action, Block } from './types';

interface Props {
  message: C2AMessage;
}

const props = defineProps<Props>();

// Current state derived from message
const currentState = computed<State>(() => {
  return props.message.state || { status: 'idle' };
});

// Render markdown content (simple HTML conversion for demo)
const renderMarkdown = (markdown: string | undefined): string => {
  if (!markdown) return '';
  // Simple markdown to HTML conversion
  let html = markdown
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+)\*/g, '<em>$1</em>')
    .replace(/`(.+)`/g, '<code>$1</code>');
  return html;
};

// Handle action click
const handleActionClick = (action: Action) => {
  if (action.disabled) return;
  
  // Emit action event for parent component to handle
  emit('action-click', action);
  
  // Execute based on intent
  switch (action.intent) {
    case 'api_call':
      console.log('API Call:', action.payload.api_endpoint);
      break;
    case 'workflow_trigger':
      console.log('Workflow Trigger:', action.payload.api_endpoint);
      break;
    default:
      console.log('Action executed:', action.action_id);
  }
};

// Handle form submit
const handleFormSubmit = () => {
  emit('form-submit', { type: 'form_definition' });
};

// Define emits
const emit = defineEmits<{
  (e: 'action-click', action: Action): void;
  (e: 'form-submit', formData: any): void;
}>();
</script>

<style scoped>
.c2a-renderer {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.c2a-state-generating {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: #666;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid #f3f3f3;
  border-top: 2px solid #007bff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.c2a-state-failed {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: #dc3545;
  background-color: #f8d7da;
  border-radius: 4px;
}

.c2a-blocks-container {
  margin-bottom: 16px;
}

.text-markdown-block {
  padding: 12px;
  line-height: 1.5;
}

.data-table-block {
  overflow-x: auto;
}

.c2a-data-table {
  width: 100%;
  border-collapse: collapse;
}

.c2a-data-table th,
.c2a-data-table td {
  padding: 8px 12px;
  border: 1px solid #dee2e6;
  text-align: left;
}

.c2a-data-table th {
  background-color: #f8f9fa;
  font-weight: 600;
}

.data-list-block {
  padding: 12px;
}

.c2a-data-list {
  margin: 0;
  padding-left: 24px;
}

.c2a-actions-container {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.c2a-action-button {
  padding: 8px 16px;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  background-color: #fff;
  cursor: pointer;
  transition: all 0.2s;
}

.c2a-action-button:hover:not(.disabled) {
  background-color: #f8f9fa;
}

.c2a-action-button.style-primary {
  background-color: #007bff;
  color: white;
  border-color: #007bff;
}

.c2a-action-button.style-success {
  background-color: #28a745;
  color: white;
  border-color: #28a745;
}

.c2a-action-button.style-danger {
  background-color: #dc3545;
  color: white;
  border-color: #dc3545;
}

.c2a-action-button.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
