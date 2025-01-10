from datetime import datetime, timedelta, timezone
import time
from colorama import init, Fore
import os

from src.utils.config import Config
from src.bot.binance_client import BinanceClientWrapper
from src.bot.trade_executor import TradeExecutor
from src.bot.market_data import MarketData
from src.bot.balance_manager import BalanceManager
from src.bot.telegram_handler import TelegramHandler
from strategies.price_drop import PriceDropStrategy
from utils.logger import setup_logger

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
            self.telegram = TelegramHandler(
                self.config.telegram_token,
                self.config.telegram_chat_id,
                self.balance_manager
            )
        else:
            self.telegram = None
            
        self.trade_executor = TradeExecutor(
            self.client.client, 
            self.logger, 
            self.telegram
        )
        self.strategy = PriceDropStrategy(drop_thresholds=drop_thresholds or self.config.drop_thresholds)
        
        # Initialize trading state
        self.initialize_trading_state()
        self.trade_amount = None  # Add trade_amount as instance variable
        self.order_type = None
        self.use_percentage = None

    def test_connection(self):
        """Test connection to Binance API"""
        try:
            for symbol in self.config.trading_symbols:
                ticker = self.client.client.get_symbol_ticker(symbol=symbol)
                price = ticker['price']
                print(Fore.GREEN + f"Connection successful. Current price of {symbol}: {price}")
        except Exception as e:
            print(Fore.RED + f"Error testing connection: {str(e)}")
            self.logger.error(f"Error testing connection: {str(e)}")
            raise

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

        # Initial setup
        self.market_data.print_daily_open_prices()
        self.balance_manager.print_balance_report()

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
        self.market_data.print_daily_open_prices()
        self.last_order_time = {symbol: None for symbol in self.config.trading_symbols}
        self.orders_placed_today = {
            symbol: {threshold: False for threshold in self.strategy.drop_thresholds}
            for symbol in self.config.trading_symbols
        }
        self.max_trades_executed = False

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
            if any(not placed for placed in self.orders_placed_today[symbol].values()):
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
                    if not self.orders_placed_today[symbol][threshold]:
                        print(Fore.MAGENTA + f"Signal generated for {symbol} at threshold {threshold}: BUY at price {price}")
                        self.execute_trade(symbol, price)  # Use the new execute_trade method
                        self.orders_placed_today[symbol][threshold] = True
                        self.logger.info(f"Signal generated for {symbol} at threshold {threshold}: BUY at price {price}")

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

    def execute_trade(self, symbol, price):
        """Execute trade with configured parameters"""
        if self.use_percentage:
            balance = self.balance_manager.get_balance().get('USDT', 0)
            amount = balance * self.trade_amount
        else:
            amount = self.trade_amount
            
        self.trade_executor.execute_trade(
            symbol=symbol,
            quantity=amount / float(price),  # Convert USDT amount to asset quantity
            price=price,
            order_type=self.order_type
        )

if __name__ == "__main__":
    if os.getenv('DOCKER_CONTAINER'):
        # Running inside Docker, use environment variables
        use_testnet = os.getenv('USE_TESTNET').strip().lower() == 'yes'
        use_telegram = os.getenv('USE_TELEGRAM').strip().lower() == 'yes'
        drop_thresholds = [float(x) for x in os.getenv('DROP_THRESHOLDS').split(',')]
        order_type = os.getenv('ORDER_TYPE').strip().lower()
        use_percentage = os.getenv('USE_PERCENTAGE').strip().lower() == 'yes'
        trade_amount = float(os.getenv('TRADE_AMOUNT'))
        usdt_reserve = float(os.getenv('USDT_RESERVE', 200))  # Default reserve amount
    else:
        # Running normally, prompt for input
        use_testnet = input("Do you want to use the testnet? (yes/no): ").strip().lower() == 'yes'
        use_telegram = input("Do you want to use Telegram notifications? (yes/no): ").strip().lower() == 'yes'
        num_thresholds = int(input("Enter the number of drop thresholds: ").strip())
        drop_thresholds = []
        for i in range(num_thresholds):
            while True:
                threshold = float(input(f"Enter drop threshold {i+1} percentage (e.g., 1 for 1%): ").strip()) / 100
                if i == 0 or threshold > drop_thresholds[-1]:  # Changed from < to > for ascending order
                    drop_thresholds.append(threshold)
                    break
                print(f"Threshold {i+1} must be higher than threshold {i}. Please enter a valid value.")
        order_type = input("Do you want to use limit orders or market orders? (limit/market): ").strip().lower()
        use_percentage = input("Do you want to use a percentage of USDT per trade? (yes/no): ").strip().lower() == 'yes'
        if use_percentage:
            trade_amount = float(input("Enter the percentage of USDT to use per trade (e.g., 10 for 10%): ").strip()) / 100
        else:
            trade_amount = float(input("Enter the amount of USDT to use per trade: ").strip())
        usdt_reserve = float(input("Enter the USDT reserve amount (minimum 200): ").strip())
        if usdt_reserve < 200:
            usdt_reserve = 200
            print("USDT reserve set to minimum value of 200")

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
    bot.test_connection()
    print(Fore.CYAN + "\nStarting trading bot...")
    bot.run()