from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram import BotCommand, Update
import telegram.error  # Add this import
import asyncio
from colorama import Fore
import logging
from datetime import datetime, timezone, timedelta
from collections import deque
import queue
import time
import random
import sys

class TelegramHandler:
    def __init__(self, token, chat_id, bot_instance):
        self.token = token
        self.chat_id = chat_id
        self.bot = bot_instance  # Reference to main bot for accessing data
        self.app = Application.builder().token(token).build()
        self.commands_setup = False
        self.logger = logging.getLogger('Telegram')
        self.trade_conv_state = {}  # Add this to track conversation states
        self.command_lock = asyncio.Lock()  # Add lock for commands
        self.command_timeout = 30  # Timeout for commands in seconds
        self.processing_commands = set()  # Track processing commands

        # Add message queue and processing flag
        self.message_queue = asyncio.Queue()
        self.is_processing = False
        self.message_lock = asyncio.Lock()
        self.message_processor_task = None
        self.max_queue_size = 1000
        self.batch_size = 5  # Process messages in small batches
        self.batch_delay = 0.1  # Small delay between batches

        self.command_queue = asyncio.Queue()  # Changed from PriorityQueue to regular Queue
        self.command_workers = 3  # Number of workers processing commands
        self.initialized = False  # Add this flag
        self.message_processor_task = None
        self.command_workers = []  # Add this to track workers
        self.startup_sent = False  # Add flag to track startup message

        self.logger.setLevel(logging.DEBUG)  # Set to DEBUG for more detailed logs
        
        # Add retry parameters
        self.max_retries = 3
        self.base_retry_delay = 1
        self.max_retry_delay = 30
        self.jitter_factor = 0.1
        
        # Add connection status tracking
        self.last_successful_send = 0
        self.consecutive_failures = 0
        self.backoff_until = 0

        self.error_count = 0
        self.max_errors = 10
        self.error_reset_time = time.time()
        self.error_reset_interval = 300  # 5 minutes

        # Add timeout settings
        self.connect_timeout = 30
        self.read_timeout = 30
        self.write_timeout = 30
        self.pool_timeout = 30
        self.command_timeout = 60  # Increased from 30 to 60 seconds
        
        # Add connection health tracking
        self.last_successful_connection = 0
        self.connection_failures = 0
        self.max_failures = 5
        self.backoff_time = 0
        self.connection_check_interval = 300  # 5 minutes

        # Add priority queue
        self.priority_queue = asyncio.PriorityQueue()
        self.normal_queue = asyncio.Queue()
        self.emergency_stop_code = None  # Will be set randomly on startup
        self.emergency_confirmed = False
        
        # Generate random emergency stop code
        self.emergency_stop_code = ''.join(random.choices('0123456789', k=6))
        self.logger.info(f"Emergency stop code generated: {self.emergency_stop_code}")
        self.poll_task = None  # Add this line

    async def send_startup_notification(self):
        """Send startup notification with retries and feedback"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"\r{Fore.CYAN}Sending startup message (attempt {attempt + 1})...", end='')
                startup_msg = self._get_startup_message()
                await self.safe_send_message(
                    startup_msg,
                    parse_mode='HTML',
                    priority=True
                )
                print(f"\r{Fore.GREEN}Startup message sent successfully!{' '*20}")
                self.startup_sent = True
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"\r{Fore.RED}Failed to send startup message: {e}{' '*20}")
                    self.logger.error(f"Failed to send startup notification: {e}")
                await asyncio.sleep(2)

    async def initialize(self):
        """Initialize Telegram bot with improved error handling"""
        try:
            if self.initialized:
                return True

            print(f"{Fore.CYAN}Starting Telegram initialization...")
            self.logger.info("Initializing Telegram bot...")
            
            try:
                # Build and start application first
                self.app = Application.builder().token(self.token).build()
                
                # Initialize and register handlers
                await self.app.initialize()
                self.register_handlers()
                
                # Start the application
                await self.app.start()
                
                # Start polling with error handling
                polling_task = self.app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                    error_callback=self._polling_error_callback
                )
                
                # Create polling task
                self.poll_task = asyncio.create_task(polling_task)
                
                # Test connection
                test_response = await self.app.bot.get_me()
                if not test_response:
                    raise Exception("Failed to connect to Telegram")
                    
                print(f"{Fore.GREEN}Telegram bot connected: @{test_response.username}")
                
                # Set initialized flag
                self.initialized = True
                
                # Start message processor
                self.message_processor_task = asyncio.create_task(
                    self._process_message_queue()
                )

                # Send startup message with visible feedback
                print(f"{Fore.CYAN}Sending startup notification...")
                await self.send_startup_notification()
                print(f"{Fore.GREEN}Startup notification sent!")
                
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to initialize Telegram: {e}")
                print(f"{Fore.RED}Telegram initialization failed: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Fatal error during Telegram initialization: {e}")
            print(f"{Fore.RED}Fatal Telegram error: {e}")
            return False

    async def _process_commands(self):
        """Process commands with high priority"""
        while True:
            try:
                _, command = await self.command_queue.get()
                try:
                    await command()
                finally:
                    self.command_queue.task_done()
            except Exception as e:
                self.logger.error(f"Command processing error: {e}")
                await asyncio.sleep(1)

    async def handle_command_wrapper(self, handler, update, context):
        """Handle commands immediately without queueing"""
        try:
            command = update.message.text.split()[0][1:]
            
            if command in self.processing_commands:
                await self.send_message("Command already processing, please wait...")
                return

            self.logger.debug(f"Processing command: {command}")
            self.processing_commands.add(command)
            
            try:
                await self.app.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action="typing"
                )
                await handler(update, context)
            finally:
                self.processing_commands.discard(command)
                
        except Exception as e:
            self.logger.exception(f"Error in command {command}: {e}")
            await self.send_message(
                f"Error processing command. Please try again."
            )

    async def _execute_command(self, handler, update, context, command):
        """Execute command with enhanced logging"""
        try:
            self.processing_commands.add(command)
            self.logger.info(f"Executing command: {command}")
            
            async with self.command_lock:
                await self.app.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action="typing"
                )
                
                # Execute command with timeout
                try:
                    await asyncio.wait_for(
                        handler(update, context),
                        timeout=self.command_timeout
                    )
                    self.logger.info(f"Command completed successfully: {command}")
                except asyncio.TimeoutError:
                    self.logger.error(f"Command timed out: {command}")
                    await self.send_message(f"Command {command} timed out. Please try again.")
                    
        except Exception as e:
            self.logger.exception(f"Error executing command {command}: {e}")
            await self.send_message(
                f"Error processing command {command}. Please try again."
            )
        finally:
            self.processing_commands.discard(command)

    def register_handlers(self):
        """Register command handlers with improved error handling"""
        try:
            if not hasattr(self, 'app') or not self.app:
                self.logger.error("Cannot register handlers - application not initialized")
                return

            # Clear existing handlers
            if hasattr(self.app, 'handlers'):
                self.app.handlers.clear()

            # Register handlers
            handlers = {
                "start": self.handle_start,
                "positions": self.handle_positions,
                "balance": self.handle_balance,
                "profits": self.handle_profits,
                "stats": self.handle_stats,
                "distribution": self.handle_distribution,
                "stacking": self.handle_stacking,
                "buytimes": self.handle_buy_times,
                "portfolio": self.handle_portfolio,
                "allocation": self.handle_allocation,
                "orders": self.handle_orders,
                "trade": self.handle_trade,
                "trades": self.handle_trades_list,
                "symbol": self.handle_symbol_stats,
                "summary": self.handle_portfolio_summary,
                "addtrade": self.handle_addtrade,
                "emergency": self.handle_emergency_stop,  # Add emergency stop handler
            }

            for command, handler in handlers.items():
                try:
                    self.app.add_handler(CommandHandler(command, self._wrap_handler(handler)))
                except Exception as e:
                    self.logger.error(f"Failed to register handler for {command}: {e}")

            # Add message handler
            try:
                self.app.add_handler(MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    self.handle_message
                ))
            except Exception as e:
                self.logger.error(f"Failed to register message handler: {e}")

            self.logger.info("Command handlers registered successfully")

        except Exception as e:
            self.logger.error(f"Error registering handlers: {e}")
            raise

    def _wrap_handler(self, handler):
        """Enhanced command handler wrapper with timeout and retry logic"""
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                if not self.initialized:
                    await self.safe_send_message("Bot is still initializing, please wait...")
                    return

                command = update.message.text.split()[0][1:]
                self.logger.debug(f"Processing command: {command}")
                
                # Check connection health before proceeding
                if not await self._check_connection():
                    await self.safe_send_message(
                        "⚠️ Connection issues detected. Command processing may be delayed.",
                        priority=True
                    )
                
                # Send typing action with retry
                for attempt in range(3):
                    try:
                        await self.app.bot.send_chat_action(
                            chat_id=update.effective_chat.id,
                            action="typing",
                            read_timeout=self.read_timeout,
                            write_timeout=self.write_timeout,
                            connect_timeout=self.connect_timeout,
                            pool_timeout=self.pool_timeout
                        )
                        break
                    except telegram.error.TimedOut:
                        if attempt == 2:
                            self.logger.warning("Failed to send typing action after 3 attempts")
                        await asyncio.sleep(1)
                    except Exception as e:
                        self.logger.error(f"Error sending typing action: {e}")
                        break

                # Execute command with timeout
                try:
                    result = await asyncio.wait_for(
                        handler(update, context),
                        timeout=self.command_timeout
                    )
                    # Update connection health on success
                    self.last_successful_connection = time.time()
                    self.connection_failures = 0
                    return result
                    
                except asyncio.TimeoutError:
                    error_msg = f"Command {command} timed out. Please try again."
                    self.logger.error(f"Command timeout: {command}")
                    await self.safe_send_message(error_msg)
                    self.connection_failures += 1
                    
            except Exception as e:
                self.logger.exception(f"Error in command {update.message.text}: {e}")
                await self.safe_send_message(
                    f"Error processing command. Please try again later."
                )
                self.connection_failures += 1
                
        return wrapped

    async def queue_message(self, text, parse_mode=None, reply_markup=None, priority=False):
        """Queue message for sending with optional priority"""
        try:
            if self.message_queue.qsize() >= self.max_queue_size:
                self.logger.warning("Message queue full, dropping oldest message")
                await self.message_queue.get()
            
            message_data = {
                'text': text,
                'parse_mode': parse_mode,
                'reply_markup': reply_markup,
                'priority': priority,
                'timestamp': datetime.now(timezone.utc)
            }
            
            await self.message_queue.put(message_data)
            
        except Exception as e:
            self.logger.error(f"Error queuing message: {e}")

    async def _process_message_queue(self):
        """Enhanced message queue processor with priority handling"""
        while True:
            try:
                # Check priority queue first
                if not self.priority_queue.empty():
                    priority, msg_data = await self.priority_queue.get()
                    try:
                        await self._send_with_retry(
                            text=msg_data['text'],
                            parse_mode=msg_data.get('parse_mode'),
                            reply_markup=msg_data.get('reply_markup')
                        )
                    finally:
                        self.priority_queue.task_done()
                    continue

                # Then check normal queue
                try:
                    msg_data = await asyncio.wait_for(
                        self.normal_queue.get(),
                        timeout=0.1
                    )
                    await self._send_with_retry(
                        text=msg_data['text'],
                        parse_mode=msg_data.get('parse_mode'),
                        reply_markup=msg_data.get('reply_markup')
                    )
                    self.normal_queue.task_done()
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                self.logger.error(f"Error in message processor: {e}")
                await asyncio.sleep(1)

    async def send_message(self, text, parse_mode=None, reply_markup=None, priority=False, **kwargs):
        """Enhanced message sending with logging"""
        if not text or not self.initialized:
            return None

        message_data = {
            'text': text,
            'chat_id': self.chat_id,
            'parse_mode': parse_mode,
            'reply_markup': reply_markup,
            **kwargs
        }

        try:
            self.logger.debug(
                "Sending Telegram message",
                extra={
                    'details': f"Priority: {priority}\nMessage: {text[:200]}..."
                }
            )

            if priority:
                await self.priority_queue.put((1, message_data))
            else:
                await self.normal_queue.put(message_data)
                
            self.logger.debug(
                "Message queued successfully",
                extra={
                    'details': f"Queue size: {self.normal_queue.qsize()}"
                }
            )
                
        except Exception as e:
            self.logger.error(
                "Error queuing message",
                extra={
                    'details': f"Error: {str(e)}\nMessage: {text[:200]}..."
                }
            )

    async def _send_with_retry(self, text, parse_mode=None, reply_markup=None):
        """Send message with retries and proper error handling"""
        for attempt in range(self.max_retries):
            try:
                return await self.app.bot.send_message(
                    chat_id=self.chat_id,  # Use instance chat_id instead of parameter
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    read_timeout=10,
                    write_timeout=10,
                    connect_timeout=10,
                    pool_timeout=10
                )
            except telegram.error.NetworkError as e:
                if attempt == self.max_retries - 1:
                    raise
                delay = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except telegram.error.RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(1)

    async def safe_send_message(self, text, priority=False, **kwargs):
        """Send message with enhanced safety and retry logic"""
        if not text or not self.initialized:
            return None
            
        if time.time() < self.backoff_time:
            if priority:
                self.logger.warning("High priority message during backoff period")
            else:
                await self.queue_message(text, priority=priority, **kwargs)
                return None

        for attempt in range(self.max_retries):
            try:
                # Split long messages
                if len(text) > 4096:
                    chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
                    responses = []
                    for chunk in chunks:
                        response = await self.app.bot.send_message(
                            chat_id=self.chat_id,
                            text=chunk,
                            read_timeout=self.read_timeout,
                            write_timeout=self.write_timeout,
                            connect_timeout=self.connect_timeout,
                            pool_timeout=self.pool_timeout,
                            **kwargs
                        )
                        responses.append(response)
                        await asyncio.sleep(0.5)  # Small delay between chunks
                    return responses[-1]
                else:
                    return await self.app.bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        read_timeout=self.read_timeout,
                        write_timeout=self.write_timeout,
                        connect_timeout=self.connect_timeout,
                        pool_timeout=self.pool_timeout,
                        **kwargs
                    )
                    
            except telegram.error.TimedOut:
                self.connection_failures += 1
                delay = min(30, (2 ** attempt))
                self.logger.warning(f"Message timed out, retrying in {delay}s")
                await asyncio.sleep(delay)
                
            except Exception as e:
                self.logger.error(f"Error sending message: {e}")
                if attempt == self.max_retries - 1:
                    await self.queue_message(text, priority=priority, **kwargs)
                    return None
                await asyncio.sleep(1)

        return None

    async def _check_connection(self):
        """Check Telegram connection health"""
        current_time = time.time()
        
        # Reset failures if enough time has passed
        if current_time - self.last_successful_connection > self.connection_check_interval:
            self.connection_failures = 0
            
        # Implement exponential backoff if too many failures
        if self.connection_failures >= self.max_failures:
            backoff_duration = min(300, (2 ** (self.connection_failures - self.max_failures)) * 30)
            self.backoff_time = current_time + backoff_duration
            self.logger.warning(f"Too many connection failures. Backing off for {backoff_duration}s")
            return False
            
        return True

    # Update API handler references in handle_positions method
    async def handle_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show trading positions with thresholds and reset times"""
        try:
            # Send loading message and store the message object
            loading_msg = await self.safe_send_message("📊 Fetching positions...")

            positions = []
            now = datetime.now(timezone.utc)
            
            # Check API handler connection
            if not self.bot.api_handler or not self.bot.api_handler.is_running:
                await self.safe_send_message(
                    "❌ Price monitoring not connected. Reconnecting...",
                    priority=True
                )
                return
            
            # Use cached prices with shorter timeout
            try:
                async with asyncio.timeout(5):
                    cached_prices = self.bot.api_handler.last_prices
                    if not cached_prices:
                        await self.safe_send_message(
                            "❌ No price data available. Please try again in a few seconds."
                        )
                        return
            except asyncio.TimeoutError:
                await self.safe_send_message(
                    "❌ Timeout while fetching prices. Please try again."
                )
                return

            # Process symbols in smaller batches
            batch_size = 4
            for i in range(0, len(self.bot.valid_symbols), batch_size):
                batch_symbols = sorted(self.bot.valid_symbols[i:i+batch_size])
                
                # Process batch concurrently with timeout
                try:
                    async with asyncio.timeout(10):  # 10 second timeout per batch
                        tasks = [self._process_symbol_position(symbol, cached_prices, now) 
                                for symbol in batch_symbols]
                        batch_results = await asyncio.gather(*tasks)
                        positions.extend([r for r in batch_results if r])
                except asyncio.TimeoutError:
                    self.logger.warning(f"Timeout processing batch starting with {batch_symbols[0]}")
                    continue

            # Format and send message
            if positions:
                message = "🎯 Trading Positions & Thresholds:\n\n"
                message += "Legend:\n"
                message += "⚪ Not Triggered | 🟡 Triggered | ✅ Available | 🔒 Locked\n\n"
                message += "\n".join(positions)
                message += f"\n\nLast Update: {now.strftime('%H:%M:%S UTC')}"

                # Send in chunks if needed
                await self.safe_send_message(message)
            else:
                await self.safe_send_message("❌ No position data available")

        except Exception as e:
            self.logger.error(f"Error fetching positions: {e}", exc_info=True)
            await self.safe_send_message(f"❌ Error fetching positions: {str(e)}")

    async def _process_symbol_position(self, symbol, cached_prices, now):
        """Process single symbol position data"""
        try:
            price_data = cached_prices.get(symbol, {})
            if not price_data:
                return f"⚪ {symbol}: No price data"

            price = price_data.get('price', 0)
            change = price_data.get('change', 0)
            arrow = "↑" if change >= 0 else "↓"
            color = "🟢" if change >= 0 else "🔴"

            ref_prices = self.bot.get_reference_prices(symbol)
            symbol_info = [f"{color} {symbol}: {price:.8f} ({change:+.2f}%) {arrow}"]

            for timeframe in ['daily', 'weekly', 'monthly']:
                if not self.bot.timeframe_config[timeframe]['enabled']:
                    continue

                current_drop = self._calculate_price_drop(
                    ref_prices.get(timeframe, {}).get('open', 0),
                    price
                )
                
                if current_drop is not None:
                    threshold_status = self._get_threshold_status(
                        symbol, timeframe, current_drop, now
                    )
                    symbol_info.extend([
                        f"  {timeframe.capitalize()}: {current_drop:+.2f}%",
                        f"    Thresholds: {' | '.join(threshold_status)}"
                    ])

            return "\n".join(symbol_info)

        except Exception as e:
            self.logger.error(f"Error processing {symbol} position: {e}")
            return None

    def _calculate_price_drop(self, ref_price, current_price):
        """Calculate price drop percentage"""
        try:
            if ref_price and ref_price > 0:
                return ((ref_price - current_price) / ref_price) * 100
            return None
        except Exception:
            return None

    def _get_threshold_status(self, symbol, timeframe, current_drop, now):
        """Get threshold status with proper error handling"""
        try:
            thresholds = self.bot.timeframe_config[timeframe]['thresholds']
            status = []
            
            for threshold in thresholds:
                threshold_pct = threshold * 100
                status.append(self._format_threshold_status(
                    symbol, timeframe, threshold, threshold_pct,
                    current_drop, now
                ))
            
            return status
        except Exception as e:
            self.logger.error(f"Error getting threshold status: {e}")
            return ["⚠️ Error"]

    def _format_threshold_status(self, symbol, timeframe, threshold, threshold_pct, 
                               current_drop, now):
        """Format single threshold status"""
        try:
            # Check if threshold is locked
            if (symbol in self.bot.strategy.order_history[timeframe] and 
                threshold in self.bot.strategy.order_history[timeframe][symbol]):
                
                last_order = self.bot.strategy.order_history[timeframe][symbol][threshold]
                reset_time = self._get_reset_time(last_order, timeframe)
                
                if now < reset_time:
                    time_left = reset_time - now
                    hours = int(time_left.total_seconds() / 3600)
                    mins = int((time_left.total_seconds() % 3600) / 60)
                    return f"🔒 {threshold_pct:.1f}% ({hours}h {mins}m)"
                    
                return f"✅ {threshold_pct:.1f}%"
                    
            # Not locked - check if triggered
            return f"🟡 {threshold_pct:.1f}%" if current_drop >= threshold_pct else f"⚪ {threshold_pct:.1f}%"
            
        except Exception as e:
            self.logger.error(f"Error formatting threshold: {e}")
            return f"⚠️ {threshold_pct:.1f}%"

    def _get_reset_time(self, last_order, timeframe):
        """Calculate reset time based on timeframe"""
        if timeframe == 'daily':
            return last_order + timedelta(days=1)
        elif timeframe == 'weekly':
            return last_order + timedelta(days=7)  # Fix: Remove days() function call
        else:  # monthly
            return last_order + timedelta(days=30)

    async def handle_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show balance info"""
        try:
            balance = self.bot.get_balance()
            if balance:
                # Filter and format significant balances
                
                significant_balances = []
                
                # Always show USDT first
                if 'USDT' in balance:
                    significant_balances.append(f"USDT: {balance['USDT']['total']:.2f}")
                
                # Add other significant balances
                for asset, details in balance.items():
                    if asset != 'USDT' and details['total'] > 0:
                        # Format with appropriate precision
                        if details['total'] < 1:
                            significant_balances.append(f"{asset}: {details['total']:.8f}")
                        else:
                            significant_balances.append(f"{asset}: {details['total']:.3f}")
                
                message = "💰 Current Balance:\n\n" + "\n".join(significant_balances)
                await self.send_message(message)
            else:
                await self.send_message("❌ Error fetching balance")
        except Exception as e:
            await self.send_message(f"❌ Error: {e}")

    async def handle_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show total trades"""
        await self.send_message(f"Total trades: {self.bot.total_trades}")

    async def handle_profits(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show profits"""
        message = "📈 Profit Summary:\n"
        # Add profit calculation logic here
        await self.send_message(message)

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system stats"""
        stats = f"🤖 Bot Statistics:\n\nUptime: {datetime.now() - self.bot.start_time}\n"
        await self.send_message(stats)

    async def handle_distribution(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show price distribution"""
        await self.send_message("📊 Price distribution analysis coming soon")

    async def handle_stacking(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show position stacking"""
        await self.send_message("📈 Position stacking analysis coming soon")

    async def handle_buy_times(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show buy times analysis"""
        await self.send_message("⏰ Buy times analysis coming soon")

    async def handle_portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show portfolio evolution"""
        await self.send_message("💼 Portfolio evolution coming soon")

    async def handle_allocation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show asset allocation"""
        await self.send_message("📊 Asset allocation analysis coming soon")

    async def handle_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show open orders"""
        try:
            message = "📋 Open Orders:\n\n"
            for order_id, order in self.bot.pending_orders.items():
                cancel_time = datetime.fromisoformat(order['cancel_time'])
                message += (f"ID: {order_id}\n"
                          f"Symbol: {order['symbol']}\n"
                          f"Price: {order['price']} USDT\n"
                          f"Quantity: {order['quantity']}\n"
                          f"Cancels at: {cancel_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n")
            
            if not self.bot.pending_orders:
                message += "No open orders"
                
            await self.send_message(message)
        except Exception as e:
            await self.send_message(f"❌ Error fetching orders: {e}")

    async def handle_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show specific trade details"""
        try:
            # Check if trade ID was provided
            if not context.args or len(context.args) != 1:
                await self.send_message("❌ Please provide a trade ID\nExample: /trade BOT_20250120232418_SOLUSDT_1")
                return

            trade_id = context.args[0]
            trade = await self.bot.get_trade_profit(trade_id)
            
            if not trade:
                await self.send_message(f"❌ Trade not found: {trade_id}")
                return
            
            # Format trade details
            message = (
                f"📊 Trade Details [ID: {trade_id}]\n\n"
                f"Symbol: {trade['symbol']}\n"
                f"Entry Price: {trade['entry_price']:.8f} USDT\n"
                f"Quantity: {trade['quantity']:.8f}\n"
                f"Total Cost: {trade['total_cost']:.2f} USDT\n\n"
                f"Current Value: {trade['current_value']:.2f} USDT\n"
                f"Last Price: {trade['last_price']:.8f} USDT\n"
                f"Profit/Loss: {trade['profit_usdt']:+.2f} USDT ({trade['profit_percentage']:+.2f}%)\n"
                f"Status: {trade['status']}\n"
                f"Filled: {trade['filled_time']}\n"
                f"Last Update: {trade['last_update']}"
            )
            
            await self.send_message(message)
            
        except Exception as e:
            await self.send_message(f"❌ Error fetching trade: {e}")

    async def handle_trades_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of all trades with tax calculations"""
        try:
            if not self.bot.trades:
                await self.send_message("No trades found")
                return

            # Group trades by symbol
            trades_by_symbol = {}
            for trade_id, trade in self.bot.trades.items():
                symbol = trade['symbol']
                if symbol not in trades_by_symbol:
                    trades_by_symbol[symbol] = []
                trades_by_symbol[symbol].append(trade_id)

            message = "📈 Trading History by Symbol:\n\n"
            
            # Process each symbol
            for symbol in sorted(trades_by_symbol.keys()):
                stats = await self.bot.get_symbol_stats(symbol)
                if stats:
                    profit_color = "🟢" if stats['net_profit_usdt'] >= 0 else "🔴"
                    message += (
                        f"{profit_color} {symbol}\n"
                        f"   Trades: {stats['number_of_trades']}\n"
                        f"   Avg Entry: {stats['average_price']:.8f}\n"
                        f"   Net P/L: {stats['net_profit_usdt']:+.2f} USDT "
                        f"({stats['net_profit_percentage']:+.2f}%) after tax\n\n"
                    )

            message += "\nUse /symbol <SYMBOL> for detailed statistics"
            await self.send_message(message)
            
        except Exception as e:
            await self.send_message(f"❌ Error fetching trades: {e}")

    async def handle_symbol_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show symbol statistics including tax calculations"""
        try:
            if not context.args or len(context.args) != 1:
                await self.send_message("❌ Please provide a symbol\nExample: /symbol BTCUSDT")
                return

            symbol = context.args[0].upper()
            if symbol not in self.bot.valid_symbols:
                await self.send_message(f"❌ Invalid symbol: {symbol}")
                return

            stats = await self.bot.get_symbol_stats(symbol)
            if not stats:
                await self.send_message(f"No trades found for {symbol}")
                return

            # Format message with detailed statistics
            message = (
                f"📊 {symbol} Trading Summary\n\n"
                f"Position Size: {stats['total_quantity']:.8f}\n"
                f"Total Cost: {stats['total_cost']:.2f} USDT\n"
                f"Average Entry: {stats['average_price']:.8f} USDT\n\n"
                f"Current Price: {stats['current_price']:.8f} USDT\n"
                f"Current Value: {stats['current_value']:.2f} USDT\n\n"
                f"Gross P/L: {stats['gross_profit_usdt']:+.2f} USDT "
                f"({stats['gross_profit_percentage']:+.2f}%)\n"
                f"Tax (28%): {stats['tax_amount']:.2f} USDT\n"
                f"Net P/L: {stats['net_profit_usdt']:+.2f} USDT "
                f"({stats['net_profit_percentage']:+.2f}%)\n\n"
                f"Number of Trades: {stats['number_of_trades']}\n"
                f"Last Update: {stats['last_update']}"
            )

            await self.send_message(message)

        except Exception as e:
            await self.send_message(f"❌ Error getting symbol stats: {e}")

    async def handle_portfolio_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show summary of all trades and total portfolio performance"""
        try:
            if not self.bot.trades:
                await self.send_message("No trades found")
                return

            # Calculate totals
            total_investment = 0
            total_current_value = 0
            total_gross_profit = 0
            symbol_summaries = []

            # Process each symbol
            for symbol in sorted(set(trade['symbol'] for trade in self.bot.trades.values())):
                stats = await self.bot.get_symbol_stats(symbol)
                if stats:
                    total_investment += stats['total_cost']
                    total_current_value += stats['current_value']
                    total_gross_profit += stats['gross_profit_usdt']
                    symbol_summaries.append(stats)

            # Calculate portfolio totals
            total_tax = total_gross_profit * self.bot.tax_rate if total_gross_profit > 0 else 0
            total_net_profit = total_gross_profit - total_tax if total_gross_profit > 0 else total_gross_profit
            total_profit_percentage = (total_net_profit / total_investment * 100) if total_investment > 0 else 0

            # Format message
            message = "📊 Portfolio Summary\n\n"
            
            # Overall summary
            message += f"💼 Total Portfolio:\n"
            message += f"Investment: {total_investment:.2f} USDT\n"
            message += f"Current Value: {total_current_value:.2f} USDT\n"
            message += f"Gross P/L: {total_gross_profit:+.2f} USDT\n"
            message += f"Tax (28%): {total_tax:.2f} USDT\n"
            message += f"Net P/L: {total_net_profit:+.2f} USDT ({total_profit_percentage:+.2f}%)\n\n"
            
            # Individual symbols
            message += "📈 By Symbol:\n"
            for stats in symbol_summaries:
                profit_color = "🟢" if stats['net_profit_usdt'] >= 0 else "🔴"
                message += (
                    f"{profit_color} {stats['symbol']}\n"
                    f"   Cost: {stats['total_cost']:.2f} USDT\n"
                    f"   Value: {stats['current_value']:.2f} USDT\n"
                    f"   Net P/L: {stats['net_profit_usdt']:+.2f} USDT ({stats['net_profit_percentage']:+.2f}%)\n"
                    f"   Trades: {stats['number_of_trades']}\n\n"
                )

            message += "\nUse /symbol <SYMBOL> for detailed symbol statistics"
            await self.send_message(message)
            
        except Exception as e:
            await self.send_message(f"❌ Error getting portfolio summary: {e}")

    async def handle_addtrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addtrade command with step-by-step interaction"""
        chat_id = update.effective_chat.id
        
        # Initialize or reset conversation state
        self.trade_conv_state[chat_id] = {
            'step': 'symbol',
            'symbol': None,
            'entry_price': None,
            'quantity': None
        }
        
        # Start conversation
        await self.send_message(
            "Let's add a manual trade! 📝\n\n"
            "Please enter the trading pair symbol (e.g., BTCUSDT):"
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle conversation messages for adding trades"""
        chat_id = update.effective_chat.id
        text = update.message.text
        
        if chat_id not in self.trade_conv_state:
            return
            
        state = self.trade_conv_state[chat_id]
        
        try:
            if state['step'] == 'symbol':
                symbol = text.upper()
                if not symbol.endswith('USDT'):
                    await self.send_message("❌ Only USDT pairs are supported (e.g., BTCUSDT)\nPlease try again:")
                    return
                    
                state['symbol'] = symbol
                state['step'] = 'entry_price'
                await self.send_message(f"✅ Symbol: {symbol}\n\nPlease enter the entry price in USDT:")
                
            elif state['step'] == 'entry_price':
                entry_price = float(text)
                if entry_price <= 0:
                    await self.send_message("❌ Entry price must be greater than 0\nPlease try again:")
                    return
                    
                state['entry_price'] = entry_price
                state['step'] = 'quantity'
                await self.send_message(
                    f"✅ Entry Price: {entry_price:.8f} USDT\n\n"
                    f"Please enter the quantity of {state['symbol'].replace('USDT', '')}:"
                )
                
            elif state['step'] == 'quantity':
                quantity = float(text)
                if quantity <= 0:
                    await self.send_message("❌ Quantity must be greater than 0\nPlease try again:")
                    return
                
                # Calculate total cost
                total_cost = state['entry_price'] * quantity
                
                # Show summary and confirmation
                confirm_msg = (
                    "📋 Trade Summary\n\n"
                    f"Symbol: {state['symbol']}\n"
                    f"Entry Price: {state['entry_price']:.8f} USDT\n"
                    f"Quantity: {quantity:.8f}\n"
                    f"Total Cost: {total_cost:.2f} USDT\n\n"
                    "Is this correct? Type 'yes' to confirm or 'no' to cancel:"
                )
                
                state['quantity'] = quantity
                state['step'] = 'confirm'
                await self.send_message(confirm_msg)
                
            elif state['step'] == 'confirm':
                if text.lower() == 'yes':
                    # Generate trade ID
                    trade_id = f"MANUAL_{datetime.now().strftime('%Y%m%d%H%M%S')}_{state['symbol']}"
                    
                    # Create trade entry
                    trade_entry = {
                        'symbol': state['symbol'],
                        'entry_price': state['entry_price'],
                        'quantity': state['quantity'],
                        'total_cost': state['entry_price'] * state['quantity'],
                        'type': 'manual',
                        'status': 'FILLED',
                        'filled_time': datetime.now(timezone.utc).isoformat()
                    }
                    
                    # Add to trades
                    self.bot.trades[trade_id] = trade_entry
                    self.bot.save_trades()
                    
                    await self.send_message(f"✅ Trade added successfully!\nTrade ID: {trade_id}")
                    
                elif text.lower() == 'no':
                    await self.send_message("❌ Trade cancelled. Use /addtrade to start over.")
                else:
                    await self.send_message("Please type 'yes' to confirm or 'no' to cancel:")
                    return
                    
                # Clear conversation state
                del self.trade_conv_state[chat_id]
                
        except ValueError:
            await self.send_message("❌ Invalid number format. Please enter a valid number:")
        except Exception as e:
            await self.send_message(f"❌ Error: {str(e)}\nUse /addtrade to start over.")
            del self.trade_conv_state[chat_id]

    async def handle_emergency_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle emergency stop command"""
        try:
            if not context.args:
                # First confirmation step
                message = (
                    "⚠️ EMERGENCY STOP REQUESTED\n\n"
                    "This will:\n"
                    "1. Cancel all open orders\n"
                    "2. Stop all trading activities\n"
                    "3. Close WebSocket connections\n\n"
                    f"To confirm, use:\n/emergency {self.emergency_stop_code}"
                )
                await self.send_message(message, priority=True)
                return

            if context.args[0] == self.emergency_stop_code:
                self.emergency_confirmed = True
                
                # Send high priority notification
                await self.send_message(
                    "🚨 EMERGENCY STOP CONFIRMED\nInitiating shutdown...",
                    priority=True
                )
                
                # Cancel all orders
                await self.bot.cancel_all_orders()
                
                # Stop WebSocket
                if self.bot.ws_manager:
                    await self.bot.ws_manager.stop()
                
                # Final confirmation
                await self.send_message(
                    "✅ Emergency stop completed:\n"
                    "• All orders cancelled\n"
                    "• Trading stopped\n"
                    "• Connections closed",
                    priority=True
                )
                
                # Initiate bot shutdown
                asyncio.create_task(self.bot.shutdown())
            else:
                await self.send_message(
                    "❌ Invalid emergency code. Command cancelled.",
                    priority=True
                )
        except Exception as e:
            self.logger.error(f"Error in emergency stop: {e}")
            await self.send_message(
                "❌ Error executing emergency stop",
                priority=True
            )

    async def shutdown(self):
        """Enhanced shutdown with proper task cleanup"""
        try:
            if not self.initialized:
                return

            self.logger.info("Shutting down Telegram bot...")
            
            try:
                # Cancel polling task first
                if self.poll_task:
                    self.poll_task.cancel()
                    try:
                        await self.poll_task
                    except asyncio.CancelledError:
                        pass

                # Cancel message processor
                if self.message_processor_task:
                    self.message_processor_task.cancel()
                    try:
                        await self.message_processor_task
                    except asyncio.CancelledError:
                        pass

                # Stop the application
                if self.app.running:
                    await self.app.stop()
                    await self.app.shutdown()
                    
                self.initialized = False
                self.logger.info("Telegram bot shutdown complete")
                
            except Exception as e:
                self.logger.error(f"Error during shutdown: {e}")
                
        except Exception as e:
            self.logger.error(f"Fatal error during shutdown: {e}")
        finally:
            self.initialized = False

    async def _polling_error_callback(self, error):
        """Handle polling errors"""
        self.logger.error(f"Polling error: {error}")
        
        # Try to restart polling if it fails
        if self.initialized and not self.poll_task.done():
            self.poll_task.cancel()
            self.poll_task = asyncio.create_task(
                self.app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                    error_callback=self._polling_error_callback
                )
            )

    def _get_startup_message(self):
        """Generate startup message"""
        startup_msg = (
            "🤖 Binance Trading Bot Started!\n\n"
            "📈 Trading Configuration:\n"
            f"• Mode: {'Testnet' if self.bot.client.API_URL == 'https://testnet.binance.vision/api' else 'Live'}\n"
            f"• Order Type: {self.bot.order_type.capitalize()}\n"
            f"• Trading Pairs: {', '.join(self.bot.valid_symbols)}\n"
            f"• USDT Reserve: {self.bot.reserve_balance_usdt}\n"
            f"• Tax Rate: 28%\n\n"
            "📊 Available Commands:\n\n"
            "Market Analysis:\n"
            "/positions - Show current prices and opportunities\n"
            "/orders - Show open limit orders\n\n"
            "Portfolio Management:\n"
            "/balance - Show current balance\n"
            "/trades - List all trades with P/L\n"
            "/addtrade - Add manual trade\n"
            "/symbol <SYMBOL> - Show detailed stats\n"
            "/summary - Show portfolio summary\n\n"
            "Analytics:\n"
            "/profits - Show current profits\n"
            "/distribution - Show entry distribution\n"
            "/stacking - Show position building\n"
            "/buytimes - Show trade timing\n"
            "/portfolio - Show value evolution\n"
            "/allocation - Show asset allocation\n\n"
            "System:\n"
            "/stats - Show system information\n\n"
            "🟢 Bot is actively monitoring markets!"
        )
        return startup_msg

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_msg = (
            "👋 Welcome to the Binance Trading Bot!\n\n"
            "Available commands:\n\n"
            "Market Analysis:\n"
            "/positions - Show current prices and opportunities\n"
            "/orders - Show open limit orders\n\n"
            "Portfolio Management:\n"
            "/balance - Show current balance\n"
            "/trades - List all trades with P/L\n"
            "/addtrade - Add manual trade\n"
            "/symbol <SYMBOL> - Show detailed stats\n"
            "/summary - Show portfolio summary\n\n"
            "Analytics:\n"
            "/profits - Show current profits\n"
            "/distribution - Show entry distribution\n"
            "/stacking - Show position building\n"
            "/buytimes - Show trade timing\n"
            "/portfolio - Show value evolution\n"
            "/allocation - Show asset allocation\n\n"
            "System:\n"
            "/stats - Show system information"
        )
        await self.send_message(welcome_msg)

