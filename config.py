"""
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
