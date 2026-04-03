import requests
import pandas as pd
from dotenv import load_dotenv
import os

# Load credentials from .env file
load_dotenv()
email = os.getenv("ACLED_EMAIL")
password = os.getenv("ACLED_PASSWORD")

# Step 1: Authenticate and get access token
print("Authenticating with ACLED...")
auth_response = requests.post(
    "https://acleddata.com/oauth/token",
    data={
        "username": email,
        "password": password,
        "grant_type": "password",
        "client_id": "acled"
    }
)

if auth_response.status_code != 200:
    print(f"Authentication failed: {auth_response.status_code}")
    print(auth_response.text)
    exit()

access_token = auth_response.json()["access_token"]
print("Authentication successful.")

# Step 2: Pull Somalia conflict data from the last 90 days
print("Fetching Somalia conflict data...")
response = requests.get(
    "https://acleddata.com/api/acled/read",
    headers={"Authorization": f"Bearer {access_token}"},
    params={
        "country": "Somalia",
        "event_date": "2025-01-01|2026-04-01",
        "event_date_where": "BETWEEN",
        "limit": 500
    }
)

if response.status_code != 200:
    print(f"Data request failed: {response.status_code}")
    print(response.text)
    exit()

# Step 3: Convert to a pandas DataFrame
data = response.json()["data"]
df = pd.DataFrame(data)

# Step 4: Show what we got
print(f"\nPulled {len(df)} events.")
print(f"Date range: {df['event_date'].min()} to {df['event_date'].max()}")
print(f"\nEvent types:")
print(df["event_type"].value_counts())
print(f"\nRegions:")
print(df["admin1"].value_counts())
print(f"\nTotal fatalities: {df['fatalities'].astype(int).sum()}")
print(f"\nSample row:")
print(df.iloc[0])