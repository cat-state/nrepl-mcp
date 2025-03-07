#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "mcp[cli]",
#   "pygments",
# ]
# ///
"""
MCP server that forwards to a Basilisp nREPL server
"""

import argparse
import json
import re
import socket
import typing
from datetime import datetime
from pygments import highlight
from pygments.lexers import ClojureLexer
from pygments.formatters import TerminalFormatter
from mcp.server.fastmcp import FastMCP, Context

# Parse command line arguments
parser = argparse.ArgumentParser(description='MCP server that forwards to a Basilisp nREPL server')
parser.add_argument('--nrepl-port', type=int, default=36915, help='nREPL server port (default: 36915)')
parser.add_argument('--host', type=str, default='127.0.0.1', help='nREPL server host (default: 127.0.0.1)')

args = parser.parse_args()

# Create server
mcp = FastMCP("Basilisp nREPL Bridge")

# Simple bencode implementation for nREPL communication
def bencode_encode(data: dict) -> bytes:
    """Simple implementation to encode dictionaries to bencode format."""
    result = "d"
    for k, v in data.items():
        result += str(len(str(k))) + ":" + str(k)
        if isinstance(v, str):
            result += str(len(v)) + ":" + v
        elif isinstance(v, int):
            result += f"i{v}e"
        elif isinstance(v, bool):
            result += f"i{1 if v else 0}e"
        elif isinstance(v, list):
            result += "l" + bencode_encode_list(v) + "e"
    result += "e"
    return result.encode()

def bencode_encode_list(data: list) -> str:
    """Helper function to encode lists in bencode format."""
    result = ""
    for item in data:
        if isinstance(item, str):
            result += str(len(item)) + ":" + item
        elif isinstance(item, int):
            result += f"i{item}e"
        elif isinstance(item, bool):
            result += f"i{1 if item else 0}e"
    return result

def parse_bencode_response(data: bytes) -> dict:
    """Parse bencode response to extract specific fields."""
    result = {}
    
    # Extract new-session
    session_match = re.search(br"11:new-session(\d+):", data)
    if session_match:
        length = int(session_match.group(1))
        pos = session_match.end()
        session_id = data[pos:pos+length].decode()
        result["new-session"] = session_id
    
    # Extract value
    value_match = re.search(br"5:value(\d+):", data)
    if value_match:
        length = int(value_match.group(1))
        pos = value_match.end()
        value = data[pos:pos+length].decode()
        result["value"] = value
    
    # Check for done status
    if re.search(br"6:status.*4:done", data):
        result["status"] = ["done"]
    
    # Extract error
    err_match = re.search(br"3:err(\d+):", data)
    if err_match:
        length = int(err_match.group(1))
        pos = err_match.end()
        err = data[pos:pos+length].decode()
        result["err"] = err
    
    # Extract root-ex
    ex_match = re.search(br"7:root-ex(\d+):", data)
    if ex_match:
        length = int(ex_match.group(1))
        pos = ex_match.end()
        root_ex = data[pos:pos+length].decode()
        result["root-ex"] = root_ex
    
    return result

def make_session_request() -> bytes:
    """Create a bencode request to create a new nREPL session."""
    return bencode_encode({
        "op": "clone",
        "verbose": 1,
        "prompt": 1
    })

def make_eval_request(code: str, session_id: str) -> bytes:
    """Create a bencode request to evaluate code in nREPL."""
    return bencode_encode({
        "op": "eval",
        "code": code,
        "session": session_id
    })

