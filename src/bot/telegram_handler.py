from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncio
from queue import Queue
from threading import Thread, Event

class TelegramHandler:
    def __init__(self, token, chat_id, balance_manager, market_data):
        self.token = token
        self.chat_id = chat_id
        self.balance_manager = balance_manager
        self.market_data = market_data
        self.ready = Event()
        self.running = True
        
        self.commands = {
            'balance': 'Get current balance',
            'trades': 'Get total trades count',
            'profits': 'Get current profits',
            'prices': 'Get current prices',
            'positions': 'Get open positions',
            'stats': 'Get trading statistics',
            'sp500': 'Show S&P 500 price'
        }

        self.logger = None  # Initialize logger attribute
        self.loop = None
        self.application = None  # Initialize application attribute

        # Start bot in separate thread
        self.bot_thread = Thread(target=self.run_bot, daemon=True)
        self.bot_thread.start()
        self.ready.wait()  # Wait for bot to initialize

    def run_bot(self):
        """Run the bot with proper event loop handling"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop

            # Create and configure application
            self.app = Application.builder().token(self.token).build()
            self.setup_handlers()

            # Initialize and start bot
            loop.run_until_complete(self.initialize_bot())
            self.ready.set()  # Signal that bot is ready
            
            # Run the event loop
            loop.run_forever()
        except Exception as e:
            print(f"Error in Telegram bot thread: {e}")
            if self.logger:  # Only use logger if it exists
                self.logger.error(f"Error in Telegram bot thread: {e}")
        finally:
            if loop and loop.is_running():
                loop.close()

    async def initialize_bot(self):
        """Initialize bot asynchronously"""
        try:
            await self.app.initialize()
            await self.app.start()
            await self.app.bot.set_my_commands([(cmd, desc) for cmd, desc in self.commands.items()])
            self.application = self.app
            
            # Update the startup sequence
            try:
                await self.app.bot.send_message(
                    chat_id=self.chat_id,
                    text="🤖 Bot started and ready!"
                )
                if self.logger:  # Only use logger if it exists
                    self.logger.info("Telegram bot initialized successfully")
            except Exception as e:
                print(f"Error sending initial message: {e}")
                if self.logger:
                    self.logger.error(f"Error sending initial message: {e}")
            
            await self.app.updater.start_polling(drop_pending_updates=True)
            
        except Exception as e:
            print(f"Error initializing bot: {str(e)}")  # Always print to console
            if self.logger:  # Only use logger if it exists
                self.logger.error(f"Error initializing bot: {str(e)}")
            raise  # Re-raise the exception to properly handle initialization failure

    async def send_message(self, text):
        """Send message asynchronously"""
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as e:
            print(f"Error sending telegram message: {str(e)}")

    def send_message_sync(self, text):
        """Thread-safe message sending"""
        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                # Create a new coroutine for sending the message
                async def send_msg():
                    try:
                        await self.app.bot.send_message(
                            chat_id=self.chat_id,
                            text=text,
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        print(f"Error in async send: {e}")

                # Run the coroutine in the event loop
                future = asyncio.run_coroutine_threadsafe(
                    send_msg(),
                    self.loop
                )
                future.result(timeout=10)
            except Exception as e:
                print(f"Error sending message: {e}")

    async def handle_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        balance_report = self.balance_manager.get_balance()
        if balance_report:
            message = "Current balance:\n" + "\n".join([f"{asset}: {total}" for asset, total in balance_report.items()])
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("Error fetching balance.")

    async def handle_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Total number of trades done: {self.balance_manager.total_trades}")

    async def handle_profits(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        current_prices = {symbol: self.market_data.fetch_current_price(symbol) 
                         for symbol in self.balance_manager.trading_symbols}
        profits = self.balance_manager.get_profits(current_prices)
        if profits:
            profit_message = "\n".join([f"{symbol}: {profit:.2f} USDT" for symbol, profit in profits.items()])
            await update.message.reply_text(f"Current profits:\n{profit_message}")
        else:
            await update.message.reply_text("Error calculating profits.")

    async def handle_prices(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /prices command"""
        try:
            prices = {}
            for symbol in self.balance_manager.trading_symbols:
                price = self.market_data.fetch_current_price(symbol)
                if price:
                    prices[symbol] = price
            
            if prices:
                message = "Current Prices:\n" + "\n".join([f"{symbol}: {price:.8f} USDT" for symbol, price in prices.items()])
                await update.message.reply_text(message)
            else:
                await update.message.reply_text("Error fetching prices.")
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")

    async def handle_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /positions command"""
        try:
            message = "Open Positions:\n\n"
            for symbol, qty in self.balance_manager.total_bought.items():
                if qty > 0:
                    avg_price = self.balance_manager.total_spent[symbol] / qty
                    current_price = self.market_data.fetch_current_price(symbol)
                    if current_price:
                        pnl = (current_price - avg_price) * qty
                        pnl_percent = ((current_price / avg_price) - 1) * 100
                        message += f"{symbol}:\n"
                        message += f"Quantity: {qty:.8f}\n"
                        message += f"Avg Price: {avg_price:.8f}\n"
                        message += f"Current Price: {current_price:.8f}\n"
                        message += f"P&L: {pnl:.2f} USDT ({pnl_percent:.2f}%)\n\n"
            
            await update.message.reply_text(message if message != "Open Positions:\n\n" else "No open positions")
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        try:
            message = "📊 Trading Statistics\n\n"
            message += f"Total Trades: {self.balance_manager.total_trades}\n"
            
            # Calculate total investment and current value
            total_investment = sum(self.balance_manager.total_spent.values())
            current_value = 0
            for symbol, qty in self.balance_manager.total_bought.items():
                if qty > 0:
                    price = self.market_data.fetch_current_price(symbol)
                    if price:
                        current_value += qty * price
            
            if total_investment > 0:
                total_return = ((current_value / total_investment) - 1) * 100
                message += f"Total Investment: {total_investment:.2f} USDT\n"
                message += f"Current Value: {current_value:.2f} USDT\n"
                message += f"Total Return: {total_return:.2f}%"
            
            await update.message.reply_text(message)
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")

    async def handle_sp500(self, update, context):
        """Handle /sp500 command"""
        await update.message.reply_text("Fetching latest S&P 500 data...")
        # The actual SP500 data will be sent through send_message by the tracker

    async def send_market_report(self):
        """Send combined market report including SP500"""
        try:
            balances = self.balance_manager.get_balance()
            
            # Format balance report
            balance_msg = "💰 Current Balance:\n"
            for asset, amount in balances.items():
                balance_msg += f"{asset}: {amount}\n"

            # Format trading pairs prices
            price_msg = "\n📊 Current Prices:\n"
            for symbol in self.market_data.trading_symbols:
                price = self.market_data.get_current_price(symbol)
                if price:
                    price_msg += f"{symbol}: ${float(price):,.2f}\n"

            # Combine messages
            full_report = f"{balance_msg}\n{price_msg}"
            
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=full_report,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error sending market report: {str(e)}")

    def send_message(self, message):
        """Send a message to Telegram channel"""
        if not hasattr(self, 'app') or not self.app:
            print("Telegram bot not yet initialized")
            return

        self.send_message_sync(message)  # Fixed: Changed 'text' to 'message'

    async def _async_send_message(self, text):
        """Internal async method for sending messages"""
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error in async send: {e}")

    def __del__(self):
        """Cleanup"""
        self.running = False
        if hasattr(self, 'app'):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.app.stop(),
                    self.loop
                )
                future.result(timeout=5)
            except Exception as e:
                print(f"Error stopping bot: {e}")

    def setup_handlers(self):
        """Setup command handlers"""
        self.app.add_handler(CommandHandler("balance", self.handle_balance))
        self.app.add_handler(CommandHandler("trades", self.handle_trades))
        self.app.add_handler(CommandHandler("profits", self.handle_profits))
        self.app.add_handler(CommandHandler("prices", self.handle_prices))
        self.app.add_handler(CommandHandler("positions", self.handle_positions))
        self.app.add_handler(CommandHandler("stats", self.handle_stats))
        self.app.add_handler(CommandHandler("sp500", self.handle_sp500))

    def set_logger(self, logger):
        """Set logger after initialization"""
        self.logger = logger
        print("Telegram logger initialized successfully")  # Debug print
