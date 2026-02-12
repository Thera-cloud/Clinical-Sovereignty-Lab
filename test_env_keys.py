import os
from dotenv import load_dotenv
load_dotenv()

print("\n🔐 KEY VALIDATOR\n")

# Stripe
key = os.getenv("STRIPE_SECRET_KEY", "")
if key.startswith("sk_"):
    print(f"✅ Stripe: ...{key[-4:]}")
else:
    print("❌ Stripe: Not found or invalid")

# SendGrid
key = os.getenv("SENDGRID_API_KEY", "")
if key.startswith("SG."):
    print(f"✅ SendGrid: ...{key[-4:]}")
else:
    print("⚠️  SendGrid: Not found (optional)")

# Azure
key = os.getenv("AZURE_API_KEY", "")
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
if key and endpoint:
    print(f"✅ Azure: ...{key[-4:]}")
else:
    print("❌ Azure: Missing key or endpoint")

print("\n✅ Done!\n")
