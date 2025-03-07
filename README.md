# Basilisp nREPL MCP Bridge

This project provides a bridge between Anthropic's Model Control Protocol (MCP) and Basilisp's nREPL server, allowing Claude to interact directly with a Basilisp REPL.
Actually, it should work with any nREPL, but the current prompts are Basilisp focused.

## Features

- Execute Basilisp code and receive pretty-printed, syntax-highlighted results
- Get documentation for Basilisp symbols
- List all available namespaces
- Find all variables in a namespace
- Check nREPL server connectivity
- Python interop with proper syntax for attribute access and method calls
- Enhanced error reporting and formatting

## Requirements

- Python 3.8+
- uv
- Basilisp (optional, should work with any nREPL)
- MCP Python SDK
- pygments (for syntax highlighting)

## Usage

1. Start a Basilisp nREPL server:
   ```
   basilisp nrepl-server --port 36915
   ```

2. Add the MCP bridge to Claude:
   ```
   claude mcp add /home/a/subjective/snr/basilisp_mcp_bridge.py
   ```

3. Connect with Claude and use the available tools:
   - `eval_code(code)` - Evaluate Basilisp code
   - `get_docs(symbol)` - Get documentation for a symbol
   - `find_namespace_vars(namespace)` - List variables in a namespace
   - `list_namespaces()` - List all available namespaces
   - `check_connection()` - Verify nREPL connectivity

## Python Interop Examples

```clojure
;; Import a module
(import [math :as math])

;; Access an attribute
(. math -pi)  ;; or (.-pi math)

;; Call a method
(.sin math 0)

;; Create Python data structures
#py{"key" "value"}
```

## Future Improvements

- Implement a proper bencode parser (beyond regex)
- Add session management for multiple REPLs
- Add auto-completion support
