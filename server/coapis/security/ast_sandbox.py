"""AST sandbox - code-level dangerous operation interception.

Parses Python code via AST and detects dangerous patterns like
exec, eval, __import__, __subclasses__, getattr exploitation, etc.

Pure Python, zero external dependencies.
"""

import ast
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ASTCheckResult:
    safe: bool
    violations: List[str]


# Dangerous built-in function names
DANGEROUS_BUILTINS = frozenset({
    "exec", "eval", "compile", "__import__",
    "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars",
    "breakpoint", "exit", "quit",
    "open",  # carefully handled - see attribute check
})

# Dangerous dunder attributes
DANGEROUS_DUNDERS = frozenset({
    "__subclasses__", "__bases__", "__mro__",
    "__globals__", "__code__", "__dict__",
    "__class__", "__init_subclass__",
    "__loader__", "__spec__",
})

# Dangerous module-level attributes accessed via getattr
DANGEROUS_ATTRS = frozenset({
    "__subclasses__", "__bases__", "__globals__",
    "__code__", "__dict__", "__class__",
})


class ASTSandbox:
    """AST-level code sandbox.

    Analyzes Python code before execution and detects dangerous
    patterns that could lead to code injection or privilege escalation.

    Pure Python, works on all platforms.
    """

    def __init__(self):
        self._violations: List[str] = []

    def check_code(self, code: str) -> ASTCheckResult:
        """Check Python code for dangerous AST patterns.

        Args:
            code: Python source code string

        Returns:
            ASTCheckResult with safe status and list of violations
        """
        self._violations = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ASTCheckResult(
                safe=False,
                violations=[f"Syntax error: {e}"],
            )

        # Walk the AST and check for dangerous patterns
        for node in ast.walk(tree):
            self._check_node(node)

        return ASTCheckResult(
            safe=len(self._violations) == 0,
            violations=list(self._violations),
        )

    def _check_node(self, node: ast.AST):
        """Check a single AST node for dangerous patterns."""
        # Check function calls
        if isinstance(node, ast.Call):
            self._check_call(node)

        # Check attribute access
        if isinstance(node, ast.Attribute):
            self._check_attribute(node)

        # Check imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._check_import(node)

        # Check variable names (for __import__ tricks)
        if isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id.endswith("__"):
                if node.id in DANGEROUS_DUNDERS:
                    self._violation(f"Dangerous dunder access: {node.id}")

    def _check_call(self, node: ast.Call):
        """Check function calls for dangerous patterns."""
        func = node.func

        # Direct call: exec(...), eval(...)
        if isinstance(func, ast.Name):
            if func.id in DANGEROUS_BUILTINS:
                self._violation(f"Dangerous function call: {func.id}()")

        # Attribute call: obj.__import__(...)
        if isinstance(func, ast.Attribute):
            if func.attr in DANGEROUS_DUNDERS:
                self._violation(f"Dangerous method call: .{func.attr}()")

        # Check for string-based dynamic execution
        if isinstance(func, ast.Name) and func.id in ("exec", "eval", "compile"):
            # Check if argument is a string literal (direct code injection)
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._violation(
                        f"Dynamic code execution with string literal: {func.id}('...')"
                    )
                elif isinstance(arg, ast.JoinedStr):
                    self._violation(
                        f"Dynamic code execution with f-string: {func.id}(f'...')"
                    )

    def _check_attribute(self, node: ast.Attribute):
        """Check attribute access for dangerous patterns."""
        if node.attr in DANGEROUS_DUNDERS:
            self._violation(f"Dangerous attribute access: .{node.attr}")

        # Check for chained __class__.__subclasses__() pattern
        if node.attr == "__class__":
            # Look at parent nodes for chaining
            pass  # Handled by the __subclasses__ check above

    def _check_import(self, node: ast.AST):
        """Check imports for dangerous patterns."""
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("__"):
                    self._violation(f"Suspicious import name: {alias.name}")

        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("__"):
                self._violation(f"Suspicious import source: {node.module}")

            # Check for importing dangerous names
            if node.names:
                for alias in node.names:
                    if alias.name in DANGEROUS_BUILTINS:
                        self._violation(
                            f"Importing dangerous builtin: {alias.name}"
                        )

    def _violation(self, message: str):
        """Record a violation."""
        self._violations.append(message)
        logger.warning("AST violation: %s", message)

    def check_expression(self, expression: str) -> ASTCheckResult:
        """Check a single Python expression for dangerous patterns.

        Simpler than check_code - for one-liner expressions.
        """
        # Wrap in a function to make it parseable
        code = f"__sandbox_check_result = {expression}"
        return self.check_code(code)

    def get_violations(self) -> List[str]:
        """Get list of violations from last check."""
        return list(self._violations)
