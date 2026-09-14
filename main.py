"""
Complete example: Fetching from API → Transforming → Loading to SQL → Querying
"""

import requests
import sqlite3
import os
from datetime import datetime
from pathlib import Path

# ============================================
# STEP 1: FETCH DATA FROM API
# ============================================

def fetch_nfl_teams():
    """Fetch NFL teams from TheSportsDB API"""
    
    API_KEY = "123"
#    base_url = "https://www.thesportsdb.com/api/v1/json"
    base_url = "https://www.thesportsdb.com/api/v1/json/123/lookupleague.php?id=4328"    
    # This is the "endpoint" - like a pre-built query
    url = f"{base_url}/{API_KEY}/search_all_teams.php?l=NFL"
    
    print("Fetching data from API...")
    response = requests.get(url)
    
    # Check if request was successful
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Received {len(data['teams'])} teams")
        return data['teams']
    else:
        print(f"✗ Error: {response.status_code}")
        return None

# ============================================
# STEP 2: TRANSFORM DATA (Python Processing)
# ============================================

def transform_team_data(raw_teams):
    """
    Transform API data into a cleaner format
    This is like your ETL process - extract, transform, load
    """
    
    transformed = []
    
    for team in raw_teams:
        # API gives you ALL fields, you pick what you need
        # Similar to: SELECT specific_columns FROM api_data
        
        clean_team = {
            'team_id': team.get('idTeam'),
            'team_name': team.get('strTeam'),
            'stadium': team.get('strStadium'),
            'league': team.get('strLeague'),
            'formed_year': team.get('intFormedYear'),
            # Calculate stadium capacity as integer
            'stadium_capacity': int(team.get('intStadiumCapacity', 0)),
            'extracted_date': datetime.now().strftime('%Y-%m-%d')
        }
        
        transformed.append(clean_team)
    
    print(f"✓ Transformed {len(transformed)} team records")
    return transformed

# ============================================
# STEP 3: LOAD INTO DATABASE (SQL)
# ============================================

def create_database():
    """Create the SQLite database and table"""
    # Ensure the data directory exists and use it for the DB file
    data_dir = Path('data')
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / 'sports_data.db'

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Create table - now you're back in SQL land!
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER PRIMARY KEY,
            team_name TEXT NOT NULL,
            stadium TEXT,
            league TEXT,
            formed_year INTEGER,
            stadium_capacity INTEGER,
            extracted_date DATE
        )
    """)
    
    conn.commit()
    print(f"✓ Database created at: {db_path}")
    return conn, db_path

def load_to_database(conn, teams):
    """Load transformed data into SQL database"""
    
    cursor = conn.cursor()
    
    # Insert or replace data
    for team in teams:
        cursor.execute("""
            INSERT OR REPLACE INTO teams 
            (team_id, team_name, stadium, league, formed_year, 
             stadium_capacity, extracted_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            team['team_id'],
            team['team_name'],
            team['stadium'],
            team['league'],
            team['formed_year'],
            team['stadium_capacity'],
            team['extracted_date']
        ))
    
    conn.commit()
    print(f"✓ Loaded {len(teams)} teams into database")

# ============================================
# STEP 4: QUERY WITH SQL (You're home now!)
# ============================================

def run_sql_queries(conn):
    """Now you can use regular SQL to analyze your data"""
    
    cursor = conn.cursor()
    
    print("\n" + "="*60)
    print("SQL QUERY RESULTS")
    print("="*60)
    
    # Query 1: Teams with largest stadiums
    print("\n1. Top 5 Teams by Stadium Capacity:")
    cursor.execute("""
        SELECT team_name, stadium, stadium_capacity
        FROM teams
        WHERE stadium_capacity > 0
        ORDER BY stadium_capacity DESC
        LIMIT 5
    """)
    
    for row in cursor.fetchall():
        print(f"   {row[0]}: {row[1]} ({row[2]:,} capacity)")
    
    # Query 2: Teams by formation year
    print("\n2. Oldest NFL Teams:")
    cursor.execute("""
        SELECT team_name, formed_year
        FROM teams
        WHERE formed_year IS NOT NULL
        ORDER BY formed_year ASC
        LIMIT 5
    """)
    
    for row in cursor.fetchall():
        print(f"   {row[0]}: Founded {row[1]}")
    
    # Query 3: Average stadium size
    print("\n3. Stadium Statistics:")
    cursor.execute("""
        SELECT 
            COUNT(*) as total_teams,
            AVG(stadium_capacity) as avg_capacity,
            MAX(stadium_capacity) as max_capacity,
            MIN(stadium_capacity) as min_capacity
        FROM teams
        WHERE stadium_capacity > 0
    """)
    
    row = cursor.fetchone()
    print(f"   Total Teams: {row[0]}")
    print(f"   Average Capacity: {row[1]:,.0f}")
    print(f"   Largest Stadium: {row[2]:,}")
    print(f"   Smallest Stadium: {row[3]:,}")

# ============================================
# MAIN EXECUTION
# ============================================

def main():
    """Run the complete ETL pipeline"""
    
    print("Starting API to SQL Pipeline...\n")
    
    # Step 1: Fetch from API (like querying an external source)
    raw_data = fetch_nfl_teams()
    
    if not raw_data:
        print("Failed to fetch data")
        return
    
    # Step 2: Transform (clean and structure the data)
    transformed_data = transform_team_data(raw_data)
    
    # Step 3: Load into Database
    conn, db_path = create_database()
    load_to_database(conn, transformed_data)
    
    # Step 4: Query with SQL (now you can do whatever you want!)
    run_sql_queries(conn)
    
    conn.close()
    print("\n✓ Pipeline complete!")
    print(f"\nYou can now open '{db_path}' with any SQLite tool")
    print("and run your own SQL queries!")

if __name__ == "__main__":
    main()
