import json
import os

class Config:
    def __init__(self, config_path):
        with open(config_path) as config_file:
            self.config = json.load(config_file)
            
    @property
    def binance_api_key(self):
        return self.config['BINANCE_API_KEY']
        
    @property
    def binance_api_secret(self):
        return self.config['BINANCE_API_SECRET']
        
    @property
    def testnet_api_key(self):
        return self.config['TESTNET_API_KEY']
        
    @property
    def testnet_api_secret(self):
        return self.config['TESTNET_API_SECRET']
        
    @property
    def trading_symbols(self):
        if os.getenv('DOCKER_CONTAINER'):
            return os.getenv('TRADING_SYMBOLS').split(',')
        return self.config["TRADING_SYMBOLS"]
        
    @property
    def telegram_token(self):
        return self.config['TELEGRAM_TOKEN']
        
    @property
    def telegram_chat_id(self):
        return self.config['TELEGRAM_CHAT_ID']
        
    @property
    def time_interval(self):
        return self.config['TIME_INTERVAL']
        
    @property
    def drop_thresholds(self):
        return self.config['DROP_THRESHOLDS']
        
    @property
    def usdt_reserve(self):
        return self.config.get('USDT_RESERVE', 200)  # Default 200 USDT if not specified
