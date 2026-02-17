import os
import sys
import json
import copy
from config import CONFIG_FILE, DEFAULT_CONFIG, _merge_emby_settings
from emby_users.api_client import _fetch_emby_users_list

# Mock load_config
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return copy.deepcopy(DEFAULT_CONFIG), True
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
        
        # Merge Emby settings
        emby_settings = data.get("EMBY")
        data["EMBY"] = _merge_emby_settings(emby_settings)
        return data, True
    except Exception as e:
        print(f"Error loading config: {e}")
        return copy.deepcopy(DEFAULT_CONFIG), False

# Load config
config, _ = load_config()
servers = config.get("EMBY", {}).get("SERVERS", [])

if not servers:
    print("No servers found")
    sys.exit(1)

server = servers[0]
print(f"Fetching users from {server['name']}...")

users, error = _fetch_emby_users_list(server)
if error:
    print(f"Error: {error}")
    sys.exit(1)

admins = [u for u in users if u.get("Policy", {}).get("IsAdministrator")]

print(f"Found {len(admins)} admins.")
for u in admins:
    print("-" * 20)
    print(f"Name: {u.get('Name')}")
    # Print keys to keep output manageable but informative
    print(json.dumps(u, indent=2))
