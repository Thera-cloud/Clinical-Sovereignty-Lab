import json, os

paths = ["/app/data/user_registry.json", "data/user_registry.json"]
for p in paths:
    if os.path.exists(p):
        with open(p) as f:
            r = json.load(f)
        for k, v in r.items():
            pr = v.get("profile", {}) if isinstance(v, dict) else {}
            nm = pr.get("name", "") or k
            if "Tester123" in nm or "tester123" in nm.lower():
                pr["onboarding_completed"] = False
                with open(p, "w") as f:
                    json.dump(r, f, indent=2)
                print("Reset " + nm + " onboarding to False")
                break
        else:
            print("User Tester123 not found. Users:")
            for k, v in r.items():
                pr = v.get("profile", {}) if isinstance(v, dict) else {}
                name = pr.get("name", "?")
                print("  " + k + ": " + str(name))
        break
else:
    print("Registry file not found")
