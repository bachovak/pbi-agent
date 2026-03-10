import json

with open("measure_library.json", "r") as f:
    data = json.load(f)

for m in data:
    print(f"ID {m['id']}: {m['request']}")