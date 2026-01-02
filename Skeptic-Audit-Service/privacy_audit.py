import os
import sys
import re

def run_audit():
    violators = []
    # PII Patterns: Looking for potential SSNs, Phone Numbers, or forbidden keywords
    pii_keywords = ["SocialSecurity", "SSN", "BirthDate", "PhoneNumber", "PatientName"]
    phone_pattern = r'\d{3}-\d{3}-\d{4}' # Simple pattern for 000-000-0000

    search_path = "."
    ignore_folder = ".git"

    for root, dirs, files in os.walk(search_path):
        if ignore_folder in root:
            continue
            
        for file in files:
            if file.endswith(".cs") or file.endswith(".txt"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                    # RULE 1: Clinical Resonance requires Encryption
                    if "Resonance" in content and "IsEncrypted" not in content:
                        violators.append(f"{file} (Missing Encryption)")
                    
                    # RULE 2: No Hardcoded PII
                    for word in pii_keywords:
                        if word in content:
                            violators.append(f"{file} (Contains PII Keyword: {word})")
                    
                    if re.search(phone_pattern, content):
                        violators.append(f"{file} (Contains Phone Number Pattern)")

    if not violators:
        print("✅ PASS: Lab is clean of PII and Encryption breaches.")
        sys.exit(0)
    else:
        print(f"❌ FAIL: Sovereignty Breach! Issues found in: {violators}")
        sys.exit(1)

if __name__ == "__main__":
    run_audit()