def send_to_nrepl(code: str, host: str = args.host, port: int = args.nrepl_port, timeout: int = 30) -> str:
    """Send code to nREPL and return the result.
    
    Args:
        code: Basilisp code to evaluate
        host: nREPL server host
        port: nREPL server port
        timeout: Socket operation timeout in seconds
        
    Returns:
        The evaluation result or error message
    """
    sock = None
    try:
        # Create socket with timeout
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        
        # Create a session
        sock.sendall(make_session_request())
        session_resp = bytes(sock.recv(4096))
        session_data = parse_bencode_response(session_resp)
        session_id = session_data.get("new-session")
        
        if not session_id:
            return "Error: Could not create nREPL session"
        
        # Evaluate code
        sock.sendall(make_eval_request(code, session_id))
        result = bytes()
        
        # Set a maximum number of read attempts
        max_reads = 100
        reads = 0
        
        while reads < max_reads:
            data = sock.recv(4096)
            if not data:
                break
            result += data
            reads += 1
            
            # Check if response is complete
            parsed = parse_bencode_response(result)
            if "status" in parsed and "done" in parsed["status"]:
                break
        
        # Extract value or error from response
        parsed_result = parse_bencode_response(result)
        
        # Check for errors
        if "err" in parsed_result:
            return f"Error: {parsed_result['err']}"
        if "root-ex" in parsed_result:
            return f"Exception: {parsed_result['root-ex']}"
        
        # Return the value or a default message
        return parsed_result.get("value", "No result")
    
    except socket.timeout:
        return "Error: nREPL connection timed out"
    except ConnectionRefusedError:
        return "Error: nREPL connection refused. Is the nREPL server running?"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        # Ensure socket is closed
        if sock:
            try:
                sock.close()
            except:
                pass

def pretty_print_result(result: str, ctx: Context) -> str:
    """Pretty-print the result of a Basilisp evaluation.
    
    Args:
        result: The raw result from nREPL
        ctx: The MCP context
        
    Returns:
        Formatted result string
    """
    # Handle errors with better formatting
    if result.startswith("Error:") or result.startswith("Exception:"):
        # Format traceback-like errors more cleanly
        if "Traceback" in result:
            lines = result.split('\n')
            formatted_lines = []
            for line in lines:
                # Keep only the most relevant parts of the traceback
                if any(x in line for x in ["File ", "Error:", "Exception:", "message:", "line ", "phase:"]):
                    formatted_lines.append(line)
            return "\n".join(formatted_lines)
        return result
    
    # For regular results, add syntax highlighting
    try:
        return highlight(result, ClojureLexer(), TerminalFormatter())
    except Exception as e:
        ctx.warning(f"Could not format result: {e}")
        return result

@mcp.tool()
def eval_code(code: str, ctx: Context) -> str:
    """Evaluate Basilisp code in nREPL.
    
    Args:
        code: Basilisp code to evaluate
        
    Returns:
        The evaluation result
    """
    ctx.info(f"Evaluating Basilisp code: {code}")
    result = send_to_nrepl(code)
    
    # Log result for debugging
    if result.startswith("Error:") or result.startswith("Exception:"):
        ctx.error(f"Evaluation error: {result}")
    else:
        ctx.info(f"Evaluation result: {result}")
    
    # Format the result for display
    return pretty_print_result(result, ctx)

@mcp.tool()
def execute_basilisp(code: str, ctx: Context) -> str:
    """Execute Basilisp code in nREPL (alias for eval_code).
    
    Args:
        code: Basilisp code to execute
        
    Returns:
        The execution result
    """
    return eval_code(code, ctx)

@mcp.tool()
def get_docs(symbol: str, ctx: Context) -> str:
    """Get documentation for a Basilisp symbol.
    
    Args:
        symbol: The Basilisp symbol to get documentation for
        
    Returns:
        The documentation string
    """
    code = f"(doc {symbol})"
    ctx.info(f"Getting documentation for: {symbol}")
    return eval_code(code, ctx)

