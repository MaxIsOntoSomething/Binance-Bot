from binance.enums import *
from colorama import Fore
import time
from threading import Thread
from queue import Queue
from datetime import datetime, timedelta  # Add this import

class TradeExecutor:
    def __init__(self, binance_wrapper, logger, telegram_handler=None, balance_manager=None):  # Add balance_manager
        self.client = binance_wrapper  # This is now the wrapper, not the raw client
        self.logger = logger
        self.telegram = telegram_handler
        self.price_precision = {}
        self.init_price_precision()
        self.order_type = None
        self.use_percentage = None
        self.trade_amount = None
        self.order_times = {}  # Track order times
        self.pending_orders = {}  # Track pending limit orders
        self.order_monitor_thread = None
        self.stop_monitoring = False
        self.start_order_monitor()
        self.balance_manager = balance_manager
        self.orders_in_progress = 0
        self.daily_order_count = {}  # Track number of orders per symbol per threshold
        self.order_cleanup_thread = None
        self.start_order_cleanup()

    def configure_trading_params(self, order_type, use_percentage, trade_amount):
        self.order_type = order_type
        self.use_percentage = use_percentage
        self.trade_amount = trade_amount

    def init_price_precision(self):
        """Initialize price precision for all symbols"""
        try:
            info = self.client.get_exchange_info()
            for symbol_info in info['symbols']:
                for filter in symbol_info['filters']:
                    if filter['filterType'] == 'PRICE_FILTER':
                        self.price_precision[symbol_info['symbol']] = self.get_precision(filter['tickSize'])
        except Exception as e:
            self.logger.error(f"Error getting price precision: {e}")

    def get_precision(self, tick_size):
        """Get decimal precision from tick size"""
        tick_size_str = f"{float(tick_size):.8f}"
        return len(tick_size_str.split('.')[-1].rstrip('0'))

    def round_price(self, symbol, price):
        """Round price to symbol's precision"""
        precision = self.price_precision.get(symbol, 2)
        return round(float(price), precision)

    def round_quantity(self, symbol, quantity):
        """Round quantity according to lot size rules"""
        try:
            lot_size_info = self.client.get_lot_size_info(symbol)
            if (lot_size_info):
                step_size = lot_size_info['stepSize']
                precision = self.client.get_precision_from_step_size(step_size)
                rounded_qty = round(quantity - (quantity % float(step_size)), precision)
                
                # Ensure quantity is within min/max bounds
                if rounded_qty < lot_size_info['minQty']:
                    print(Fore.RED + f"Quantity {rounded_qty} is below minimum {lot_size_info['minQty']} for {symbol}")
                    return None
                if rounded_qty > lot_size_info['maxQty']:
                    print(Fore.RED + f"Quantity {rounded_qty} is above maximum {lot_size_info['maxQty']} for {symbol}")
                    return None
                    
                return rounded_qty
            return None
        except Exception as e:
            self.logger.error(f"Error rounding quantity: {e}")
            return None

    def start_order_monitor(self):
        """Start the order monitoring thread"""
        self.stop_monitoring = False
        self.order_monitor_thread = Thread(target=self.monitor_pending_orders, daemon=True)
        self.order_monitor_thread.start()

    def stop_order_monitor(self):
        """Stop the order monitoring thread"""
        self.stop_monitoring = True
        if self.order_monitor_thread:
            self.order_monitor_thread.join()

    def monitor_pending_orders(self):
        """Monitor pending orders in a separate thread"""
        while not self.stop_monitoring:
            try:
                # Create a copy of keys to avoid runtime modification issues
                order_ids = list(self.pending_orders.keys())
                
                for order_id in order_ids:
                    order_info = self.pending_orders[order_id]
                    symbol = order_info['symbol']
                    
                    order_status = self.client.client.get_order(
                        symbol=symbol,
                        orderId=order_id
                    )
                    
                    if order_status['status'] == 'FILLED':
                        print(Fore.GREEN + f"\nOrder filled: {symbol}")  # Add newline for better formatting
                        self.logger.info(f"BUY ORDER for {symbol}: {order_status}")
                        if self.telegram:
                            self.telegram.send_trade_notification(symbol, order_status)
                        if self.balance_manager:
                            self.balance_manager.print_balance_report(order_status)
                        del self.pending_orders[order_id]
                        self.orders_in_progress -= 1
                    elif order_status['status'] == 'REJECTED' or order_status['status'] == 'CANCELED':
                        print(Fore.RED + f"Order {order_status['status'].lower()}: {symbol}")
                        del self.pending_orders[order_id]
                        
            except Exception as e:
                self.logger.error(f"Error monitoring orders: {str(e)}")
            
            time.sleep(5)  # Check every 5 seconds

    def check_open_orders(self, symbol):
        """Check number of open orders for a symbol"""
        try:
            open_orders = self.client.get_open_orders(symbol=symbol)
            return len([order for order in open_orders if order['side'] == 'BUY'])
        except Exception as e:
            self.logger.error(f"Error checking open orders for {symbol}: {str(e)}")
            return 0

    def reset_daily_order_count(self):
        """Reset daily order count while preserving open orders"""
        self.daily_order_count = {}
        # Check all open orders and add them to daily count
        for symbol in self.client.trading_symbols:
            open_count = self.check_open_orders(symbol)
            if open_count > 0:
                self.daily_order_count[symbol] = open_count
                self.logger.info(f"Found {open_count} open orders for {symbol} during reset")

    def can_place_order(self, symbol, max_orders=3):
        """Check if we can place more orders for this symbol"""
        current_orders = self.daily_order_count.get(symbol, 0)
        return current_orders < max_orders

    def execute_trade(self, symbol, quantity, price, order_type="limit"):
        try:
            # Check if we can place more orders for this symbol
            if not self.can_place_order(symbol):
                self.logger.info(f"Maximum orders reached for {symbol}, skipping new order")
                return None

            # Take balance snapshot if this is the first order in a batch
            if self.balance_manager and self.orders_in_progress == 0:
                self.balance_manager.take_balance_snapshot()
            
            self.orders_in_progress += 1
            
            # Format quantity using the wrapper's method
            formatted_quantity = self.client.format_quantity(symbol, float(quantity))
            if not formatted_quantity:
                raise ValueError(f"Invalid quantity after formatting for {symbol}")
                
            # Round price to correct precision
            rounded_price = self.round_price(symbol, price)
            
            print(Fore.YELLOW + f"\nPlacing order for {symbol}")
            print(Fore.YELLOW + f"Original quantity: {quantity}")
            print(Fore.YELLOW + f"Formatted quantity: {formatted_quantity}")
            print(Fore.YELLOW + f"Price: {rounded_price}")
            
            if order_type == "limit":
                order = self.client.client.create_order(  # Access the underlying client through wrapper
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                    quantity=formatted_quantity,
                    price=str(rounded_price),
                    recvWindow=5000
                )
                
                # Add to pending orders and track time
                current_time = time.time()
                self.order_times[order['orderId']] = current_time
                self.pending_orders[order['orderId']] = {
                    'symbol': symbol,
                    'order': order
                }
                
                # Log order placement time and expiration
                placement_time = datetime.fromtimestamp(current_time)
                expiration_time = placement_time + timedelta(hours=8)
                print(Fore.YELLOW + f"Order placed at: {placement_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(Fore.YELLOW + f"Will be cancelled if not filled by: {expiration_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
            else:
                order = self.client.client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=formatted_quantity,
                    recvWindow=5000
                )
                print(Fore.GREEN + f"BUY ORDER for {symbol}: {order}")
                if self.telegram:
                    self.telegram.send_trade_notification(symbol, order)
                if self.balance_manager:
                    self.balance_manager.print_balance_report(order)
                self.orders_in_progress -= 1

            # Update daily order count after successful order placement
            self.daily_order_count[symbol] = self.daily_order_count.get(symbol, 0) + 1
            
            return order
            
        except Exception as e:
            self.orders_in_progress -= 1
            self.logger.error(f"Error executing trade for {symbol}: {str(e)}")
            print(Fore.RED + f"Error executing trade for {symbol}: {str(e)}")
            return None

    def start_order_cleanup(self):
        """Start the order cleanup thread"""
        self.order_cleanup_thread = Thread(target=self.cleanup_old_orders, daemon=True)
        self.order_cleanup_thread.start()

    def cleanup_old_orders(self):
        """Continuously monitor and cancel old orders"""
        while not self.stop_monitoring:
            try:
                current_time = time.time()
                open_orders = self.client.get_open_orders()
                
                for order in open_orders:
                    order_id = order['orderId']
                    order_time = self.order_times.get(order_id)
                    
                    if order_time and (current_time - order_time) > 8 * 3600:  # 8 hours in seconds
                        try:
                            self.client.cancel_order(symbol=order['symbol'], orderId=order_id)
                            print(Fore.YELLOW + f"\nCancelled old order: {order['symbol']} (Order ID: {order_id})")
                            print(Fore.YELLOW + f"Order age: {(current_time - order_time) / 3600:.2f} hours")
                            self.logger.info(f"Cancelled old order: {order['symbol']} (Order ID: {order_id})")
                            
                            # Remove from tracking
                            if order_id in self.pending_orders:
                                del self.pending_orders[order_id]
                            if order_id in self.order_times:
                                del self.order_times[order_id]
                                
                        except Exception as e:
                            self.logger.error(f"Error cancelling order {order_id}: {str(e)}")
                
            except Exception as e:
                self.logger.error(f"Error in cleanup thread: {str(e)}")
            
            time.sleep(300)  # Check every 5 minutes

    def cancel_old_orders(self):
        """Cancel limit orders that are older than 8 hours"""
        try:
            open_orders = self.client.get_open_orders()
            current_time = time.time()
            for order in open_orders:
                order_id = order['orderId']
                order_time = self.order_times.get(order_id)
                if order_time and (current_time - order_time) > 8 * 3600:
                    self.client.cancel_order(symbol=order['symbol'], orderId=order_id)
                    print(Fore.RED + f"Cancelled old order: {order['symbol']} (Order ID: {order_id})")
                    self.logger.info(f"Cancelled old order: {order['symbol']} (Order ID: {order_id})")
        except Exception as e:
            self.logger.error(f"Error cancelling old orders: {str(e)}")
            print(Fore.RED + f"Error cancelling old orders: {str(e)}")

    def __del__(self):
        """Cleanup when object is destroyed"""
        self.stop_monitoring = True
        if self.order_monitor_thread:
            self.order_monitor_thread.join()
        if self.order_cleanup_thread:
            self.order_cleanup_thread.join()
