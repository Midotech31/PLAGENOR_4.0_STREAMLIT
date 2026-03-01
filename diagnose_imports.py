import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def t(label):
    print(f"[{time.time():.3f}] {label}", flush=True)

t("START")
import config
t("config OK")

from core.repository import ensure_data_directory
t("ensure_data_directory imported")
ensure_data_directory()
t("ensure_data_directory() done")

from core.repository import get_all_users, save_user
t("user repo imported")
users = get_all_users()
t(f"get_all_users() done — {len(users)} users")

from services.storage import read_json, write_json
t("storage imported")

# Show full storage.py
print("\n=== services/storage.py ===")
with open(os.path.join("services","storage.py"), encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        print(f"{i}: {line.rstrip()}")

# Show repository.py save_user and ensure_data_directory
print("\n=== core/repository.py (first 80 lines) ===")
with open(os.path.join("core","repository.py"), encoding="utf-8") as f:
    lines = f.readlines()
for i in range(min(80, len(lines))):
    print(f"{i+1}: {lines[i].rstrip()}")