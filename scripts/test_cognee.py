"""
Quick sanity test for Cognee Cloud API.
Run this to make sure your API key and Tenant URL are correct.
"""
import os
import sys
import requests
from dotenv import load_dotenv

def main():
    load_dotenv()
    api_key = os.environ.get("COGNEE_API_KEY")
    base_url = os.environ.get("COGNEE_BASE_URL", "").rstrip("/")
    
    if not api_key or not base_url:
        print("ERROR: COGNEE_API_KEY or COGNEE_BASE_URL is missing in .env")
        sys.exit(1)
        
    print(f"Testing Cognee Connection to: {base_url}")
    
    try:
        resp = requests.get(
            f"{base_url}/api/v1/datasets/",
            headers={"X-Api-Key": api_key},
            timeout=10
        )
        if resp.status_code == 200:
            print("✅ SUCCESS! Connected to Cognee Cloud.")
            print(f"Datasets found: {len(resp.json())}")
        else:
            print(f"❌ FAILED! Status: {resp.status_code}\n{resp.text}")
    except Exception as e:
        print(f"❌ FAILED to connect: {e}")

if __name__ == "__main__":
    main()
