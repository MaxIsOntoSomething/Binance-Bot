import json
import os

class Config:
    def __init__(self, config_path):
        self.config_path = config_path  # Store config path for updates
        with open(config_path) as config_file:
            self.config = json.load(config_file)
        self._trading_symbols = self.config["TRADING_SYMBOLS"]

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
        return self._trading_symbols

    @trading_symbols.setter
    def trading_symbols(self, symbols):
        self._trading_symbols = symbols
        self.config['TRADING_SYMBOLS'] = symbols
        # Update the config file with new symbols
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Warning: Could not update config file: {e}")

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

    @property
    def polygon_access_key(self):
        """Get Polygon.io API key"""
        return self.config['POLYGON_ACCESS_KEY']

    @property
    def polygon_secret_key(self):
        """Get Polygon.io secret key"""
        return self.config['POLYGON_SECRET_KEY']

    @property
    def alpha_vantage_api_key(self):
        """Get Alpha Vantage API key"""
        return self.config['ALPHA_VANTAGE_API_KEY']

    @property
    def stock_symbols(self):
        """Get stock symbols to track"""
        return self.config.get('STOCK_SYMBOLS', ['SPY', 'MSTR'])

    @property
    def stock_check_times(self):
        """Get times to check stock prices"""
        return self.config.get('STOCK_CHECK_TIMES', ['08:00', '12:00', '16:00', '20:00'])

    @property
    def max_orders_per_symbol(self):
        """Get max orders per symbol"""
        return self.config.get('MAX_ORDERS_PER_SYMBOL', 3)
