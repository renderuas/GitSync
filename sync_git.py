#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import ssl
from datetime import datetime

# ANSI Color codes for styled console output
class Color:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def log_info(msg):
    print(f"{Color.CYAN}[INFO]{Color.RESET} {msg}")

def log_success(msg):
    print(f"{Color.GREEN}[SUCCESS]{Color.RESET} {msg}")

def log_warn(msg):
    print(f"{Color.YELLOW}[WARNING]{Color.RESET} {msg}")

def log_error(msg):
    print(f"{Color.RED}[ERROR]{Color.RESET} {msg}", file=sys.stderr)

# Fallback YAML parser to allow running without PyYAML installed
def parse_simple_yaml(content):
    data = {
        "github_url": "https://github.com",
        "github_username": "",
        "github_pat": "",
        "ssl_verify": True,
        "folders": []
    }
    
    lines = content.splitlines()
    current_folder = None
    
    for line in lines:
        # Strip comments and whitespace
        line = line.split('#')[0].strip()
        if not line:
            continue
        
        # Check for list items
        if line.startswith("-"):
            item_content = line[1:].strip()
            if item_content.startswith("path:"):
                val = item_content.split("path:", 1)[1].strip().strip('"\'')
                current_folder = {"path": val}
                data["folders"].append(current_folder)
            continue
            
        # Check for keys
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"\'')
            
            if key in ("github_url", "github_username", "github_pat"):
                data[key] = val
            elif key == "ssl_verify":
                data[key] = val.lower() in ("true", "yes", "1")
            elif key in ("path", "repo_name", "description", "private"):
                if current_folder is not None:
                    if key == "private":
                        current_folder[key] = val.lower() in ("true", "yes", "1")
                    else:
                        current_folder[key] = val
                
    return data

def load_config(config_path="sync_config.yaml"):
    if not os.path.exists(config_path):
        log_error(f"Configuration file not found: {config_path}")
        log_info("Please copy sync_config.example.yaml to sync_config.yaml and configure it.")
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Attempt to use PyYAML, fall back to simple parser if not installed
    try:
        import yaml
        config_data = yaml.safe_load(content)
        # Ensure default values are populated
        if "github_url" not in config_data:
            config_data["github_url"] = "https://github.com"
        if "ssl_verify" not in config_data:
            config_data["ssl_verify"] = True
        if "folders" not in config_data or not config_data["folders"]:
            config_data["folders"] = []
    except ImportError:
        log_info("PyYAML module not found. Using built-in simple YAML parser.")
        config_data = parse_simple_yaml(content)
        
    # Resolve PAT (Env variable GITHUB_PAT takes precedence)
    pat = os.environ.get("GITHUB_PAT")
    if pat:
        config_data["github_pat"] = pat
        
    return config_data

def get_api_base_url(github_url):
    github_url = github_url.rstrip("/")
    if "github.com" in github_url:
        return "https://api.github.com"
    else:
        # GitHub Enterprise Server API base URL
        return f"{github_url}/api/v3"

def get_ssl_context(verify=True):
    if not verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None

def check_repo_exists(api_base, username, repo_name, pat, ssl_context):
    url = f"{api_base}/repos/{username}/{repo_name}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {pat}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            if response.status == 200:
                return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        else:
            log_warn(f"API returned status {e.code} while checking repository '{repo_name}' existence.")
            # We will assume it might not exist or we can't access it, let's try creating it anyway
            return False
    except Exception as e:
        log_warn(f"Failed to check repository existence via API: {e}")
        return False
    return False

