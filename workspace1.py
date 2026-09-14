"""
API Discovery Tool - How to Find Available Values
When documentation is poor, use this approach to discover what's available
"""

import requests
import json

API_KEY = "3"
BASE_URL = "https://www.thesportsdb.com/api/v1/json"

# ============================================================
# STEP 1: Find "List All" or "Search All" Endpoints
# ============================================================

def discover_all_teams():
    """
    STRATEGY: Look for endpoints that list EVERYTHING
    Common patterns: 
    - list_all_*
    - search_all_*
    - get_all_*
    """
    
    print("="*70)
    print("STEP 1: DISCOVER ALL AVAILABLE TEAMS")
    print("="*70)
    print("\nLooking for a 'list all' endpoint...\n")
    
    # Try to get ALL teams in a league
    url = f"{BASE_URL}/{API_KEY}/search_all_teams.php?l=NFL"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        
        if data.get('teams'):
            print(f"✓ Found {len(data['teams'])} teams!")
            print("\nAll available NFL team names:")
            print("-"*70)
            
            team_names = []
            for team in data['teams']:
                team_name = team['strTeam']
                team_names.append(team_name)
                print(f"  - {team_name}")
            
            # Save for later use
            with open('available_nfl_teams.txt', 'w') as f:
                f.write('\n'.join(team_names))
            
            print(f"\n✓ Saved all team names to 'available_nfl_teams.txt'")
            return team_names
    
    return []

# ============================================================
# STEP 2: Extract IDs and Reference Values
# ============================================================

def extract_reference_values():
    """
    STRATEGY: Get the 'list all' data and extract ALL the IDs and values
    you might need later
    """
    
    print("\n" + "="*70)
    print("STEP 2: EXTRACT ALL REFERENCE VALUES")
    print("="*70)
    
    url = f"{BASE_URL}/{API_KEY}/search_all_teams.php?l=NFL"
    response = requests.get(url)
    data = response.json()
    
    # Create a reference lookup
    reference_data = {
        'teams': {},
        'leagues': set(),
        'countries': set(),
        'stadiums': set()
    }
    
    if data.get('teams'):
        for team in data['teams']:
            # Store team with multiple lookup keys
            team_id = team['idTeam']
            team_name = team['strTeam']
            
            reference_data['teams'][team_name] = {
                'id': team_id,
                'name': team_name,
                'alternate_name': team.get('strAlternate'),
                'stadium': team.get('strStadium'),
                'league': team.get('strLeague'),
                'country': team.get('strCountry')
            }
            
            # Collect unique values
            if team.get('strLeague'):
                reference_data['leagues'].add(team['strLeague'])
            if team.get('strCountry'):
                reference_data['countries'].add(team['strCountry'])
            if team.get('strStadium'):
                reference_data['stadiums'].add(team['strStadium'])
    
    # Convert sets to lists for JSON
    reference_data['leagues'] = list(reference_data['leagues'])
    reference_data['countries'] = list(reference_data['countries'])
    reference_data['stadiums'] = list(reference_data['stadiums'])
    
    # Save to JSON for easy lookup
    with open('nfl_reference.json', 'w') as f:
        json.dump(reference_data, f, indent=2)
    
    print("\n✓ Created reference file: nfl_reference.json")
    print(f"\nAvailable leagues: {reference_data['leagues']}")
    print(f"Available countries: {reference_data['countries']}")
    print(f"Total teams: {len(reference_data['teams'])}")
    
    return reference_data

# ============================================================
# STEP 3: Try Different Search Patterns
# ============================================================

def test_search_patterns(search_term="Cowboys"):
    """
    STRATEGY: Test if the API accepts partial matches or 
    different formats
    """
    
    print("\n" + "="*70)
    print(f"STEP 3: TEST SEARCH PATTERNS FOR '{search_term}'")
    print("="*70)
    
    test_cases = [
        search_term,                    # Exact
        search_term.lower(),            # Lowercase
        search_term.upper(),            # Uppercase
        search_term.replace(" ", ""),   # No spaces
        search_term.split()[0],         # First word only
    ]
    
    for test in test_cases:
        url = f"{BASE_URL}/{API_KEY}/searchteams.php?t={test}"
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('teams'):
                print(f"✓ '{test}' -> Found {len(data['teams'])} team(s)")
                for team in data['teams']:
                    print(f"    {team['strTeam']}")
            else:
                print(f"✗ '{test}' -> No results")

# ============================================================
# STEP 4: Build a Lookup Function
# ============================================================

