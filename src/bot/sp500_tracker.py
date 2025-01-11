import requests
from datetime import datetime, timedelta
import pytz
from datetime import time as datetime_time  # Renamed import to avoid conflict
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_calls, time_window):
        self.max_calls = max_calls
        self.time_window = time_window  # in seconds
        self.calls = deque()

    def wait_if_needed(self):
        """Wait if we've exceeded our rate limit"""
        now = time.time()
        
        # Remove old calls outside the time window
        while self.calls and now - self.calls[0] >= self.time_window:
            self.calls.popleft()
        
        # If we've reached the limit, wait until we can make another call
        if len(self.calls) >= self.max_calls:
            wait_time = self.calls[0] + self.time_window - now
            if wait_time > 0:
                time.sleep(wait_time)
                self.calls.popleft()  # Remove oldest call after waiting
        
        # Add current call
        self.calls.append(now)

class SP500Tracker:
    def __init__(self, api_key, telegram_handler=None, logger=None):
        self.api_key = api_key
        self.telegram = telegram_handler
        self.logger = logger
        self.base_url = "https://www.alphavantage.co/query"
        self.last_check_date = None
        self.check_times = [
            datetime_time(hour=8, minute=0),   # Use renamed import
            datetime_time(hour=12, minute=0),
            datetime_time(hour=16, minute=0),
            datetime_time(hour=20, minute=0)
        ]
        self.stocks = {
            'SPY': {'name': 'S&P 500 ETF', 'function': 'GLOBAL_QUOTE'},
            'MSTR': {'name': 'Microstrategy', 'function': 'GLOBAL_QUOTE'}
        }
        # Initialize rate limiter: 4 calls per minute (60 seconds)
        self.rate_limiter = RateLimiter(max_calls=4, time_window=60)
        self.timeout = 10  # Add timeout value

    def should_check_price(self, current_time):
        """Check if we should fetch SP500 price based on time"""
        if self.last_check_date != current_time.date():
            for check_time in self.check_times:
                current_time_check = current_time.time()
                if current_time_check >= check_time:
                    return True
        return False

    def get_sp500_price(self):
        """Fetch stock prices from Alpha Vantage API"""
        try:
            message_parts = []
            
            for symbol, info in self.stocks.items():
                # Wait if we need to due to rate limiting
                self.rate_limiter.wait_if_needed()
                
                params = {
                    'function': info['function'],
                    'symbol': symbol,
                    'apikey': self.api_key
                }
                
                try:
                    response = requests.get(self.base_url, params=params, timeout=self.timeout)
                    if response.status_code == 404:
                        self._handle_error(f"API endpoint not found for {symbol}")
                        continue
                    if response.status_code != 200:
                        self._handle_error(f"API returned status code {response.status_code} for {symbol}")
                        continue
                        
                    data = response.json()
                    
                    if 'Note' in data:
                        self._handle_error(f"API rate limit reached: {data['Note']}")
                        return None
                        
                    if 'Error Message' in data:
                        self._handle_error(f"API error: {data['Error Message']}")
                        continue
                    
                    if 'Global Quote' in data:
                        quote = data['Global Quote']
                        price = float(quote['05. price'])
                        change = float(quote['09. change'])
                        change_percent = float(quote['10. change percent'].rstrip('%'))
                        volume = int(quote['06. volume'])
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Format with emoji based on price change
                        change_emoji = "🔴" if change < 0 else "🟢"
                        
                        stock_message = (
                            f"{change_emoji} {info['name']} ({symbol}) Price Report\n"
                            f"Time: {timestamp}\n"
                            f"Price: ${price:,.2f}\n"
                            f"Change: ${change:+,.2f} ({change_percent:+.2f}%)\n"
                            f"Volume: {volume:,}"
                        )
                        
                        message_parts.append(stock_message)
                        
                        if self.logger:
                            self.logger.info(f"{info['name']} price: ${price:,.2f}")
                    else:
                        self._handle_no_data(symbol, info)
                
                except requests.Timeout:
                    self._handle_error(f"Request timeout for {symbol}")
                    continue
                except requests.RequestException as e:
                    self._handle_error(f"Request failed for {symbol}: {str(e)}")
                    continue
                except Exception as e:
                    self._handle_error(f"Unexpected error for {symbol}: {str(e)}")
                    continue
            
            if message_parts and self.telegram:
                combined_message = "\n\n".join(message_parts)
                self.telegram.send_message_sync(combined_message)
            
            self.last_check_date = datetime.now(pytz.UTC).date()
            
        except Exception as e:
            self._handle_error(str(e))

    def _handle_no_data(self, symbol, info):
        """Handle case when no data is available"""
        error_msg = f"No data available for {info['name']} ({symbol})"
        if self.logger:
            self.logger.warning(error_msg)
        if self.telegram:
            self.telegram.send_message_sync(f"⚠️ {error_msg}")

    def _handle_error(self, error_message):
        """Handle API errors"""
        error_msg = f"Error fetching stock prices: {error_message}"
        if self.logger:
            self.logger.error(error_msg)
        if self.telegram:
            self.telegram.send_message_sync(f"⚠️ {error_msg}")