@mcp.tool()
def find_namespace_vars(namespace: str, ctx: Context) -> str:
    """List all vars in a namespace.
    
    Args:
        namespace: The namespace to list vars from
        
    Returns:
        A list of vars in the namespace
    """
    code = f"""(let [ns-vars (->> (ns-publics '{namespace})
                               (sort-by key) 
                               (map (fn [[k v]] (str k))))
              ns-macros (->> (ns-interns '{namespace})
                            (filter (fn [[k v]] (:macro (meta v))))
                            (sort-by key)
                            (map (fn [[k v]] (str k " [macro]"))))]
          (str "Variables in namespace {namespace}:\\n"
               (str/join "\\n" ns-vars)
               "\\n\\nMacros in namespace {namespace}:\\n"
               (str/join "\\n" ns-macros)))"""
    ctx.info(f"Listing vars in namespace: {namespace}")
    return eval_code(code, ctx)

@mcp.tool()
def list_namespaces(ctx: Context) -> str:
    """List all available namespaces.
    
    Returns:
        A list of available namespaces
    """
    code = """(str/join "\n" (sort (map str (all-ns))))"""
    ctx.info("Listing all namespaces")
    return eval_code(code, ctx)

@mcp.tool()
def check_connection(ctx: Context) -> str:
    """Check if the nREPL server is running and responding.
    
    Returns:
        Connection status
    """
    try:
        result = send_to_nrepl("(+ 1 1)")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if result == "2":
            return f"✅ Connection successful at {timestamp}"
        else:
            return f"⚠️ Connection issue at {timestamp}. Server responded but with unexpected result: {result}"
    except Exception as e:
        return f"❌ Connection failed at {timestamp}: {str(e)}"

@mcp.prompt("basilisp-repl")
def basilisp_repl_prompt() -> str:
    """Prompt for interacting with Basilisp REPL."""
    return """
You are now connected to a Basilisp REPL. Basilisp is a Lisp dialect similar to Clojure, but running on the Python VM.

## Available Tools

You have several tools available to interact with the Basilisp REPL:

1. `eval_code(code)` - Evaluate Basilisp code and return the result
2. `execute_basilisp(code)` - Alias for eval_code
3. `get_docs(symbol)` - Get documentation for a Basilisp symbol
4. `find_namespace_vars(namespace)` - List all vars in a given namespace
5. `list_namespaces()` - List all available namespaces
6. `check_connection()` - Check if the nREPL server is running and responding

## Basilisp Help Guide

Basilisp is largely compatible with Clojure, with some differences:

### Basic Operations
- Arithmetic: `(+ 1 2)`, `(- 10 5)`, `(* 3 4)`, `(/ 10 2)`
- Comparisons: `(= 1 1)`, `(< 5 10)`, `(> 7 2)`
- Logic: `(and true false)`, `(or false true)`, `(not true)`

### Variables and Functions
- Define a variable: `(def x 10)`
- Define a function: `(defn add [a b] (+ a b))`
- Anonymous function: `(fn [x] (* x x))` or `#(* % %)`

### Data Structures
- Lists: `(list 1 2 3)` or `'(1 2 3)`
- Vectors: `[1 2 3]`
- Maps: `{"a" 1, "b" 2}` or `{:a 1, :b 2}`
- Sets: `#{1 2 3}`

### Python Interop
- Import a module: `(import math)`
- Import with alias: `(import [math :as m])`
- Call a function: `(math/sqrt 16)`
- Access attributes: `(. math -pi)` or `(.-pi math)`
- Call methods: `(. obj method args)` or `(.method obj args)`
- Create Python objects: `#py{:a 1 :b 2}`

### Special Features
- Threading macros: 
  - Thread-first: `(-> x (f) (g) (h))` - inserts x as first arg
  - Thread-last: `(->> x (f) (g) (h))` - inserts x as last arg
- Destructuring: `(let [[a b] [1 2]] (+ a b))`

## Examples

```clojure
;; Define a function
(defn fibonacci [n]
  (loop [a 0 b 1 i 0]
    (if (= i n)
      a
      (recur b (+ a b) (inc i)))))

;; Map it over a sequence
(map fibonacci (range 10))
;; => (0 1 1 2 3 5 8 13 21 34)

;; Use Python interop
(import [datetime :as dt])
(def now (dt/datetime.now))
(str "Current hour: " (.-hour now))
```

If you need help with Basilisp syntax or functionality, you can use the documentation tools or try examples.
"""

