import requests

API_KEY = "123"  # Free public API key
BASE_URL = "https://www.thesportsdb.com/api/v1/json"

# Get all NFL teams
# response = requests.get(f"{BASE_URL}/{API_KEY}/search_all_teams.php?l=NFL")
response = requests.get(f"https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?c=Spain")
teams = response.json()
print(teams)