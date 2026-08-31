import React from 'react';
import DataTableExample from './examples/DataTableExample';
import FormDefinitionExample from './examples/FormDefinitionExample';

function App() {
  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      <h1>C2A React Sandbox Examples</h1>
      <p>This sandbox demonstrates the Chat-to-Action (C2A) protocol rendering capabilities.</p>
      
      <div style={{ marginTop: '30px' }}>
        <h2>Data Table Example</h2>
        <DataTableExample />
        
        <h2 style={{ marginTop: '40px' }}>Form Definition Example</h2>
        <FormDefinitionExample />
      </div>
    </div>
  );
}

export default App;
