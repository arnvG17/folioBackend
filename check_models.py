import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ No GOOGLE_API_KEY found.")
    exit(1)

genai.configure(api_key=api_key)

try:
    print("Listing available embedding models for your API Key...")
    models = [m for m in genai.list_models() if 'embedContent' in m.supported_generation_methods]
    for m in models:
        print(f"✅ Model found: {m.name}")
except Exception as e:
    print(f"❌ Error: {e}")
