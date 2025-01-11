from datetime import datetime, timedelta, timezone
import time
from colorama import init, Fore
import os
import requests  # Add this import at the top with other imports

from src.utils.config import Config
from src.bot.binance_client import BinanceClientWrapper
from src.bot.trade_executor import TradeExecutor
from src.bot.market_data import MarketData
from src.bot.balance_manager import BalanceManager
from src.bot.telegram_handler import TelegramHandler
from strategies.price_drop import PriceDropStrategy
from src.utils.logger import setup_logger
from src.bot.sp500_tracker import SP500Tracker

# Initialize colorama
init(autoreset=True)

class TradingBot:
    def __init__(self, config_path='config/config.json', use_testnet=False, use_telegram=False,
                 drop_thresholds=None, usdt_reserve=200):
        self.config = Config(config_path)
        self.logger = setup_logger()
        
        # Initialize components
        self.client = BinanceClientWrapper(
            self.config.testnet_api_key if use_testnet else self.config.binance_api_key,
            self.config.testnet_api_secret if use_testnet else self.config.binance_api_secret,
            use_testnet
        )
        
        self.balance_manager = BalanceManager(
            self.client.client, 
            self.logger, 
            self.config.trading_symbols,
            usdt_reserve
        )
        
        self.market_data = MarketData(  # Add MarketData initialization
            self.client.client,
            self.logger,
            self.config.trading_symbols
        )
        
        if use_telegram:
            try:
                # Add debug logging
                self.logger.info(f"Initializing Telegram with token: {self.config.telegram_token[:10]}...")
                self.logger.info(f"Chat ID: {self.config.telegram_chat_id}")
                
                self.telegram = TelegramHandler(
                    self.config.telegram_token,
                    self.config.telegram_chat_id,
                    self.balance_manager,
                    self.market_data
                )
                self.telegram.set_logger(self.logger)
                
                # Test Telegram connection
                test_msg = "🤖 Bot starting up... Testing Telegram connection."
                self.telegram.send_message_sync(test_msg)
                self.logger.info("Telegram test message sent successfully")
                
            except Exception as e:
                self.logger.error(f"Failed to initialize Telegram handler: {str(e)}")
                self.telegram = None
                print(Fore.RED + f"Error initializing Telegram: {str(e)}")
        else:
            self.telegram = None
            self.logger.info("Telegram notifications disabled")
            
        self.trade_executor = TradeExecutor(
            self.client,  # Pass the wrapper instead of self.client.client
            self.logger, 
            self.telegram,
            self.balance_manager,  # Add balance_manager to TradeExecutor
            max_orders=self.config.max_orders_per_symbol  # Use property instead of get method
        )
        self.strategy = PriceDropStrategy(drop_thresholds=drop_thresholds or self.config.drop_thresholds)
        
        # Initialize SP500 tracker with Alpha Vantage API
        self.sp500_tracker = SP500Tracker(
            self.config.alpha_vantage_api_key,
            self.telegram if use_telegram else None,
            self.logger
        )
        
        # Initialize trading state
        self.initialize_trading_state()
        self.trade_amount = None  # Add trade_amount as instance variable
        self.order_type = None
        self.use_percentage = None

    def test_connection(self):
        """Test connection to Binance API and validate symbols"""
        valid_symbols = []
        invalid_symbols = []
        
        for symbol in self.config.trading_symbols:
            try:
                ticker = self.client.client.get_symbol_ticker(symbol=symbol)
                price = ticker['price']
                print(Fore.GREEN + f"Connection successful. Current price of {symbol}: {price}")
                valid_symbols.append(symbol)
            except Exception as e:
                print(Fore.RED + f"Invalid symbol: {symbol}")
                self.logger.error(f"Invalid symbol: {symbol}")
                invalid_symbols.append(symbol)
                
        if invalid_symbols:
            self._write_invalid_symbols(invalid_symbols)
            print(Fore.YELLOW + f"\nRemoved {len(invalid_symbols)} invalid symbols. Trading will continue with {len(valid_symbols)} valid symbols.")
        print(Fore.CYAN + "\nTesting Stock Market Connections:")
        try:
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': 'SPY',
                'apikey': self.config.alpha_vantage_api_key
            }
            try:
                response = requests.get("https://www.alphavantage.co/query", params=params, timeout=10)
                if response.status_code != 200:
                    print(Fore.RED + f"Alpha Vantage API returned status code {response.status_code}")
                    return len(valid_symbols) > 0
                    
                data = response.json()
                
                if 'Error Message' in data:
                    print(Fore.RED + f"Alpha Vantage API error: {data['Error Message']}")
                    return len(valid_symbols) > 0
                    
                if 'Global Quote' in data:
                    quote = data['Global Quote']
                    price = float(quote['05. price'])
                    print(Fore.GREEN + f"Connection successful. Alpha Vantage API working. SPY price: ${price:,.2f}")
                else:
                    print(Fore.RED + "Could not fetch stock data from Alpha Vantage")
            except requests.Timeout:
                print(Fore.RED + "Alpha Vantage API request timed out")
            except requests.RequestException as e:
                print(Fore.RED + f"Error connecting to Alpha Vantage: {str(e)}")
        except Exception as e:
            print(Fore.RED + f"Error testing Alpha Vantage connection: {str(e)}")
            self.logger.error(f"Error testing Alpha Vantage connection: {str(e)}")
                
        if invalid_symbols:
            self._write_invalid_symbols(invalid_symbols)
            print(Fore.YELLOW + f"\nRemoved {len(invalid_symbols)} invalid crypto symbols. Trading will continue with {len(valid_symbols)} valid symbols.")
            self.logger.warning(f"Removed invalid symbols: {', '.join(invalid_symbols)}")
            
        # Update trading symbols to only include valid ones
        self.config.trading_symbols = valid_symbols
        return len(valid_symbols) > 0

    def _write_invalid_symbols(self, invalid_symbols):
        """Write invalid symbols to a file in config folder"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join('config', 'invalid_symbols.txt')
            
            # Create config directory if it doesn't exist
            os.makedirs('config', exist_ok=True)
            
            with open(filepath, 'a') as f:
                f.write(f"\n=== Invalid Symbols Found at {timestamp} ===\n")
                for symbol in invalid_symbols:
                    f.write(f"{symbol}\n")
                    
            print(Fore.YELLOW + f"\nInvalid symbols have been logged to {filepath}")
        except Exception as e:
            print(Fore.RED + f"Error writing invalid symbols to file: {str(e)}")
            self.logger.error(f"Error writing invalid symbols: {str(e)}")

    def initialize_trading_state(self):
        self.last_order_time = {symbol: None for symbol in self.config.trading_symbols}
        self.orders_placed_today = {
            symbol: {threshold: False for threshold in self.strategy.drop_thresholds}
            for symbol in self.config.trading_symbols
        }
        self.max_trades_executed = False

    def run(self):
        fetch_price_interval = 60  # Check every minute
        last_price_fetch_time = time.time() - fetch_price_interval
        next_daily_open_check = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        # Initial setup - Only send to Telegram if explicitly enabled
        print("\nInitial Balance Report:")
        self.market_data.print_daily_open_prices()
        balance = self.balance_manager.get_balance()
        if balance:
            balance_msg = []
            for asset, amount in balance.items():
                print(f"{asset}: {amount}")
                self.logger.info(f"Balance: {asset}: {amount}")
                balance_msg.append(f"{asset}: {amount}")
            
            if self.telegram:
                try:
                    self.telegram.send_message_sync("📊 Initial Balance:\n" + "\n".join(balance_msg))
                except Exception as e:
                    self.logger.error(f"Error sending initial balance to Telegram: {e}")

        # Rest of run method
        while True:
            try:
                self.process_trading_loop(
                    fetch_price_interval,
                    last_price_fetch_time,
                    next_daily_open_check
                )
                time.sleep(60)
                
            except Exception as e:
                self.logger.error(f"Error in main loop: {str(e)}")
                print(Fore.RED + f"Error in main loop: {str(e)}")
                time.sleep(60)

    def process_trading_loop(self, fetch_price_interval, last_price_fetch_time, next_daily_open_check):
        current_time = datetime.now(timezone.utc)
        
        # Check SP500 price at specified times
        if self.sp500_tracker.should_check_price(current_time):
            self.sp500_tracker.get_sp500_price()
        
        current_time = time.time()
        
        # Update prices if needed
        if current_time - last_price_fetch_time >= fetch_price_interval:
            for symbol in self.config.trading_symbols:
                self.market_data.fetch_current_price(symbol)
            last_price_fetch_time = current_time

        # Daily reset check
        if datetime.now(timezone.utc) >= next_daily_open_check:
            self.handle_daily_reset(next_daily_open_check)
            next_daily_open_check += timedelta(days=1)

        # Cancel old limit orders separately
        self.trade_executor.cancel_old_orders()

        # Process trades
        if not self.max_trades_executed:
            self.process_trades()

    def handle_daily_reset(self, next_daily_open_check):
        """Handle daily reset while preserving open orders"""
        # Get daily prices before reset
        daily_prices = {}
        for symbol in self.config.trading_symbols:
            price = self.market_data.get_daily_open_price(symbol)
            if price:
                daily_prices[symbol] = price
        
        # Perform reset operations
        self.market_data.print_daily_open_prices()
        self.trade_executor.reset_daily_order_count()
        
        # Reset order tracking but exclude open orders
        open_orders = {symbol: False for symbol in self.config.trading_symbols}
        for symbol in self.config.trading_symbols:
            if self.trade_executor.check_open_orders(symbol) > 0:
                open_orders[symbol] = True
                print(Fore.YELLOW + f"Found open orders for {symbol} during reset")
        
        # Initialize new day's order tracking
        self.orders_placed_today = {
            symbol: {
                threshold: open_orders[symbol] 
                for threshold in self.strategy.drop_thresholds
            }
            for symbol in self.config.trading_symbols
        }
        
        # Send notification if telegram is enabled
        if self.telegram:
            self.telegram.send_daily_reset_notification(daily_prices)
        
        self.max_trades_executed = False
        self.logger.info("Daily reset completed while preserving open orders")

    def check_usdt_balance(self):
        """Check USDT balance every 10 minutes"""
        while True:
            if not self.balance_manager.has_sufficient_balance(self.trade_amount):
                print(Fore.RED + "Insufficient USDT balance above reserve. Waiting for deposits...")
                time.sleep(600)  # Wait 10 minutes
            else:
                break

    def process_trades(self):
        # Check USDT balance before processing trades
        self.check_usdt_balance()
        for symbol in self.config.trading_symbols:
            # Only process if we can place more orders
            if self.trade_executor.can_place_order(symbol):
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(Fore.CYAN + f"[{timestamp}] Fetching historical data for {symbol}...")
                historical_data = self.market_data.get_historical_data(
                    symbol, 
                    self.config.time_interval, 
                    "1 day ago UTC"
                )
                daily_open_price = self.market_data.get_daily_open_price(symbol)
                signals = self.strategy.generate_signals(
                    historical_data['close'].astype(float).values, 
                    daily_open_price
                )
                
                for threshold, price in signals:
                    # Check if this threshold can still be used for this symbol
                    if self.trade_executor.can_place_order(symbol, threshold):
                        print(Fore.MAGENTA + f"Signal generated for {symbol} at threshold {threshold}: BUY at price {price}")
                        self.execute_trade(symbol, price, threshold)  # Pass threshold to execute_trade
                        self.logger.info(f"Signal generated for {symbol} at threshold {threshold}: BUY at price {price}")
                    else:
                        print(Fore.YELLOW + f"Already executed order for {symbol} at threshold {threshold}, skipping")

        # Update max_trades_executed status
        self.max_trades_executed = all(
            all(placed for placed in self.orders_placed_today[symbol].values()) 
            for symbol in self.config.trading_symbols
        )

    def configure_trading_params(self, order_type, use_percentage, trade_amount):
        """Configure trading parameters"""
        self.trade_amount = trade_amount
        self.order_type = order_type
        self.use_percentage = use_percentage
        self.trade_executor.configure_trading_params(
            order_type=order_type,
            use_percentage=use_percentage,
            trade_amount=trade_amount
        )

    def execute_trade(self, symbol, price, threshold):
        """Execute trade with configured parameters"""
        try:
            if self.use_percentage:
                balance = self.balance_manager.get_balance().get('USDT', 0)
                amount = balance * self.trade_amount
            else:
                amount = self.trade_amount
            
            # Calculate quantity with more precision
            quantity = "{:.8f}".format(amount / float(price))
            
            self.trade_executor.execute_trade(
                symbol=symbol,
                quantity=quantity,  # Pass the formatted string quantity
                price=price,
                order_type=self.order_type,
                threshold=threshold  # Add threshold parameter
            )
        except Exception as e:
            self.logger.error(f"Error calculating trade quantity for {symbol}: {str(e)}")
            print(Fore.RED + f"Error calculating trade quantity for {symbol}: {str(e)}")

if __name__ == "__main__":
    if os.getenv('DOCKER_CONTAINER'):
        # Add debug logging for Docker environment
        print("Running in Docker container")
        print(f"USE_TELEGRAM env: {os.getenv('USE_TELEGRAM')}")
        print(f"TELEGRAM_TOKEN env: {os.getenv('TELEGRAM_TOKEN')[:10]}...")
        print(f"TELEGRAM_CHAT_ID env: {os.getenv('TELEGRAM_CHAT_ID')}")
        
        # Running inside Docker, use environment variables
        use_testnet = os.getenv('USE_TESTNET').strip().lower() == 'yes'
        use_telegram = os.getenv('USE_TELEGRAM').strip().lower() == 'yes'
        drop_thresholds = [float(x) for x in os.getenv('DROP_THRESHOLDS').split(',')]
        order_type = os.getenv('ORDER_TYPE').strip().lower()
        use_percentage = os.getenv('USE_PERCENTAGE').strip().lower() == 'yes'
        trade_amount = float(os.getenv('TRADE_AMOUNT'))
        usdt_reserve = float(os.getenv('USDT_RESERVE', 0))  # Default reserve amount is 0
    else:
        # Running normally, prompt for input
        use_testnet = input("Do you want to use the testnet? (yes/no): ").strip().lower() == 'yes'
        use_telegram = input("Do you want to use Telegram notifications? (yes/no): ").strip().lower() == 'yes'
        
        # Get drop thresholds
        while True:
            try:
                num_thresholds = int(input("Enter the number of drop thresholds: ").strip())
                break
            except ValueError:
                print("Please enter a valid number.")
                
        drop_thresholds = []
        for i in range(num_thresholds):
            while True:
                try:
                    threshold = float(input(f"Enter drop threshold {i+1} percentage (e.g., 1 for 1%): ").strip()) / 100
                    if i == 0 or threshold > drop_thresholds[-1]:
                        drop_thresholds.append(threshold)
                        break
                    print(f"Threshold {i+1} must be higher than threshold {i}. Please enter a valid value.")
                except ValueError:
                    print("Please enter a valid number.")
        
        # Get order type
        while True:
            order_type = input("Do you want to use limit orders or market orders? (limit/market): ").strip().lower()
            if order_type in ['limit', 'market']:
                break
            print("Please enter either 'limit' or 'market'.")
        
        # Get percentage usage
        use_percentage = input("Do you want to use a percentage of USDT per trade? (yes/no): ").strip().lower() == 'yes'
        
        # Get trade amount with validation
        while True:
            try:
                if use_percentage:
                    amount_input = input("Enter the percentage of USDT to use per trade (e.g., 10 for 10%): ").strip()
                    trade_amount = float(amount_input) / 100
                    if 0 < trade_amount <= 1:
                        break
                    print("Please enter a percentage between 0 and 100.")
                else:
                    trade_amount = float(input("Enter the amount of USDT to use per trade: ").strip())
                    if trade_amount > 0:
                        break
                    print("Please enter an amount greater than 0.")
            except ValueError:
                print("Please enter a valid number.")
        
        # Get USDT reserve amount with validation
        while True:
            try:
                usdt_input = input("Enter the USDT reserve amount (0 or higher): ").strip()
                if not usdt_input:
                    usdt_reserve = 0
                    break
                usdt_reserve = float(usdt_input)
                if usdt_reserve >= 0:
                    break
                print("Please enter a non-negative number.")
            except ValueError:
                print("Please enter a valid number.")
        
        print(f"USDT reserve set to: {usdt_reserve}")

    # Initialize bot
    bot = TradingBot(
        use_testnet=use_testnet,
        use_telegram=use_telegram,
        drop_thresholds=sorted(drop_thresholds),  # Ensure thresholds are sorted
        usdt_reserve=usdt_reserve
    )
    
    # Configure trading parameters using new method
    bot.configure_trading_params(
        order_type=order_type,
        use_percentage=use_percentage,
        trade_amount=trade_amount
    )
    
    # Start bot
    print(Fore.CYAN + "\nInitializing bot...")
    if bot.test_connection():
        print(Fore.CYAN + "\nStarting trading bot...")
        bot.run()
    else:
        print(Fore.RED + "\nNo valid trading symbols found. Please check your configuration.")