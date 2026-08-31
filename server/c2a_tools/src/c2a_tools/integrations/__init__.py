"""C2A framework integrations.

Each module here adapts C2A to a specific agent framework by exposing
framework-native tool definitions. They import the framework's registry
lazily (inside the module / at call time) so importing c2a_tools never
requires the framework to be installed.
"""
