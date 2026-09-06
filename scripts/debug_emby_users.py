import sys
import json
from core.config_manager import load_config
from emby_users.api_client import _fetch_emby_users_list

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
