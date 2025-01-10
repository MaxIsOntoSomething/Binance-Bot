import logging
from datetime import datetime
import os

def setup_logger():
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Setup logging configuration
    logging.basicConfig(
        filename=f'logs/trades_{datetime.now().strftime("%Y%m%d")}.log',
        format='%(asctime)s - %(message)s',
        level=logging.INFO
    )
    return logging.getLogger()