@mcp.prompt("basilisp-help")
def basilisp_help_prompt() -> str:
    """Prompt with helpful information about Basilisp."""
    return """
# Basilisp Help Guide

Basilisp is a Lisp dialect similar to Clojure, but running on the Python VM.

## Available Tools

You have several tools to interact with the Basilisp REPL:

1. `eval_code(code)` - Evaluate Basilisp code and return the result
2. `execute_basilisp(code)` - Alias for eval_code
3. `get_docs(symbol)` - Get documentation for a Basilisp symbol
4. `find_namespace_vars(namespace)` - List all vars in a namespace
5. `list_namespaces()` - List all available namespaces
6. `check_connection()` - Check if the nREPL server is running

## Core Concepts

### Basic Operations
- Arithmetic: `(+ 1 2)`, `(- 10 5)`, `(* 3 4)`, `(/ 10 2)`
- Comparisons: `(= 1 1)`, `(< 5 10)`, `(> 7 2)`
- Logic: `(and true false)`, `(or false true)`, `(not true)`

### Variables and Functions
- Define a variable: `(def x 10)`
- Define a function: `(defn add [a b] (+ a b))`
- Anonymous function: `(fn [x] (* x x))` or `#(* % %)`
- Multiarity functions:
```clojure
(defn greet
  ([] (greet "World"))
  ([name] (str "Hello, " name "!")))
```

### Data Structures
- Lists: `(list 1 2 3)` or `'(1 2 3)`
- Vectors: `[1 2 3]`
- Maps: `{"a" 1, "b" 2}` or `{:a 1, :b 2}`
- Sets: `#{1 2 3}`
- Support for transient and volatile collections

### Python Interop
- Import a module: `(import math)`
- Import with alias: `(import [math :as m])`
- Call a function: `(math/sqrt 16)`
- Access attributes: `(. math -pi)` or `(.-pi math)`
- Call methods: `(. obj method args)` or `(.method obj args)`
- Create Python objects: `#py{:a 1 :b 2}`
- Decorators: `(defn f {:decorators [decorator/here]} [x] ...)`

### Special Features
- Threading macros: 
  - Thread-first: `(-> x (f) (g) (h))` - inserts x as first argument
  - Thread-last: `(->> x (f) (g) (h))` - inserts x as last argument
- Destructuring: `(let [[a b] [1 2], {:keys [c d]} {:c 3, :d 4}] (+ a b c d))`
- Dynamic variables: `(def ^:dynamic *db* nil)`
- Namespaces: `(ns my.project.core (:require [some.lib :as lib]))`

## Common Functions

### Sequence Operations
- `map`, `filter`, `reduce`, `take`, `drop`, `first`, `rest`
- `cons`, `conj`, `concat`, `into`, `partition`

### Collection Operations
- `get`, `assoc`, `dissoc`, `contains?`, `keys`, `vals`
- `update`, `merge`, `select-keys`

### Flow Control
- `if`, `when`, `cond`, `case`, `condp`
- `loop`, `recur`, `for`, `doseq`, `dotimes`
- `try`, `catch`, `finally`, `throw`

## Resources
- For more details on any function, use `(get_docs function-name)`
- To see all functions in a namespace, use `(find_namespace_vars namespace-name)`
- To list all namespaces, use `(list_namespaces)`
"""

async def run():
    return await mcp.run_stdio_async()

# Run the server
if __name__ == "__main__":
    print(f"Starting MCP server, forwarding to nREPL at {args.host}:{args.nrepl_port}")
    try:
        import asyncio
        asyncio.run(run())
    except Exception as e:
        print(f"Error running MCP server: {str(e)}")
        import traceback
        traceback.print_exc()
