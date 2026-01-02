import os
import sys

def run_audit():
    violators = []
    # UPGRADE: Scan the entire project directory
    search_path = "." 
    
    # We want to ignore the hidden .git folder
    ignore_folder = ".git"

    for root, dirs, files in os.walk(search_path):
        if ignore_folder in root:
            continue
            
        for file in files:
            if file.endswith(".cs"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    content = f.read()
                    # THE SOVEREIGN RULE: If it handles Resonance, it MUST have Encryption
                    if "Resonance" in content and "IsEncrypted" not in content:
                        violators.append(file)
    
    if not violators:
        print("✅ PASS: All sensitive contracts include an Encryption check.")
        sys.exit(0)
    else:
        print(f"❌ FAIL: Security breach detected! The following files lack encryption protocols: {violators}")
        sys.exit(1)

if __name__ == "__main__":
    run_audit()
