import telegram
from telegram.ext import Updater, CommandHandler

class TelegramHandler:
    def __init__(self, token, chat_id, balance_manager):
        self.bot = telegram.Bot(token=token)
        self.chat_id = chat_id
        self.balance_manager = balance_manager
        self.updater = Updater(token)
        self.setup_handlers()

    def setup_handlers(self):
        dispatcher = self.updater.dispatcher
        dispatcher.add_handler(CommandHandler("balance", self.handle_balance))
        dispatcher.add_handler(CommandHandler("trades", self.handle_trades))
        dispatcher.add_handler(CommandHandler("profits", self.handle_profits))
        self.updater.start_polling()

    def send_message(self, message):
        try:
            self.bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            print(f"Error sending telegram message: {str(e)}")

    def send_trade_notification(self, symbol, order):
        message = f"BUY ORDER for {symbol}:\n{order}"
        self.send_message(message)

    def handle_balance(self, update, context):
        balance_report = self.balance_manager.get_balance()
        if balance_report:
            message = "Current balance:\n" + "\n".join([f"{asset}: {total}" for asset, total in balance_report.items()])
            update.message.reply_text(message)
        else:
            update.message.reply_text("Error fetching balance.")

    def handle_trades(self, update, context):
        update.message.reply_text(f"Total number of trades done: {self.balance_manager.total_trades}")

    def handle_profits(self, update, context):
        current_prices = {symbol: self.market_data.fetch_current_price(symbol) 
                         for symbol in self.balance_manager.trading_symbols}
        profits = self.balance_manager.get_profits(current_prices)
        if profits:
            profit_message = "\n".join([f"{symbol}: {profit:.2f} USDT" for symbol, profit in profits.items()])
            update.message.reply_text(f"Current profits:\n{profit_message}")
        else:
            update.message.reply_text("Error calculating profits.")
