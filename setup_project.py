"""
Sports Tracker - Project Setup Script
Run this script to create the initial project structure
"""

import os
from pathlib import Path

def create_project_structure():
    """Create the complete directory structure for the sports tracker project"""
    
    # Define the project structure
    structure = {
        'src': {
            'data_collectors': ['__init__.py', 'sports_api.py', 'config.py'],
            'calculators': ['__init__.py', 'win_calculator.py'],
            'database': ['__init__.py', 'models.py', 'db_manager.py'],
            'web': ['__init__.py', 'app.py'],
            'notifications': ['__init__.py', 'email_sender.py'],
        },
        'tests': ['__init__.py', 'test_calculator.py', 'test_api.py'],
        'static': {
            'css': ['style.css'],
            'js': ['main.js']
        },
        'templates': ['index.html', 'results.html'],
        'data': ['.gitkeep'],
        'logs': ['.gitkeep'],
    }
    
    # Root level files
    root_files = {
        'requirements.txt': '''# Core dependencies
requests>=2.31.0
python-dotenv>=1.0.0
apscheduler>=3.10.0

# Database
sqlalchemy>=2.0.0

# Web framework (choose one)
fastapi>=0.104.0
uvicorn>=0.24.0
# flask>=3.0.0

# Email
python-smtplib-ssl>=1.0.0

# Testing
pytest>=7.4.0
''',
        
        'config.py': '''"""
Configuration settings for the sports tracker
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # API Configuration
    SPORTS_API_KEY = os.getenv('SPORTS_API_KEY', '')
    SPORTS_API_URL = os.getenv('SPORTS_API_URL', 'https://api.example.com')
    
    # Database Configuration
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/sports_tracker.db')
    DATABASE_URL = f'sqlite:///{DATABASE_PATH}'
    
    # Email Configuration
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', '').split(',')
    
    # Schedule Configuration
    UPDATE_SCHEDULE_DAY = os.getenv('UPDATE_SCHEDULE_DAY', 'monday')
    UPDATE_SCHEDULE_TIME = os.getenv('UPDATE_SCHEDULE_TIME', '09:00')
    
    # Web Configuration
    WEB_HOST = os.getenv('WEB_HOST', '0.0.0.0')
    WEB_PORT = int(os.getenv('WEB_PORT', 8000))

config = Config()
''',
        
        '.env.example': '''# API Keys
SPORTS_API_KEY=your_api_key_here
SPORTS_API_URL=https://api.sportsdata.io/v3

# Database
DATABASE_PATH=data/sports_tracker.db

# Email Settings
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENTS=recipient1@email.com,recipient2@email.com

# Schedule (day of week and time)
UPDATE_SCHEDULE_DAY=monday
UPDATE_SCHEDULE_TIME=09:00

# Web Server
WEB_HOST=0.0.0.0
WEB_PORT=8000
''',
        
        '.gitignore': '''# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Environment
.env
.venv

# IDE
.vscode/
.idea/
*.swp
*.swo

# Database
*.db
*.sqlite
*.sqlite3

# Logs
logs/*.log

# OS
.DS_Store
Thumbs.db
''',
        
        'main.py': '''"""
Main entry point for the sports tracker application
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
import logging

from src.data_collectors.sports_api import SportsDataCollector
from src.calculators.win_calculator import WinCalculator
from src.database.db_manager import DatabaseManager
from src.notifications.email_sender import EmailNotifier
from config import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/sports_tracker.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def run_weekly_update():
    """Execute the weekly sports data update and calculation"""
    logger.info("Starting weekly sports update...")
    
    try:
        # Initialize components
        db = DatabaseManager()
        collector = SportsDataCollector()
        calculator = WinCalculator()
        notifier = EmailNotifier()
        
        # Collect latest sports data
        logger.info("Collecting sports data...")
        sports_data = collector.fetch_weekly_results()
        
        # Save to database
        logger.info("Saving data to database...")
        db.save_results(sports_data)
        
        # Calculate statistics
        logger.info("Calculating win statistics...")
        calculations = calculator.calculate(sports_data)
        
        # Send notification
        logger.info("Sending email notification...")
        notifier.send_weekly_summary(calculations)
        
        logger.info("Weekly update completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during weekly update: {e}", exc_info=True)

def main():
    """Main function to start the scheduler"""
    logger.info("Sports Tracker started")
    
    # Create scheduler
    scheduler = BlockingScheduler()
    
    # Schedule weekly updates (every Monday at 9 AM by default)
    scheduler.add_job(
        run_weekly_update,
        'cron',
        day_of_week=config.UPDATE_SCHEDULE_DAY,
        hour=int(config.UPDATE_SCHEDULE_TIME.split(':')[0]),
        minute=int(config.UPDATE_SCHEDULE_TIME.split(':')[1])
    )
    
    logger.info(f"Scheduled weekly updates for {config.UPDATE_SCHEDULE_DAY} at {config.UPDATE_SCHEDULE_TIME}")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Sports Tracker stopped")

if __name__ == "__main__":
    main()
''',
        
        'README.md': '''# Sports Tracker

A Python application to track sports wins across multiple sports and calculate weekly statistics.

## Features
- Automated weekly data collection from sports APIs
- Win/loss calculations and statistics
- Email notifications with weekly summaries
- Optional web interface for viewing results
- SQLite database for historical data

## Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd sports-tracker
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\\Scripts\\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and settings
   ```

5. **Run the application**
   ```bash
   # For scheduled updates
   python main.py
   
   # For web interface
   python src/web/app.py
   ```

## Project Structure
```
sports-tracker/
├── src/                    # Source code
│   ├── data_collectors/   # API integrations
│   ├── calculators/       # Calculation logic
│   ├── database/          # Database models
│   ├── web/              # Web interface
│   └── notifications/     # Email system
├── tests/                 # Unit tests
├── data/                  # Database files
├── logs/                  # Application logs
└── static/               # Web assets
```

## Configuration

Edit `.env` file to configure:
- Sports API credentials
- Email settings (SMTP)
- Update schedule
- Database location

## Testing

Run tests with:
```bash
pytest tests/
```

## License
MIT
'''
    }
    
    # Create directory structure
    for dir_name, contents in structure.items():
        if isinstance(contents, dict):
            # Nested directory
            for subdir, files in contents.items():
                path = Path(dir_name) / subdir
                path.mkdir(parents=True, exist_ok=True)
                for file in files:
                    (path / file).touch()
        else:
            # Simple directory with files
            path = Path(dir_name)
            path.mkdir(parents=True, exist_ok=True)
            for file in contents:
                (path / file).touch()
    
    # Create root level files
    for filename, content in root_files.items():
        with open(filename, 'w') as f:
            f.write(content)
    
    print("✓ Project structure created successfully!")
    print("\nNext steps:")
    print("1. Create a virtual environment: python -m venv venv")
    print("2. Activate it: source venv/bin/activate (or venv\\Scripts\\activate on Windows)")
    print("3. Install dependencies: pip install -r requirements.txt")
    print("4. Copy .env.example to .env and add your API keys")
    print("5. Start coding in VS Code!")

if __name__ == "__main__":
    create_project_structure()