## Binance Trading Bot

A Python-based trading bot for Binance that implements both cryptocurrency and stock market tracking strategies.

### Features

- Cryptocurrency Trading:
  - Multiple price drop thresholds for buying
  - Support for both limit and market orders
  - Automatic order monitoring and balance tracking
  - Real-time balance reports with trade summaries
  - Trading fee calculations and tracking
  - Configurable USDT reserve amount
  - Support for both live and testnet trading
  - Automatic cancellation of unfilled orders after 8 hours

- Stock Market Integration:
  - S&P 500 tracking via Alpha Vantage API
  - Multiple daily price checks for stocks
  - Configurable stock symbols tracking
  - Real-time stock market notifications

- Monitoring and Notifications:
  - Optional Telegram notifications
  - Health check monitoring
  - Detailed logging system
  - Balance and trade reporting

### Prerequisites

- Python 3.9 or higher
- A Binance account (regular or testnet)
- Telegram bot (optional)
- Alpha Vantage API key (for stock tracking)
- Polygon.io API key (for additional market data)

### Installation

1. **Clone the repository**
    ```sh
    git clone https://github.com/your-username/binance-bot.git
    cd binance-bot
    ```

2. **Create and activate a virtual environment**
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3. **Install dependencies**
    ```sh
    pip install -r requirements.txt
    ```

4. **Configure the bot**
    Copy `config/config_template.json` to `config/config.json` and edit with your details:
    ```json
    {
        "BINANCE_API_KEY": "your_api_key",
        "BINANCE_API_SECRET": "your_api_secret",
        "TESTNET_API_KEY": "your_testnet_key",
        "TESTNET_API_SECRET": "your_testnet_secret",
        "TRADING_SYMBOLS": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "TIME_INTERVAL": "1d",
        "TELEGRAM_TOKEN": "your_telegram_bot_token",
        "TELEGRAM_CHAT_ID": "your_telegram_chat_id",
        "DROP_THRESHOLDS": [0.01, 0.02, 0.03],
        "USDT_RESERVE": 200,
        "ALPHA_VANTAGE_API_KEY": "your_alpha_vantage_api_key",
        "POLYGON_API_KEY": "your_polygon_api_key",
        "STOCK_SYMBOLS": ["AAPL", "GOOGL", "AMZN"]
    }
    ```

### Usage

1. **Start the bot**
    ```sh
    python main.py
    ```

2. **Configuration prompts**
    - Choose testnet or live trading
    - Enable/disable Telegram notifications
    - Set number of price drop thresholds
    - Configure threshold percentages (in ascending order)
    - Choose limit or market orders
    - Set fixed USDT amount or percentage per trade
    - Set USDT reserve amount (minimum 200)
    - Configure stock symbols for tracking

3. **Trading Process**
    - Bot monitors price drops from daily open
    - Places orders when price drops hit thresholds
    - Automatically cancels unfilled limit orders after 8 hours
    - Maintains minimum USDT reserve
    - Shows detailed balance reports after trades
    - Tracks stock prices and sends notifications

4. **Balance Reports**
    After each trade, you'll see:
    - Current balances with changes
    - Trade summary with quantities and prices
    - Trading fees (0.1% per trade)
    - Total amount spent including fees

5. **Telegram Commands** (if enabled)
    - `/balance`: Current account balance
    - `/trades`: Total number of trades executed
    - `/profits`: Current profit/loss calculation
    - `/stocks`: Current stock prices

### Docker Support

1. **Create .env file**
    ```env
    BINANCE_API_KEY=your_api_key
    BINANCE_API_SECRET=your_api_secret
    TESTNET_API_KEY=your_testnet_key
    TESTNET_API_SECRET=your_testnet_secret
    TELEGRAM_TOKEN=your_telegram_token
    TELEGRAM_CHAT_ID=your_chat_id
    USE_TESTNET=yes
    USE_TELEGRAM=no
    DROP_THRESHOLDS=0.01,0.02,0.03
    ORDER_TYPE=limit
    USE_PERCENTAGE=no
    TRADE_AMOUNT=100
    USDT_RESERVE=200
    ALPHA_VANTAGE_API_KEY=your_alpha_vantage_api_key
    POLYGON_API_KEY=your_polygon_api_key
    STOCK_SYMBOLS=AAPL,GOOGL,AMZN
    ```

2. **Build and run**
    ```sh
    docker-compose build
    docker-compose up
    ```

### Security

- Never share your API keys
- Use API keys with trade-only permissions
- Maintain the USDT reserve for account safety
- Test with testnet before live trading

### TODO

- Fully manageable via Telegram
- Implement multiple strategies:
  - RSI-based strategy
  - Moving average crossovers
  - Volume-based triggers
- Support for other exchanges
- Backtesting capabilities
- Local UI for management
- Limit orders should cancel automatically when not executed within 8 hours
- Bot should check for open limit positions at daily reset and still be able to make new orders on top of the open ones
- Add email notifications option monthly

### Disclaimer

This bot is for educational purposes. Trading cryptocurrencies carries risk. Use at your own discretion.

### Support

For questions or issues:
- Create a GitHub issue
- Contact via Discord: **maskiplays**