def build_team_lookup():
    """
    STRATEGY: Create a reusable lookup that handles different inputs
    """
    
    print("\n" + "="*70)
    print("STEP 4: CREATE SMART LOOKUP FUNCTION")
    print("="*70)
    
    # Load the reference data
    with open('nfl_reference.json', 'r') as f:
        reference = json.load(f)
    
    def find_team(search_term):
        """
        Smart lookup that handles:
        - Exact name
        - Partial name
        - Case-insensitive
        """
        search_lower = search_term.lower()
        
        matches = []
        for team_name, team_data in reference['teams'].items():
            if search_lower in team_name.lower():
                matches.append({
                    'name': team_name,
                    'id': team_data['id'],
                    'stadium': team_data['stadium']
                })
        
        return matches
    
    # Test it
    print("\nTesting smart lookup:")
    print("-"*70)
    
    test_searches = ["Cowboys", "49ers", "Patriots", "New York"]
    
    for search in test_searches:
        results = find_team(search)
        print(f"\nSearch: '{search}'")
        if results:
            for r in results:
                print(f"  ✓ {r['name']} (ID: {r['id']})")
        else:
            print(f"  ✗ No matches")
    
    return find_team

# ============================================================
# STEP 5: Discover Related Endpoints
# ============================================================

def discover_related_data(team_id="134920"):
    """
    STRATEGY: Once you have an ID, try common endpoint patterns
    to see what else you can get
    """
    
    print("\n" + "="*70)
    print(f"STEP 5: DISCOVER WHAT DATA YOU CAN GET FOR A TEAM")
    print("="*70)
    print(f"\nUsing team ID: {team_id}")
    
    # Common endpoint patterns to try
    endpoints_to_try = [
        ("eventslast.php", {"id": team_id}, "Last 5 events"),
        ("eventsnext.php", {"id": team_id}, "Next 5 events"),
        ("lookupteam.php", {"id": team_id}, "Team details"),
    ]
    
    print("\nTrying different endpoints:")
    print("-"*70)
    
    for endpoint, params, description in endpoints_to_try:
        url = f"{BASE_URL}/{API_KEY}/{endpoint}"
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Check what keys are in the response
            keys = list(data.keys())
            has_data = any(data[key] for key in keys if data[key])
            
            if has_data:
                print(f"✓ {description:20} -> {endpoint}")
                print(f"  Available keys: {keys}")
            else:
                print(f"✗ {description:20} -> No data")
        else:
            print(f"✗ {description:20} -> Error {response.status_code}")

# ============================================================
# STEP 6: Handle Multiple Leagues
# ============================================================

def discover_all_leagues():
    """
    STRATEGY: Find all available leagues first, then get teams for each
    """
    
    print("\n" + "="*70)
    print("STEP 6: DISCOVER ALL AVAILABLE LEAGUES")
    print("="*70)
    
    # Common US sports leagues
    leagues_to_try = ["NFL", "NBA", "MLB", "NHL", "MLS"]
    
    all_leagues_data = {}
    
    for league in leagues_to_try:
        url = f"{BASE_URL}/{API_KEY}/search_all_teams.php?l={league}"
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('teams'):
                team_count = len(data['teams'])
                print(f"✓ {league:10} -> {team_count} teams")
                
                all_leagues_data[league] = {
                    'count': team_count,
                    'teams': [t['strTeam'] for t in data['teams']]
                }
            else:
                print(f"✗ {league:10} -> No data")
    
    # Save comprehensive reference
    with open('all_leagues_reference.json', 'w') as f:
        json.dump(all_leagues_data, f, indent=2)
    
    print(f"\n✓ Saved complete reference: all_leagues_reference.json")
    return all_leagues_data

# ============================================================
# COMPLETE WORKFLOW
# ============================================================

def complete_discovery_workflow():
    """
    Run the complete discovery process
    """
    
    print("\n" + "="*70)
    print("API DISCOVERY COMPLETE WORKFLOW")
    print("="*70)
    print("\nThis will show you how to discover everything you need")
    print("when API documentation is poor or incomplete.\n")
    
    # Step 1: Get all teams
    team_names = discover_all_teams()
    
    # Step 2: Extract all reference values
    reference = extract_reference_values()
    
    # Step 3: Test search patterns
    if team_names:
        test_search_patterns(team_names[0])
    
    # Step 4: Build smart lookup
    find_team = build_team_lookup()
    
    # Step 5: Discover related data
    if reference['teams']:
        first_team_id = list(reference['teams'].values())[0]['id']
        discover_related_data(first_team_id)
    
    # Step 6: Get all leagues
    all_leagues = discover_all_leagues()
    
    print("\n" + "="*70)
    print("DISCOVERY COMPLETE!")
    print("="*70)
    print("\nFiles created:")
    print("  - available_nfl_teams.txt       (List of all team names)")
    print("  - nfl_reference.json            (Complete reference data)")
    print("  - all_leagues_reference.json    (All leagues and teams)")
    print("\nNow you know:")
    print("  ✓ What team names exist")
    print("  ✓ What IDs to use")
    print("  ✓ What endpoints work")
    print("  ✓ What data is available")
    print("="*70)

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    complete_discovery_workflow()