import json
from werkzeug.security import generate_password_hash

PATH = "data/users.json"
USERNAME = "requester1"
NEW_PASSWORD = "Req2026!"

with open(PATH, encoding="utf-8") as f:
    users = json.load(f)

found = False
for u in users:
    if u.get("username") == USERNAME:
        u["password_hash"] = generate_password_hash(NEW_PASSWORD)
        found = True
        print(f"Updated {USERNAME} password to {NEW_PASSWORD!r}")
        break

if not found:
    print(f"User {USERNAME!r} not found.")

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(users, f, ensure_ascii=False, indent=2)

print("Done.")