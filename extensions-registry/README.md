# C2A Extensions Registry

This registry allows community contributors to submit and register custom `extensions` namespace for the Chat-to-Action (C2A) Interactive Message Protocol.

## Extension Namespace Format

Custom extensions should follow the format: `com.{organization}.{domain}.{feature}`

Examples:
- `com.analytics.charts` - Analytics chart visualizations
- `org.devops.dashboard` - DevOps dashboard components
- `io.financial.transaction` - Financial transaction cards

## Submitting an Extension

To submit a new C2A extension:

1. Fork this repository
2. Add your extension definition in the `extensions/` directory
3. Create a pull request with your extension details

## Extension Specification

Each extension should include:
- `extension.json`: Extension metadata and schema definition
- `README.md`: Documentation for the extension usage
- `examples/`: Example C2A messages using this extension

## Available Extensions

### Official Extensions
- `com.coapis.c2a.data_table` - Data table rendering extension
- `com.coapis.c2a.form_definition` - Form definition extension
- `com.coapis.c2a.action_card` - Action card extension

### Community Extensions
*(Coming soon)*

---

*For questions or support, please open an issue in this repository.*
