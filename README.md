# WSL to GitHub Sync Utility

This Python utility automates the process of syncing multiple local directories inside WSL (Ubuntu) to your corporate GitHub account as separate private repositories, without needing the GitHub CLI (`gh`).

---

## Features

- **Automated Repository Creation**: Checks if the target repository exists on corporate GitHub. If not, it automatically creates it as a **private** repository via the API.
- **Git Sync Automation**: Initializes a local git repository, configures the origin remote URL using secure credentials, stages files, commits changes, and pushes to `main`.
- **Zero External Dependencies Fallback**: The script includes a built-in YAML parser. If the standard `PyYAML` package isn't installed in WSL, the script fallback-parses the configuration automatically so you can run it out of the box.
- **Corporate Proxy & SSL bypass**: If your corporate PC decrypts traffic causing SSL errors, you can disable SSL certificate checking for both the API requests and Git commands with a simple config setting (`ssl_verify: false`).

---

## Setup & Configuration

### 1. Generate a GitHub Personal Access Token (PAT)
1. Go to your corporate GitHub account: `https://github.axa.com/settings/tokens`.
2. Click **Generate new token (classic)**.
3. Give it a descriptive name (e.g. `wsl-migration-token`).
4. Select the **`repo`** scope (this is required to check, create, and push to repositories).
5. Copy the generated token immediately. **Do not close the page until you copy it!**

### 2. Configure the Sync List
In your WSL terminal:
1. Copy the example configuration to create your active configuration file:
   ```bash
   cp sync_config.example.yaml sync_config.yaml
   ```
2. Open `sync_config.yaml` in your favorite editor (e.g., `nano sync_config.yaml` or VS Code) and customize it:
   ```yaml
   github_url: "https://github.axa.com"
   github_username: "victor-ruiz"
   
   # Leave this empty if you prefer setting it in your shell environment
   github_pat: ""
   
   # Set to false if you experience corporate proxy certificate errors
   ssl_verify: true

   folders:
     - path: "/home/victor/scripts/db-utils"
       description: "Database scripts and query helpers"
     - path: "/home/victor/automation/reporting"
       repo_name: "axa-report-builder" # Override repo name on GitHub
     - path: "/home/victor/code/test-suite"
   ```

> [!NOTE]
> `sync_config.yaml` is pre-configured in `.gitignore` to prevent you from accidentally committing your secret tokens or local folder paths to Git.

---

## How to Run

1. Expose your Personal Access Token in your WSL terminal session:
   ```bash
   export GITHUB_PAT="your_token_here"
   ```
   *(Alternatively, you can paste the PAT directly inside the `github_pat: "..."` field of `sync_config.yaml`)*

2. Run the script:
   ```bash
   python3 sync_git.py
   ```

---

## Troubleshooting

### 1. Missing `yaml` Library
If the script prints: `PyYAML module not found. Using built-in simple YAML parser.`
- **Don't worry!** The script continues running using its built-in fallback parser.
- If you'd prefer to use the standard YAML library, you can install it easily in WSL:
  ```bash
  sudo apt update && sudo apt install -y python3-yaml
  # Or
  pip install pyyaml
  ```

### 2. SSL / Certificate Verification Failures
In corporate environments, network traffic is often intercepted and re-signed by corporate firewalls, causing SSL connection errors like `certificate verify failed`.
- **Solution**: Open `sync_config.yaml` and set `ssl_verify: false`. The script will bypass certificate checks for the API calls and configure Git locally for each synced repo to ignore SSL validation (`git config http.sslVerify false`).

### 3. Permission Denied (401 / 403 / 404)
If you get errors creating or pushing to repositories:
- Make sure your PAT is copied correctly and has not expired.
- Check that the PAT has the `repo` checkbox enabled.
- Verify your username matches `victor-ruiz` exactly.

---

## Security Warning
This utility uses HTTPS with PAT embedded in the remote URL (e.g., `https://username:token@github.axa.com/...`). This means Git stores the token in plaintext inside the `.git/config` file of each synced folder.
- **Recommendation**: Once you have completed migrating your PC and verified all repositories are safely on GitHub, **revoke the PAT** in your GitHub Settings. This instantly invalidates the token stored in all `.git/config` files, ensuring no one can reuse them.