def create_repo(api_base, repo_name, description, is_private, pat, ssl_context):
    url = f"{api_base}/user/repos"
    data = {
        "name": repo_name,
        "private": is_private
    }
    if description:
        data["description"] = description
        
    json_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=json_data, method="POST")
    req.add_header("Authorization", f"token {pat}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            if response.status in (200, 201):
                return True
    except urllib.error.HTTPError as e:
        log_error(f"Failed to create repository '{repo_name}'. API response: {e.code} {e.reason}")
        try:
            error_detail = e.read().decode('utf-8')
            log_error(f"Details: {error_detail}")
        except Exception:
            pass
        return False
    except Exception as e:
        log_error(f"Error during repository creation request: {e}")
        return False
    return False

def run_git(args, cwd):
    # Run a git command and return result
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return res

def sync_directory(folder_info, config_data, ssl_context):
    path = folder_info.get("path")
    if not path:
        log_error("Skipping folder config: missing 'path' property.")
        return False
        
    # Expand user directory (~/...)
    path = os.path.expanduser(path)
    
    if not os.path.isdir(path):
        log_error(f"Directory does not exist: {path}")
        return False
        
    # Determine repo name
    repo_name = folder_info.get("repo_name")
    if not repo_name:
        repo_name = os.path.basename(os.path.normpath(path))
        
    description = folder_info.get("description", "Automated WSL backup")
    is_private = folder_info.get("private", True)
    
    username = config_data["github_username"]
    pat = config_data["github_pat"]
    github_url = config_data["github_url"]
    ssl_verify = config_data["ssl_verify"]
    
    # Parse domain host (e.g. github.axa.com)
    parsed_url = urllib.parse.urlparse(github_url)
    github_host = parsed_url.netloc
    
    print(f"\n{Color.BOLD}=== Syncing: {path} -> {username}/{repo_name} ==={Color.RESET}")
    
    # 1. API Check and Creation
    api_base = get_api_base_url(github_url)
    log_info(f"Checking if repository '{username}/{repo_name}' exists on GitHub...")
    exists = check_repo_exists(api_base, username, repo_name, pat, ssl_context)
    
    if not exists:
        log_info(f"Repository does not exist. Creating private repo '{repo_name}'...")
        created = create_repo(api_base, repo_name, description, is_private, pat, ssl_context)
        if not created:
            log_error(f"Aborting sync for {path}: could not create remote repository.")
            return False
        log_success("Remote repository created successfully.")
    else:
        log_info("Repository already exists on GitHub.")
        
    # 2. Git operations
    # Check if .git folder exists
    git_dir = os.path.join(path, ".git")
    if not os.path.isdir(git_dir):
        log_info("Initializing new git repository...")
        res = run_git(["git", "init"], path)
        if res.returncode != 0:
            log_error(f"Failed to initialize git: {res.stderr}")
            return False
            
    # Set SSL verification locally if requested
    if not ssl_verify:
        run_git(["git", "config", "http.sslVerify", "false"], path)
        
    # Setup authenticated remote URL
    # URL encode PAT to ensure safety with special characters
    encoded_pat = urllib.parse.quote(pat)
    remote_url = f"https://{username}:{encoded_pat}@{github_host}/{username}/{repo_name}.git"
    
    # Check existing remote
    res = run_git(["git", "remote", "get-url", "origin"], path)
    if res.returncode == 0:
        log_info("Updating existing 'origin' remote URL...")
        run_git(["git", "remote", "set-url", "origin", remote_url], path)
    else:
        log_info("Adding 'origin' remote URL...")
        run_git(["git", "remote", "add", "origin", remote_url], path)
        
    # Add files
    log_info("Staging files...")
    run_git(["git", "add", "."], path)
    
    # Check if there are commits yet
    commit_needed = False
    res_head = run_git(["git", "rev-parse", "--verify", "HEAD"], path)
    if res_head.returncode != 0:
        # No commits exist yet in this repository
        commit_needed = True
        log_info("First commit in this repository...")
    else:
        # Check if there are changes to commit
        res_status = run_git(["git", "status", "--porcelain"], path)
        if res_status.stdout.strip():
            commit_needed = True
            log_info("Local modifications detected, preparing commit...")
            
    if commit_needed:
        # Verify if we actually have anything staged (to avoid error if empty folder)
        res_staged = run_git(["git", "diff", "--cached", "--name-only"], path)
        if not res_staged.stdout.strip():
            log_warn("No files staged to commit (folder might be empty or all files ignored). Skipping push.")
            return True
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-backup sync: {timestamp}"
        res_commit = run_git(["git", "commit", "-m", commit_msg], path)
        if res_commit.returncode != 0:
            log_error(f"Commit failed: {res_commit.stderr}")
            return False
        log_success("Committed changes.")
    else:
        log_info("No local changes to commit.")
        
    # Ensure branch is main
    run_git(["git", "branch", "-M", "main"], path)
    
    # Push
    log_info("Pushing to GitHub...")
    res_push = run_git(["git", "push", "-u", "origin", "main"], path)
    if res_push.returncode != 0:
        log_error(f"Push failed: {res_push.stderr}")
        log_info("Double check your PAT permissions (must have 'repo' scope).")
        return False
        
    log_success(f"Directory {path} synced successfully!")
    return True

def main():
    print(f"{Color.BOLD}==========================================")
    print("      WSL to GitHub Sync Utility")
    print(f"=========================================={Color.RESET}")
    
    # 1. Load config
    config = load_config()
    
    if not config["github_username"]:
        log_error("Missing 'github_username' in configuration.")
        sys.exit(1)
    if not config["github_pat"]:
        log_error("Missing 'github_pat' in configuration. Please define GITHUB_PAT env variable or set it in sync_config.yaml.")
        sys.exit(1)
        
    # 2. Check if git is installed
    try:
        res = subprocess.run(["git", "--version"], capture_output=True, text=True)
        if res.returncode != 0:
            raise FileNotFoundError()
    except FileNotFoundError:
        log_error("Git is not installed or not in PATH inside WSL. Please install git ('sudo apt install git') and try again.")
        sys.exit(1)
        
    # 3. Process folders
    folders = config["folders"]
    if not folders:
        log_warn("No folders configured to sync in sync_config.yaml.")
        sys.exit(0)
        
    ssl_context = get_ssl_context(config["ssl_verify"])
    
    success_count = 0
    fail_count = 0
    
    for folder in folders:
        try:
            success = sync_directory(folder, config, ssl_context)
            if success:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            log_error(f"Unexpected error syncing folder {folder.get('path')}: {e}")
            fail_count += 1
            
    # Summary
    print(f"\n{Color.BOLD}==========================================")
    print("             Sync Summary")
    print(f"=========================================={Color.RESET}")
    print(f"Total directories processed: {len(folders)}")
    print(f"Successful syncs:           {Color.GREEN}{success_count}{Color.RESET}")
    print(f"Failed syncs:               {Color.RED if fail_count > 0 else Color.GREEN}{fail_count}{Color.RESET}")
    print(f"{Color.BOLD}=========================================={Color.RESET}")
    
    # Info about credentials security
    log_warn("Note: Credentials (PAT) are stored in your local .git/config files via the remote URLs.")
    log_warn("Ensure your WSL environment remains secure. If needed, revoke this PAT after migration.")
    
    if fail_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
