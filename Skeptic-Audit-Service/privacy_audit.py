import os
import sys

def run_audit():
    violators = []
    # Check the contracts folder for the encryption requirement
    contracts_path = "./Shared-Clinical-Contracts"
    
    if not os.path.exists(contracts_path):
        print(f"⚠️ Warning: {contracts_path} not found.")
        return

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
        sys.exit(0)
    else:
        print(f"❌ FAIL: The following files lack encryption protocols: {violators}")
        sys.exit(1) # This forces the 'Stop'

if __name__ == "__main__":
    run_audit()
