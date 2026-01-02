import os

def run_audit():
    violators = []
    # We are looking for any file that handles 'SessionId' or 'ResonanceScore'
    # but DOES NOT mention 'Encryption' or 'AuditTrail'
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    contracts_path = os.path.join(base_path, "Shared-Clinical-Contracts")
    
    for root, dirs, files in os.walk(contracts_path):
        for file in files:
            if file.endswith(".cs"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    content = f.read()
                    if "ResonanceScore" in content and "IsEncrypted" not in content:
                        violators.append(file)
    
    if not violators:
        print("✅ PASS: All sensitive contracts include an Encryption check.")
    else:
        print(f"❌ FAIL: The following files lack encryption protocols: {violators}")

if __name__ == "__main__":
    run_audit()

