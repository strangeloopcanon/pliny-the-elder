#!/usr/bin/env python3
"""
Test script to verify VEI setup is working correctly
"""

import os
import sys
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check_mark(passed):
    return f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"

def test_environment():
    """Test environment setup"""
    print(f"\n{BLUE}=== Testing VEI Environment Setup ==={RESET}\n")
    
    all_passed = True
    
    # 1. Check Python version
    python_version = sys.version_info
    python_ok = python_version >= (3, 11)
    print(f"{check_mark(python_ok)} Python version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    if not python_ok:
        print(f"  {YELLOW}Warning: Python 3.11+ recommended{RESET}")
    
    # 2. Check .env file
    env_file = Path(".env")
    env_exists = env_file.exists()
    print(f"{check_mark(env_exists)} .env file exists: {env_exists}")
    
    # 3. Check API key
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    api_key = os.getenv("OPENAI_API_KEY")
    api_key_set = api_key and api_key != "your_api_key_here"
    print(f"{check_mark(api_key_set)} OPENAI_API_KEY: {'Set' if api_key_set else 'Not set or placeholder'}")
    if not api_key_set:
        print(f"  {RED}Error: Please set your actual API key in .env file{RESET}")
        all_passed = False
    
    # 4. Check required packages
    packages = {
        "mcp": "MCP (Model Context Protocol)",
        "openai": "OpenAI SDK",
        "pydantic": "Pydantic",
        "typer": "Typer CLI",
        "rich": "Rich console",
        "dotenv": "Python-dotenv"
    }
    
    print(f"\n{BLUE}Required packages:{RESET}")
    for package, name in packages.items():
        try:
            if package == "dotenv":
                import dotenv
            else:
                __import__(package)
            print(f"{check_mark(True)} {name}")
        except ImportError:
            print(f"{check_mark(False)} {name} - Not installed")
            all_passed = False
    
    # 5. Check optional packages
    optional_packages = {
        "playwright": "Playwright (browser automation)",
        "agents": "OpenAI Agents SDK"
    }
    
    print(f"\n{BLUE}Optional packages:{RESET}")
    for package, name in optional_packages.items():
        try:
            __import__(package)
            print(f"{check_mark(True)} {name}")
        except ImportError:
            print(f"{check_mark(False)} {name} - Not installed (optional)")
    
    # 6. Check VEI installation
    try:
        import vei
        print(f"\n{check_mark(True)} VEI package installed")
        
        # Check VEI CLI tools
        from vei.cli import vei_demo, vei_chat, vei_llm_test
        print(f"{check_mark(True)} VEI CLI tools available")
    except ImportError as e:
        print(f"\n{check_mark(False)} VEI package not properly installed: {e}")
        all_passed = False
    
    # 7. Check directories
    print(f"\n{BLUE}Directory structure:{RESET}")
    dirs = [
        "_vei_out",
        "vei",
        "examples",
        "tests"
    ]
    for dir_name in dirs:
        dir_exists = Path(dir_name).exists()
        print(f"{check_mark(dir_exists)} {dir_name}/")
    
    # 8. Test SSE server availability
    print(f"\n{BLUE}Testing SSE server:{RESET}")
    import socket
    
    def check_port(host="127.0.0.1", port=3001):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                return s.connect_ex((host, port)) == 0
            except:
                return False
    
    server_running = check_port()
    print(f"{check_mark(server_running)} SSE server on port 3001: {'Running' if server_running else 'Not running (will auto-start)'}")
    
    # Summary
    print(f"\n{BLUE}{'='*50}{RESET}")
    if all_passed:
        print(f"{GREEN}✓ All critical checks passed!{RESET}")
        print(f"\nYou can now run:")
        print(f"  {BLUE}python run_vei_gpt5_demo.py{RESET}")
        print(f"  {BLUE}vei-demo --mode llm --model gpt-5{RESET}")
        print(f"  {BLUE}vei-chat --model gpt-5{RESET}")
    else:
        print(f"{RED}✗ Some checks failed. Please fix the issues above.{RESET}")
        if not api_key_set:
            print(f"\n{YELLOW}Most importantly, set your OPENAI_API_KEY in the .env file{RESET}")
    
    return all_passed

if __name__ == "__main__":
    success = test_environment()
    sys.exit(0 if success else 1)
