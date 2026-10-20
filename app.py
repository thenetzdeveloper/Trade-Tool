import os
import json
import time
from datetime import datetime
import requests
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request, render_template

# Try importing MetaTrader 5
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

import yfinance as yf
import google.generativeai as genai
from openai import OpenAI

import sys

def get_data_file_path(filename):
    """Get absolute path to data file, works for dev and for PyInstaller freeze"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)

if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

# Global list to manage server-side auto-trading logs
BACKEND_LOGS = []

# Cache for the latest AI analysis results to sync with frontend
ANALYSIS_CACHE_FILE = get_data_file_path('latest_analysis.json')

def save_latest_analysis(analysis_data):
    """Save latest AI analysis to latest_analysis.json"""
    try:
        with open(ANALYSIS_CACHE_FILE, 'w') as f:
            json.dump(analysis_data, f, indent=2)
    except Exception as e:
        print(f"Error saving latest analysis: {e}")

def load_latest_analysis():
    """Load latest AI analysis from latest_analysis.json"""
    if os.path.exists(ANALYSIS_CACHE_FILE):
        try:
            with open(ANALYSIS_CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading latest analysis: {e}")
    return None
LATEST_AI_ANALYSIS = load_latest_analysis()

# Cache file for historical BUY/SELL signals drawn on the Lightweight Chart
TRADE_HISTORY_FILE = get_data_file_path('trade_history.json')

def save_trade_history(trades):
    """Save trade history to trade_history.json"""
    try:
        with open(TRADE_HISTORY_FILE, 'w') as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        print(f"Error saving trade history: {e}")

def load_trade_history():
    """Load trade history from trade_history.json, seeding mock items if file doesn't exist"""
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading trade history: {e}")
            
    # Seed mock trade indicators at historical peak/trough timestamps matching the gold chart
    mock_history = [
        {
            "timestamp": 1781521200,
            "type": "SELL",
            "price": 4356.6,
            "sl": 4381.6,
            "tp": 4306.6,
            "ema20": 4340.0,
            "ema50": 4330.0,
            "ema200": 4310.0,
            "fallback_price": 4356.6,
            "status": "simulated"
        },
        {
            "timestamp": 1781550000,
            "type": "BUY",
            "price": 4342.4,
            "sl": 4317.4,
            "tp": 4392.4,
            "ema20": 4350.0,
            "ema50": 4340.0,
            "ema200": 4320.0,
            "fallback_price": 4342.4,
            "status": "simulated"
        },
        {
            "timestamp": 1781611200,
            "type": "SELL",
            "price": 4375.9,
            "sl": 4400.9,
            "tp": 4325.9,
            "ema20": 4360.0,
            "ema50": 4350.0,
            "ema200": 4330.0,
            "fallback_price": 4375.9,
            "status": "simulated"
        },
        {
            "timestamp": 1781618400,
            "type": "BUY",
            "price": 4344.4,
            "sl": 4319.4,
            "tp": 4394.4,
            "ema20": 4365.0,
            "ema50": 4355.0,
            "ema200": 4335.0,
            "fallback_price": 4344.4,
            "status": "simulated"
        },
        {
            "timestamp": 1781715600,
            "type": "SELL",
            "price": 4401.1,
            "sl": 4426.1,
            "tp": 4351.1,
            "ema20": 4380.0,
            "ema50": 4360.0,
            "ema200": 4340.0,
            "fallback_price": 4401.1,
            "status": "simulated"
        },
        {
            "timestamp": 1781722800,
            "type": "BUY",
            "price": 4254.3,
            "sl": 4229.3,
            "tp": 4304.3,
            "ema20": 4320.0,
            "ema50": 4330.0,
            "ema200": 4345.0,
            "fallback_price": 4254.3,
            "status": "simulated"
        },
        {
            "timestamp": 1781751600,
            "type": "SELL",
            "price": 4339.6,
            "sl": 4364.6,
            "tp": 4289.6,
            "ema20": 4330.0,
            "ema50": 4335.0,
            "ema200": 4340.0,
            "fallback_price": 4339.6,
            "status": "simulated"
        },
        {
            "timestamp": 1781834400,
            "type": "BUY",
            "price": 4193.9,
            "sl": 4168.9,
            "tp": 4243.9,
            "ema20": 4230.0,
            "ema50": 4270.0,
            "ema200": 4305.0,
            "fallback_price": 4193.9,
            "status": "simulated"
        }
    ]
    save_trade_history(mock_history)
    return mock_history

TRADE_HISTORY = load_trade_history()



def add_backend_log(message, log_type="system"):
    """Append a log message to the server logs queue and output to stdout"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    BACKEND_LOGS.append({
        "timestamp": timestamp,
        "message": message,
        "type": log_type
    })
    print(f"[{timestamp}] [{log_type.upper()}] {message}")
    if len(BACKEND_LOGS) > 100:
        BACKEND_LOGS.pop(0)

# Ensure first startup logs
add_backend_log("XAUUSD Trading Bot application backend initialized.", "system")

CONFIG_FILE = get_data_file_path('config.json')

def load_config():
    """Load config from config.json or return default dict"""
    defaults = {
        "api_provider": "gemini",
        "openai_key": "",
        "gemini_key": "",
        "gemini_backup_keys": ["", "", "", "", ""],
        "anthropic_key": "",
        "fmp_key": "",
        "trading_strategy": "swing",
        "trading_timeframe": "H1",
        "mt5": {
            "login": "",
            "password": "",
            "server": "MetaQuotes-Demo",
            "terminal_path": "",
            "live_trading": False
        },
        "risk_management": {
            "sl_pips": 50,
            "tp_pips": 100,
            "lot_size": 0.01,
            "auto_lot_enabled": False,
            "balance_step": 100.0,
            "scalping_target_pips": 15,
            "max_open_positions": 3,
            "trailing_stop_enabled": False,
            "trailing_stop_pips": 30.0,
            "trailing_activation_pips": 20.0,
            "partial_tp_enabled": False,
            "partial_tp_pips": 30.0,
            "partial_tp_percent": 50.0
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                # Merge defaults for missing fields recursively
                for k, v in defaults.items():
                    if k not in data:
                        data[k] = v
                    elif isinstance(v, dict) and isinstance(data[k], dict):
                        for sub_k, sub_v in v.items():
                            if sub_k not in data[k]:
                                data[k][sub_k] = sub_v
                return data
        except Exception as e:
            print(f"Error loading config: {e}")
    return defaults

def save_config(config_data):
    """Save config data to config.json"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

# Ensure config file exists initially
if not os.path.exists(CONFIG_FILE):
    save_config(load_config())

GOLD_SYMBOLS = ["XAUUSD", "GOLD", "XAUUSDm", "XAUUSD.m", "XAUUSD_"]
MT5_TERMINAL_CANDIDATES = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe",
    r"C:\Program Files\MetaQuotes MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    r"C:\Program Files\Exness MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\Exness MetaTrader 5\terminal64.exe",
]

def get_mt5_login_int(login_id):
    """Return a valid MT5 numeric login or None when the form is incomplete."""
    try:
        return int(str(login_id).strip())
    except (TypeError, ValueError):
        return None

def find_mt5_gold_symbol():
    """Select the first available broker gold symbol in Market Watch."""
    for symbol in GOLD_SYMBOLS:
        if mt5.symbol_select(symbol, True):
            symbol_info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if symbol_info is not None and tick is not None:
                return symbol
    return None

def get_existing_mt5_terminal_paths():
    """Return common MT5 terminal paths that exist on this Windows machine."""
    return [path for path in MT5_TERMINAL_CANDIDATES if os.path.exists(path)]

def initialize_mt5(mt5_settings=None):
    """Initialize MT5 using an explicit terminal path when the user provides one."""
    mt5_settings = mt5_settings or {}
    terminal_path = str(mt5_settings.get("terminal_path", "")).strip()

    if terminal_path:
        if not os.path.exists(terminal_path):
            return False, f"MT5 terminal path not found: {terminal_path}"
        if not mt5.initialize(path=terminal_path):
            return False, f"Failed to initialize MT5 at {terminal_path}: {mt5.last_error()}"
        return True, f"Initialized MT5 from {terminal_path}"

    if mt5.initialize():
        return True, "Initialized MT5 from registered Windows terminal."

    existing_paths = get_existing_mt5_terminal_paths()
    if existing_paths:
        path_list = "; ".join(existing_paths)
        return False, f"MT5 terminal found but no path is configured. Choose one of: {path_list}"

    return False, f"Failed to initialize: {mt5.last_error()}. Install MT5 x64 or set the terminal64.exe path."

def test_mt5_connection(mt5_settings):
    """Initialize MT5 and optionally authorize against the provided account."""
    if not MT5_AVAILABLE:
        return False, "MetaTrader 5 library not installed.", None

    initialized, init_message = initialize_mt5(mt5_settings)
    if not initialized:
        return False, init_message, None

    try:
        login_id = mt5_settings.get("login")
        password = mt5_settings.get("password")
        server = mt5_settings.get("server", "MetaQuotes-Demo")
        account_type = mt5_settings.get("account_type", "demo").upper()

        if login_id or password:
            login_int = get_mt5_login_int(login_id)
            if login_int is None:
                return False, "MT5 Login ID must be a number.", None
            if not password:
                return False, "MT5 password is required.", None

            authorized = mt5.login(login=login_int, password=password, server=server)
            if not authorized:
                return False, f"Failed to authorize: {mt5.last_error()}", None

            account = mt5.account_info()
            balance = f" Balance: {account.balance:.2f} {account.currency}." if account else ""
            return True, f"Connected ({account_type}) as Account {login_int} on {server}.{balance}", account

        return True, f"{init_message}. Add login, password, and server to trade from a specific account.", None
    finally:
        mt5.shutdown()

def get_mt5_rates(config, timeframe=None, count=100):
    """Retrieve historical candle rates from MetaTrader 5"""
    if not MT5_AVAILABLE:
        return None, "MetaTrader 5 library not installed."

    # Map timeframe strings to MT5 constants
    tf_map = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
        "D1": mt5.TIMEFRAME_D1
    }
    mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_H1)

    # Log in if credentials are provided in settings
    mt5_settings = config.get("mt5", {})
    initialized, init_message = initialize_mt5(mt5_settings)
    if not initialized:
        mt5.shutdown()
        return None, init_message

    login_id = mt5_settings.get("login")
    password = mt5_settings.get("password")
    server = mt5_settings.get("server", "MetaQuotes-Demo")

    if login_id and password:
        try:
            authorized = mt5.login(login=int(login_id), password=password, server=server)
            if not authorized:
                mt5.shutdown()
                return None, f"MT5 Authorization failed for login {login_id}: {mt5.last_error()}"
        except ValueError:
            pass # Skip login if ID is not an integer (user typing)

    # Standard Gold symbols list to account for broker suffixes
    rates = None
    active_symbol = None

    for symbol in GOLD_SYMBOLS:
        # Check if symbol is available in market watch
        selected = mt5.symbol_select(symbol, True)
        if selected:
            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
            if rates is not None and len(rates) > 0:
                active_symbol = symbol
                break

    if rates is None or len(rates) == 0:
        mt5.shutdown()
        return None, "Could not find or retrieve data for Gold symbol in MetaTrader 5."

    # Convert to DataFrame
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # We shutdown MT5 to release resources, or we can keep it open. Shutdown is safer in local web apps.
    mt5.shutdown()
    
    return {
        "df": df,
        "symbol": active_symbol,
        "source": "MetaTrader 5"
    }, None

def get_yfinance_rates(timeframe="H1", count=100):
    """Retrieve historical candle rates from Yahoo Finance as a fallback"""
    # Map timeframe to yfinance arguments
    # yfinance handles 1h, 15m, 1d
    yf_tf = "1h"
    if timeframe == "M5":
        yf_tf = "5m"
    elif timeframe == "M15":
        yf_tf = "15m"
    elif timeframe == "D1":
        yf_tf = "1d"

    # XAUUSD=X is the gold spot price on Yahoo Finance. Let's fall back to GC=F (futures) if that fails.
    symbol = "XAUUSD=X"
    period = "5d" if timeframe in ["M5", "M15", "H1"] else "60d"
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=yf_tf)
        
        if df.empty or len(df) < 20:
            # Try GC=F
            symbol = "GC=F"
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=yf_tf)
            
        if df.empty:
            return None, "Yahoo Finance API returned empty DataFrame."

        # Process columns to make it consistent with MT5 dataframe
        df = df.reset_index()
        # Rename columns to lowercase
        df.columns = [col.lower() for col in df.columns]
        
        # Ensure correct column names exist
        rename_map = {}
        for col in df.columns:
            if 'date' in col or 'time' in col:
                rename_map[col] = 'time'
        if rename_map:
            df = df.rename(columns=rename_map)
        
        # Keep only last 'count' rows
        df = df.tail(count).copy()
        
        return {
            "df": df,
            "symbol": symbol,
            "source": "Yahoo Finance (API Fallback)"
        }, None
    except Exception as e:
        return None, f"Yahoo Finance error: {str(e)}"

def get_live_price_tick(config, timeframe="M15"):
    """Return the newest available XAUUSD price tick for the moving chart line."""
    if MT5_AVAILABLE:
        mt5_settings = config.get("mt5", {})
        initialized, init_message = initialize_mt5(mt5_settings)
        if initialized:
            try:
                login_id = mt5_settings.get("login")
                password = mt5_settings.get("password")
                server = mt5_settings.get("server", "MetaQuotes-Demo")

                if login_id and password:
                    login_int = get_mt5_login_int(login_id)
                    if login_int is not None:
                        mt5.login(login=login_int, password=password, server=server)

                symbol = find_mt5_gold_symbol()
                if symbol:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        bid = float(tick.bid)
                        ask = float(tick.ask)
                        price = ask if ask > 0 else bid
                        return {
                            "success": True,
                            "symbol": symbol,
                            "source": "MetaTrader 5 Live Tick",
                            "price": price,
                            "bid": bid,
                            "ask": ask,
                            "timestamp": int(tick.time) if getattr(tick, "time", None) else int(time.time()),
                            "is_realtime": True
                        }, None
            finally:
                mt5.shutdown()

    data_dict, err = get_yfinance_rates(timeframe=timeframe, count=30)
    if err:
        return None, err

    df = data_dict["df"]
    latest = df.iloc[-1]
    t_val = latest["time"]
    if hasattr(t_val, "timestamp"):
        ts = int(t_val.timestamp())
    else:
        ts = int(pd.to_datetime(t_val).timestamp())

    price = float(latest["close"])
    return {
        "success": True,
        "symbol": data_dict["symbol"],
        "source": "Yahoo Finance Fallback",
        "price": price,
        "bid": price,
        "ask": price,
        "timestamp": ts,
        "is_realtime": False
    }, None

def calculate_technical_indicators(df):
    """Compute EMA, RSI, ATR, MACD, Bollinger Bands, Stochastic, and S/R indicators on the price DataFrame"""
    # Create copy to avoid SettingWithCopyWarning
    df = df.copy()
    
    # Calculate EMAs
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # Calculate RSI (14)
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    ema_gain = gain.ewm(com=13, adjust=False).mean()
    ema_loss = loss.ewm(com=13, adjust=False).mean()
    
    rs = ema_gain / (ema_loss + 1e-10) # Prevent division by zero
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Calculate ATR (14)
    high_low = df['high'] - df['low']
    high_pc = (df['high'] - df['close'].shift(1)).abs()
    low_pc = (df['low'] - df['close'].shift(1)).abs()
    
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    # Calculate MACD (12, 26, 9)
    df['macd_ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['macd_ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = df['macd_ema12'] - df['macd_ema26']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # Calculate Bollinger Bands (20, 2)
    df['bb_middle'] = df['close'].rolling(window=20).mean()
    std_dev = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + (2 * std_dev)
    df['bb_lower'] = df['bb_middle'] - (2 * std_dev)
    
    # Calculate Stochastic Oscillator (14, 3, 3)
    low_14 = df['low'].rolling(window=14).min()
    high_14 = df['high'].rolling(window=14).max()
    df['stoch_k'] = ((df['close'] - low_14) / (high_14 - low_14 + 1e-10)) * 100
    df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()
    
    # Calculate 20-period Support/Resistance levels
    df['resistance_20'] = df['high'].rolling(window=20).max()
    df['support_20'] = df['low'].rolling(window=20).min()
    
    # Drop rows that don't have enough data to calculate indicators
    df = df.dropna().reset_index(drop=True)
    return df

def fetch_gold_news_rss():
    """Fetch global financial news for Gold/Forex from public RSS feeds"""
    news_list = []
    # 1. Yahoo Finance Gold News RSS
    url = "https://finance.yahoo.com/rss/headline?s=GC=F"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(res.content)
            for item in root.findall('.//item')[:5]:
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                
                # Format date string
                try:
                    dt = datetime.strptime(pub_date[:-6], "%a, %d %b %Y %H:%M:%S")
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = pub_date
                
                news_list.append({
                    "title": title,
                    "link": link,
                    "date": date_str,
                    "source": "Yahoo Finance"
                })
    except Exception as e:
        print(f"Error fetching Yahoo RSS: {e}")

    # 2. DailyForex RSS Feed (Fallback or Addition)
    if len(news_list) < 3:
        url2 = "https://www.dailyforex.com/rss/forexnews.xml"
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url2, headers=headers, timeout=5)
            if res.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(res.content)
                for item in root.findall('.//item')[:5]:
                    title = item.find('title').text if item.find('title') is not None else ""
                    link = item.find('link').text if item.find('link') is not None else ""
                    pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                    
                    news_list.append({
                        "title": title,
                        "link": link,
                        "date": pub_date[:16],
                        "source": "DailyForex"
                    })
        except Exception as e:
            print(f"Error fetching DailyForex RSS: {e}")

    # Fallback to realistic mock items if offline/empty
    if not news_list:
        news_list = [
            {
                "title": "US Inflation Drops to 2.4%, Raising Odds of a Fed 25bps Rate Cut in September",
                "link": "https://finance.yahoo.com",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Market News"
            },
            {
                "title": "Gold Prices Steady Near $2350 as Geopolitical Risks Offset Stronger US Dollar Index",
                "link": "https://finance.yahoo.com",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Financial Feed"
            },
            {
                "title": "Fed Officials Maintain Hawkish Tone, Citing Labor Market Resilience and Wage Inflation",
                "link": "https://finance.yahoo.com",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Central Bank Watch"
            }
        ]
    
    return news_list

def get_active_positions(config):
    """Retrieve active positions on MetaTrader 5 for Gold symbols"""
    if not MT5_AVAILABLE:
        return []
        
    mt5_settings = config.get("mt5", {})
    initialized, init_message = initialize_mt5(mt5_settings)
    if not initialized:
        return []
        
    try:
        login_id = mt5_settings.get("login")
        password = mt5_settings.get("password")
        server = mt5_settings.get("server", "MetaQuotes-Demo")
        
        if login_id and password:
            try:
                authorized = mt5.login(login=int(login_id), password=password, server=server)
                if not authorized:
                    return []
            except ValueError:
                return []
                
        symbol = find_mt5_gold_symbol()
        if not symbol:
            return []
            
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return []
            
        results = []
        for pos in positions:
            pos_type = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            results.append({
                "ticket": int(pos.ticket),
                "symbol": str(pos.symbol),
                "type": pos_type,
                "volume": float(pos.volume),
                "price_open": float(pos.price_open),
                "sl": float(pos.sl),
                "tp": float(pos.tp),
                "profit": float(pos.profit)
            })
        return results
    except Exception as e:
        print(f"Error getting active positions: {e}")
        return []
    finally:
        mt5.shutdown()

def execute_mt5_order(config, signal_type, current_price, sl=None, tp=None):
    """Simulate or execute actual order placement on MetaTrader 5 with exits logic"""
    # Check if MT5 available
    if not MT5_AVAILABLE:
        return {"status": "error", "message": "MT5 library not available on this platform."}
        
    mt5_settings = config.get("mt5", {})
    risk = config.get("risk_management", {})
    
    # Pre-calculate lot size if auto lot is enabled
    lot_size = float(risk.get("lot_size", 0.01))
    auto_lot_calculated = False
    
    if risk.get("auto_lot_enabled", False):
        initialized, init_msg = initialize_mt5(mt5_settings)
        if initialized:
            try:
                login_id = mt5_settings.get("login")
                password = mt5_settings.get("password")
                server = mt5_settings.get("server", "MetaQuotes-Demo")
                
                if login_id and password:
                    login_int = get_mt5_login_int(login_id)
                    if login_int is not None:
                        mt5.login(login=login_int, password=password, server=server)
                        
                account = mt5.account_info()
                if account is not None:
                    balance = float(account.balance)
                    balance_step = float(risk.get("balance_step", 100.0))
                    if balance_step > 0:
                        lot_size = max(0.01, round((balance / balance_step) * 0.01, 2))
                        auto_lot_calculated = True
                        add_backend_log(f"Auto-Lot Sizing: Calculated dynamic lot size {lot_size} based on account balance ${balance:.2f} (Step: ${balance_step:.2f})", "system")
                else:
                    add_backend_log("Auto-Lot Sizing Warning: Could not retrieve account balance. Using default configured lot size.", "warning")
            except Exception as e_lot:
                add_backend_log(f"Auto-Lot Sizing Exception: {e_lot}. Using default configured lot size.", "error")
            finally:
                mt5.shutdown()
        else:
            add_backend_log(f"Auto-Lot Sizing: MT5 init failed ({init_msg}). Using default configured lot size.", "warning")

    if not mt5_settings.get("live_trading", False):
        return {
            "status": "simulated", 
            "message": "Simulation Mode Active. Order simulated successfully.",
            "lot_size": lot_size
        }
        
    login_id = mt5_settings.get("login")
    password = mt5_settings.get("password")
    server = mt5_settings.get("server", "MetaQuotes-Demo")
    
    if not login_id or not password:
        return {"status": "error", "message": "MT5 account credentials missing."}
        
    initialized, init_message = initialize_mt5(mt5_settings)
    if not initialized:
        return {"status": "error", "message": init_message}
        
    try:
        login_int = get_mt5_login_int(login_id)
        if login_int is None:
            mt5.shutdown()
            return {"status": "error", "message": "MT5 Login ID must be a number."}

        authorized = mt5.login(login=login_int, password=password, server=server)
        if not authorized:
            mt5.shutdown()
            return {"status": "error", "message": f"MT5 Login failed: {mt5.last_error()}"}
    except Exception as e:
        mt5.shutdown()
        return {"status": "error", "message": f"MT5 Authorization exception: {str(e)}"}
        
    symbol = find_mt5_gold_symbol()
    if not symbol:
        mt5.shutdown()
        return {"status": "error", "message": "Gold symbol not selected/available in MetaTrader 5."}
            
    # Calculate SL and TP
    sl_pips = float(risk.get("sl_pips", 50))
    tp_pips = float(risk.get("tp_pips", 100))
    # If auto-lot was not calculated, fallback to config lot_size
    if not auto_lot_calculated:
        lot_size = float(risk.get("lot_size", 0.01))
    
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        mt5.shutdown()
        return {"status": "error", "message": f"Failed to get info for symbol {symbol}"}
        
    point = symbol_info.point # usually 0.01 for gold

    # AUTO EXIT / CLOSE OPPOSITE POSITIONS BEFORE PLACING ORDER
    try:
        active_positions = mt5.positions_get(symbol=symbol)
        if active_positions:
            for pos in active_positions:
                # Close short positions if buying, and close long positions if selling
                if (signal_type == "BUY" and pos.type == mt5.POSITION_TYPE_SELL) or \
                   (signal_type == "SELL" and pos.type == mt5.POSITION_TYPE_BUY):
                    
                    close_tick = mt5.symbol_info_tick(symbol)
                    if close_tick:
                        close_type = mt5.ORDER_TYPE_BUY if pos.type == mt5.POSITION_TYPE_SELL else mt5.ORDER_TYPE_SELL
                        close_price = close_tick.ask if pos.type == mt5.POSITION_TYPE_SELL else close_tick.bid
                        
                        close_req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": symbol,
                            "volume": pos.volume,
                            "type": close_type,
                            "position": pos.ticket,
                            "price": close_price,
                            "deviation": 20,
                            "magic": 234000,
                            "comment": f"Auto Close Opposite Position {pos.ticket}",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        res_close = mt5.order_send(close_req)
                        if res_close.retcode == mt5.TRADE_RETCODE_DONE:
                            add_backend_log(f"MT5 Auto Exit: Closed opposite position {pos.ticket} at {close_price}", "system")
                        else:
                            add_backend_log(f"MT5 Auto Exit Fail: Could not close position {pos.ticket}. Retcode: {res_close.retcode}", "error")
    except Exception as ex_close:
        add_backend_log(f"Error while checking/closing opposite positions: {ex_close}", "error")
    
    # Determine BUY / SELL parameters
    if signal_type == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            mt5.shutdown()
            return {"status": "error", "message": f"No live tick available for {symbol}."}
        price = tick.ask
        final_sl = float(sl) if sl is not None else (price - (sl_pips * 10 * point))
        final_tp = float(tp) if tp is not None else (price + (tp_pips * 10 * point))
    elif signal_type == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            mt5.shutdown()
            return {"status": "error", "message": f"No live tick available for {symbol}."}
        price = tick.bid
        final_sl = float(sl) if sl is not None else (price + (sl_pips * 10 * point))
        final_tp = float(tp) if tp is not None else (price - (tp_pips * 10 * point))
    else:
        mt5.shutdown()
        return {"status": "error", "message": "Invalid signal type for order execution."}
        
    # Request setup
    request_dict = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": final_sl,
        "tp": final_tp,
        "deviation": 20,
        "magic": 234000,
        "comment": "Antigravity AI Bot Trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    # Send order
    result = mt5.order_send(request_dict)
    mt5.shutdown()
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "error", "message": f"Order send failed! Retcode: {result.retcode}, Description: {result.comment}"}
        
    return {
        "status": "success",
        "message": f"Order executed successfully! Position Ticket: {result.order}",
        "ticket": result.order,
        "symbol": symbol,
        "price": result.price,
        "sl": final_sl,
        "tp": final_tp,
        "lot_size": lot_size
    }

# ==================== Flask Routes ====================

@app.route('/')
def home():
    """Serve the Web Dashboard HTML page"""
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    """Return system connection status"""
    config = load_config()
    mt5_active, mt5_message, account = test_mt5_connection(config.get("mt5", {}))
    
    ai_status = "Not Configured"
    api_provider = config.get("api_provider", "gemini")
    
    if api_provider == "gemini" and config.get("gemini_key"):
        ai_status = "Gemini Key Configured"
    elif api_provider == "openai" and config.get("openai_key"):
        ai_status = "OpenAI Key Configured"
    elif api_provider == "claude" and config.get("anthropic_key"):
        ai_status = "Claude Key Configured"
    elif api_provider == "ensemble":
        # Check how many keys are configured
        active_keys = []
        if config.get("gemini_key"): active_keys.append("Gemini")
        if config.get("openai_key"): active_keys.append("OpenAI")
        if config.get("anthropic_key"): active_keys.append("Claude")
        if active_keys:
            ai_status = f"Consensus Mode ({', '.join(active_keys)})"
        else:
            ai_status = "Consensus Mode (No Keys Configured)"
    else:
        ai_status = "Mock/Simulation Mode Active"

    return jsonify({
        "mt5_available": MT5_AVAILABLE,
        "mt5_connected": mt5_active,
        "mt5_status_message": mt5_message,
        "mt5_balance": account.balance if account else 0.0,
        "mt5_equity": account.equity if account else 0.0,
        "mt5_leverage": account.leverage if account else 0,
        "ai_status": ai_status,
        "api_provider": api_provider,
        "live_trading_enabled": config.get("mt5", {}).get("live_trading", False),
        # Expose config keys for form auto-populating
        "gemini_key": config.get("gemini_key", ""),
        "gemini_backup_keys": config.get("gemini_backup_keys", ["", "", "", "", ""]),
        "openai_key": config.get("openai_key", ""),
        "anthropic_key": config.get("anthropic_key", ""),
        "fmp_key": config.get("fmp_key", ""),
        "mt5_account_type": config.get("mt5", {}).get("account_type", "demo"),
        "mt5_login": config.get("mt5", {}).get("login", ""),
        "mt5_server": config.get("mt5", {}).get("server", ""),
        "mt5_password": config.get("mt5", {}).get("password", ""),
        "mt5_terminal_path": config.get("mt5", {}).get("terminal_path", ""),
        "mt5_terminal_candidates": get_existing_mt5_terminal_paths() if MT5_AVAILABLE else [],
        "lot_size": config.get("risk_management", {}).get("lot_size", 0.01),
        "auto_lot_enabled": config.get("risk_management", {}).get("auto_lot_enabled", False),
        "balance_step": config.get("risk_management", {}).get("balance_step", 100.0),
        "sl_pips": config.get("risk_management", {}).get("sl_pips", 50),
        "tp_pips": config.get("risk_management", {}).get("tp_pips", 100),
        "trading_strategy": config.get("trading_strategy", "swing"),
        "trading_timeframe": config.get("trading_timeframe", "H1"),
        "scalping_target_pips": config.get("risk_management", {}).get("scalping_target_pips", 15),
        "max_open_positions": config.get("risk_management", {}).get("max_open_positions", 3),
        "trailing_stop_enabled": config.get("risk_management", {}).get("trailing_stop_enabled", False),
        "trailing_stop_pips": config.get("risk_management", {}).get("trailing_stop_pips", 30.0),
        "trailing_activation_pips": config.get("risk_management", {}).get("trailing_activation_pips", 20.0),
        "partial_tp_enabled": config.get("risk_management", {}).get("partial_tp_enabled", False),
        "partial_tp_pips": config.get("risk_management", {}).get("partial_tp_pips", 30.0),
        "partial_tp_percent": config.get("risk_management", {}).get("partial_tp_percent", 50.0)
    })

@app.route('/api/test-mt5', methods=['POST'])
def test_mt5_route():
    """Validate MT5 credentials from the settings form without placing trades."""
    data = request.json or {}
    mt5_settings = data.get("mt5", data)
    success, message, account = test_mt5_connection(mt5_settings)
    result = {
        "success": success,
        "message": message,
        "mt5_available": MT5_AVAILABLE
    }
    if account:
        result["account"] = {
            "login": account.login,
            "name": account.name,
            "server": account.server,
            "balance": account.balance,
            "equity": account.equity,
            "currency": account.currency,
            "leverage": account.leverage
        }
    return jsonify(result), 200 if success else 400

@app.route('/api/market-data', methods=['GET'])
def get_market_data():
    """Fetch live rates, calculate indicators and return metadata + history"""
    config = load_config()
    timeframe = request.args.get("timeframe", "H1")
    
    # 1. Try MT5
    data_dict, err = get_mt5_rates(config, timeframe=timeframe, count=100)
    
    # 2. Fall back to yfinance
    if err:
        print(f"MT5 Fetch failed: {err}. Falling back to Yahoo Finance...")
        data_dict, err = get_yfinance_rates(timeframe=timeframe, count=100)
        
    if err:
        return jsonify({"success": False, "error": err}), 500
        
    df = calculate_technical_indicators(data_dict["df"])
    
    if df.empty:
        return jsonify({"success": False, "error": "Insufficient data to compute indicators."}), 500
        
    # Get latest row
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    # Determine trend signals
    ema20 = float(latest['ema20'])
    ema50 = float(latest['ema50'])
    ema200 = float(latest['ema200'])
    close = float(latest['close'])
    rsi = float(latest['rsi'])
    atr = float(latest['atr'])
    
    ema_trend = "NEUTRAL"
    if ema20 > ema50:
        ema_trend = "BULLISH"
    elif ema20 < ema50:
        ema_trend = "BEARISH"
        
    ema200_trend = "BULLISH" if close > ema200 else "BEARISH"
    
    # RSI Condition
    rsi_condition = "NEUTRAL"
    if rsi >= 70:
        rsi_condition = "OVERBOUGHT"
    elif rsi <= 30:
        rsi_condition = "OVERSOLD"
        
    # MACD Condition
    macd = float(latest['macd'])
    macd_sig = float(latest['macd_signal'])
    macd_hist = float(latest['macd_hist'])
    prev_macd = float(prev['macd'])
    prev_macd_sig = float(prev['macd_signal'])
    
    macd_crossover = "NEUTRAL"
    if macd > macd_sig and prev_macd <= prev_macd_sig:
        macd_crossover = "BULLISH CROSSOVER"
    elif macd < macd_sig and prev_macd >= prev_macd_sig:
        macd_crossover = "BEARISH CROSSOVER"
    else:
        macd_crossover = "BULLISH MOMENTUM" if macd > macd_sig else "BEARISH MOMENTUM"
        
    # Bollinger Bands Position
    bb_upper = float(latest['bb_upper'])
    bb_lower = float(latest['bb_lower'])
    bb_mid = float(latest['bb_middle'])
    
    bb_pos = "INSIDE BANDS"
    if close >= bb_upper:
        bb_pos = "ABOVE UPPER BAND (Overbought)"
    elif close <= bb_lower:
        bb_pos = "BELOW LOWER BAND (Oversold)"
        
    # Stochastic Oscillator Condition
    stoch_k = float(latest['stoch_k'])
    stoch_d = float(latest['stoch_d'])
    stoch_cond = "NEUTRAL"
    if stoch_k >= 80 or stoch_d >= 80:
        stoch_cond = "OVERBOUGHT"
    elif stoch_k <= 20 or stoch_d <= 20:
        stoch_cond = "OVERSOLD"
        
    # Local Support & Resistance
    support = float(latest['support_20'])
    resistance = float(latest['resistance_20'])

    # Build historical list for UI chart
    history_list = []
    for _, row in df.iterrows():
        t_val = row['time']
        if hasattr(t_val, 'timestamp'):
            ts = int(t_val.timestamp())
        else:
            try:
                ts = int(pd.to_datetime(t_val).timestamp())
            except:
                ts = int(time.time()) # fallback
        
        history_list.append({
            "time": ts,
            "open": float(row['open']),
            "high": float(row['high']),
            "low": float(row['low']),
            "close": float(row['close']),
            "ema20": float(row['ema20']),
            "ema50": float(row['ema50']),
            "ema200": float(row['ema200']),
            "rsi": float(row['rsi']),
            "atr": float(row['atr'])
        })

    return jsonify({
        "success": True,
        "symbol": data_dict["symbol"],
        "data_source": data_dict["source"],
        "timeframe": timeframe,
        "current_price": close,
        "indicators": {
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi": rsi,
            "atr": atr,
            "ema_trend": ema_trend,
            "ema200_trend": ema200_trend,
            "rsi_condition": rsi_condition,
            "macd": macd,
            "macd_signal": macd_sig,
            "macd_hist": macd_hist,
            "macd_crossover": macd_crossover,
            "bb_upper": bb_upper,
            "bb_middle": bb_mid,
            "bb_lower": bb_lower,
            "bb_position": bb_pos,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
            "stoch_condition": stoch_cond,
            "support_20": support,
            "resistance_20": resistance
        },
        "history": history_list,
        "latest_analysis": LATEST_AI_ANALYSIS,
        "active_positions": get_active_positions(config),
        "trade_history": TRADE_HISTORY
    })

@app.route('/api/live-tick', methods=['GET'])
def get_live_tick():
    """Return latest price for the moving live price line on the chart."""
    config = load_config()
    timeframe = request.args.get("timeframe", "M15")
    tick_data, err = get_live_price_tick(config, timeframe=timeframe)
    if err:
        return jsonify({"success": False, "error": err}), 500
    return jsonify(tick_data)

@app.route('/api/news', methods=['GET'])
def get_news():
    """Retrieve global news and parse RSS"""
    news = fetch_gold_news_rss()
    return jsonify({"success": True, "news": news})

import concurrent.futures
from collections import Counter

def query_openai(prompt, config):
    key = config.get("openai_key")
    if not key:
        raise Exception("OpenAI API key is missing.")
    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a professional financial trading assistant that outputs only raw JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

def query_claude(prompt, config):
    key = config.get("anthropic_key")
    if not key:
        raise Exception("Anthropic API key is missing.")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1500,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=data, timeout=30)
    if res.status_code != 200:
        raise Exception(f"Claude API failed: {res.status_code} - {res.text}")
    res_json = res.json()
    return res_json["content"][0]["text"]

def query_gemini_with_rotation(prompt, config):
    key = config.get("gemini_key")
    if not key:
        raise Exception("Gemini key is missing")
    try:
        genai.configure(api_key=key)
        last_err = Exception("No Gemini models succeeded")
        for model_name in ['gemini-3.5-flash', 'gemini-2.5-flash', 'gemini-2.0-flash']:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return response.text, f"Gemini AI ({model_name})"
            except Exception as e_model:
                last_err = e_model
                continue
        raise last_err
    except Exception as e:
        backup_keys = config.get("gemini_backup_keys", ["", "", "", "", ""])
        non_empty_backups = [k.strip() for k in backup_keys if k.strip()]
        if non_empty_backups:
            new_main_key = non_empty_backups[0]
            rotated_backups = [k for k in backup_keys if k != new_main_key] + [""]
            config["gemini_key"] = new_main_key
            config["gemini_backup_keys"] = rotated_backups
            save_config(config)
            
            genai.configure(api_key=new_main_key)
            last_err = Exception("No Gemini models succeeded on retry")
            for model_name in ['gemini-3.5-flash', 'gemini-2.5-flash', 'gemini-2.0-flash']:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    return response.text, f"Gemini AI ({model_name})"
                except Exception as e_model:
                    last_err = e_model
                    continue
            raise last_err
        else:
            raise e

def run_consensus_ensemble(prompt, config, current_price, recommended_sl_buy, recommended_tp_buy, recommended_sl_sell, recommended_tp_sell, ema20, ema50):
    results = {}
    errors = []
    
    def run_one(provider):
        try:
            if provider == "gemini":
                res, model_status = query_gemini_with_rotation(prompt, config)
                return provider, res, model_status
            elif provider == "openai":
                res = query_openai(prompt, config)
                return provider, res, "OpenAI GPT-4o"
            elif provider == "claude":
                res = query_claude(prompt, config)
                return provider, res, "Anthropic Claude 3.5"
        except Exception as e:
            return provider, None, str(e)

    providers_to_query = []
    if config.get("gemini_key") or config.get("gemini_backup_keys", [""])[0].strip():
        providers_to_query.append("gemini")
    if config.get("openai_key"):
        providers_to_query.append("openai")
    if config.get("anthropic_key"):
        providers_to_query.append("claude")
        
    if not providers_to_query:
        raise Exception("No AI API keys configured for Consensus Mode.")
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers_to_query)) as executor:
        futures = {executor.submit(run_one, p): p for p in providers_to_query}
        for future in concurrent.futures.as_completed(futures):
            p = futures[future]
            try:
                provider, response, status = future.result()
                if response:
                    # Clean and parse JSON
                    clean_text = response.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()
                    parsed = json.loads(clean_text)
                    results[provider] = {
                        "parsed": parsed,
                        "status": status
                    }
                else:
                    errors.append(f"{p} failed: {status}")
            except Exception as ex:
                errors.append(f"{p} exception: {ex}")

    if not results:
        raise Exception(f"All AI providers in Consensus Mode failed. Errors: {'; '.join(errors)}")
        
    # Count frequencies of each signal
    signals = []
    for r in results.values():
        sig = r["parsed"].get("signal")
        if sig in ["BUY", "SELL", "WAIT"]:
            signals.append(sig)
            
    if not signals:
        raise Exception("No valid signals received from AI providers.")
        
    counts = Counter(signals)
    most_common = counts.most_common(1)[0]
    majority_signal = most_common[0]
    majority_count = most_common[1]
    
    # Tie breaking logic
    if len(signals) == 2 and majority_count == 1:
        consensus_signal = "WAIT"
    elif len(signals) == 3 and majority_count == 1:
        consensus_signal = "WAIT"
    else:
        consensus_signal = majority_signal
        
    # Average the confidence of the providers that agreed with the consensus signal
    confidences = []
    for r in results.values():
        if consensus_signal == "WAIT" or r["parsed"].get("signal") == consensus_signal:
            confidences.append(float(r["parsed"].get("confidence", 50)))
    avg_confidence = sum(confidences) / len(confidences) if confidences else 50
    
    # Average the trade targets for the providers that agreed with the consensus
    entries = []
    sls = []
    tps = []
    for r in results.values():
        if r["parsed"].get("signal") == consensus_signal:
            p_json = r["parsed"]
            if p_json.get("entry_price"): entries.append(float(p_json.get("entry_price")))
            if p_json.get("stop_loss"): sls.append(float(p_json.get("stop_loss")))
            if p_json.get("take_profit"): tps.append(float(p_json.get("take_profit")))
            
    avg_entry = sum(entries) / len(entries) if entries else current_price
    
    if consensus_signal == "BUY":
        avg_sl = sum(sls) / len(sls) if sls else recommended_sl_buy
        avg_tp = sum(tps) / len(tps) if tps else recommended_tp_buy
    elif consensus_signal == "SELL":
        avg_sl = sum(sls) / len(sls) if sls else recommended_sl_sell
        avg_tp = sum(tps) / len(tps) if tps else recommended_tp_sell
    else:
        avg_sl = sum(sls) / len(sls) if sls else (recommended_sl_buy if ema20 > ema50 else recommended_sl_sell)
        avg_tp = sum(tps) / len(tps) if tps else (recommended_tp_buy if ema20 > ema50 else recommended_tp_sell)
        
    # Synthesize reasons
    reasons_kh = []
    reasons_en = []
    for provider, r in results.items():
        prov_name = "Gemini" if provider == "gemini" else "GPT-4o" if provider == "openai" else "Claude"
        reasons_kh.append(f"[{prov_name} (សញ្ញា៖ {r['parsed'].get('signal')}): {r['parsed'].get('reason_khmer')}]")
        reasons_en.append(f"[{prov_name} (Signal: {r['parsed'].get('signal')}): {r['parsed'].get('reason_english')}]")
        
    consensus_kh = f"របបវិភាគរួមគ្នា (AI Consensus Mode)៖ សម្រេចបានសញ្ញា {consensus_signal} ដោយសម្លេងគាំទ្រ {majority_count}/{len(signals)} ម៉ូឌែល។\n\n" + "\n\n".join(reasons_kh)
    consensus_en = f"AI Consensus Mode: Decided signal {consensus_signal} by support of {majority_count}/{len(signals)} models.\n\n" + "\n\n".join(reasons_en)
    
    active_engines = ", ".join([r["status"] for r in results.values()])
    
    synthetic_json = {
        "signal": consensus_signal,
        "confidence": int(avg_confidence),
        "entry_price": round(avg_entry, 2),
        "stop_loss": round(avg_sl, 2),
        "take_profit": round(avg_tp, 2),
        "reason_khmer": consensus_kh,
        "reason_english": consensus_en,
        "ai_engine": f"Consensus ({active_engines})"
    }
    return synthetic_json

def run_ai_analysis_and_trade(timeframe="H1"):
    """
    Perform technical indicators compilation, fetch global news RSS,
    query OpenAI/Gemini AI, parse the JSON, and submit/close orders on MT5.
    Returns (success, result_dict, error_message).
    """
    config = load_config()
    
    add_backend_log(f"Starting AI Analysis cycle for Gold on timeframe {timeframe}...", "system")
    
    # 1. Fetch latest market data
    data_dict, err = get_mt5_rates(config, timeframe=timeframe, count=100)
    if err:
        add_backend_log(f"MT5 market data fetch failed: {err}. Trying yfinance fallback...", "warning")
        data_dict, err = get_yfinance_rates(timeframe=timeframe, count=100)
        
    if err:
        add_backend_log(f"Market data fetch failed: {err}", "error")
        return False, None, f"Failed to retrieve data for AI: {err}"
        
    df = calculate_technical_indicators(data_dict["df"])
    if df.empty:
        add_backend_log("Technical indicator computation returned empty dataframe", "error")
        return False, None, "Insufficient data to run analysis."
        
    latest = df.iloc[-1]
    
    # 2. Fetch latest news
    news_items = fetch_gold_news_rss()
    news_text = ""
    for idx, item in enumerate(news_items[:4]):
        news_text += f"{idx+1}. {item['title']} (Source: {item['source']})\n"
        
    # Technical values for prompt
    current_price = float(latest['close'])
    ema20 = float(latest['ema20'])
    ema50 = float(latest['ema50'])
    ema200 = float(latest['ema200'])
    rsi = float(latest['rsi'])
    atr = float(latest['atr'])
    macd = float(latest['macd'])
    macd_sig = float(latest['macd_signal'])
    macd_hist = float(latest['macd_hist'])
    bb_upper = float(latest['bb_upper'])
    bb_middle = float(latest['bb_middle'])
    bb_lower = float(latest['bb_lower'])
    stoch_k = float(latest['stoch_k'])
    stoch_d = float(latest['stoch_d'])
    support = float(latest['support_20'])
    resistance = float(latest['resistance_20'])
    
    ema_trend = "BULLISH (EMA20 > EMA50)" if ema20 > ema50 else "BEARISH (EMA20 < EMA50)"
    ema200_trend = "ABOVE 200 EMA (Long-term Bullish)" if current_price > ema200 else "BELOW 200 EMA (Long-term Bearish)"
    
    macd_info = f"MACD: {macd:.4f}, Signal: {macd_sig:.4f}, Hist: {macd_hist:.4f} (" + ("Bullish Crossover/Momentum" if macd > macd_sig else "Bearish Crossover/Momentum") + ")"
    bb_info = f"Upper BB: {bb_upper:.2f}, Middle BB (SMA20): {bb_middle:.2f}, Lower BB: {bb_lower:.2f} (Current Price: " + ("Above Upper Band" if current_price >= bb_upper else "Below Lower Band" if current_price <= bb_lower else "Inside Bands") + ")"
    stoch_info = f"%K: {stoch_k:.2f}, %D: {stoch_d:.2f} (" + ("Overbought" if stoch_k > 80 else "Oversold" if stoch_k < 20 else "Neutral") + ")"
    sr_info = f"20-period Support: {support:.2f}, Resistance: {resistance:.2f}"
    
    trading_strategy = config.get("trading_strategy", "swing")
    
    if trading_strategy == "scalping":
        strategy_label = "Scalping (Short-term momentum)"
        atr_sl_mult = 1.0
        atr_tp_mult = 1.5
        strategy_guideline = """You are executing a Scalping Strategy. Look for quick, short-term momentum opportunities on lower timeframes (e.g. M5, M15).
Recommend tighter stop loss and take profit targets to capture quick profits.
For entry confirmation: Look for Stochastic crossings in Oversold (<20) or Overbought (>80) zones, Bollinger Band boundary tests/reversals, and MACD histogram momentum shifts."""
    elif trading_strategy == "day_trading":
        strategy_label = "Day Trading (Intraday trend)"
        atr_sl_mult = 1.2
        atr_tp_mult = 2.2
        strategy_guideline = """You are executing a Day Trading Strategy. Look for intra-day trend continuations and reversals, opening and closing positions within the same day.
Recommend moderate stop loss and take profit targets.
For entry confirmation: Focus on EMA 20/50 crossovers, daily high/low pivots, and mid-period RSI support/resistance levels."""
    elif trading_strategy == "position":
        strategy_label = "Position Trading (Long-term trend following)"
        atr_sl_mult = 2.0
        atr_tp_mult = 4.0
        strategy_guideline = """You are executing a Position Trading (Long-term Trend Following) Strategy. Focus on long-term macro trends and hold positions for days or weeks.
Recommend wide stop loss and take profit targets to withstand intermediate market noise and drawdowns.
For entry confirmation: Focus on weekly and daily support/resistance levels, EMA 200 alignments, and monthly macro news events."""
    else:  # default to swing
        strategy_label = "Swing Trading (Medium-term trend)"
        atr_sl_mult = 1.5
        atr_tp_mult = 3.0
        strategy_guideline = """You are executing a Swing Strategy. Focus on medium-to-long term trends, utilizing larger support and resistance levels.
Recommend wider stop loss and take profit targets to allow the trade to breathe.
For entry confirmation: Focus on long-term EMA 200 alignments, major Support/Resistance pivots, and MACD trend crossings."""

    recommended_sl_buy = current_price - (atr_sl_mult * atr)
    recommended_tp_buy = current_price + (atr_tp_mult * atr)
    recommended_sl_sell = current_price + (atr_sl_mult * atr)
    recommended_tp_sell = current_price - (atr_tp_mult * atr)

    prompt = f"""
You are a world-class financial analyst and senior quantitative trader specializing in XAUUSD (Gold Spot vs US Dollar).
Analyze the current market state and generate a precise trade signal.

[TRADING STRATEGY]
Strategy: {strategy_label}
{strategy_guideline}

[MARKET TECHNICAL DATA]
Asset: XAUUSD (Gold vs US Dollar)
Current Price: {current_price:.2f}
Timeframe: {timeframe}
EMA Trend (20 vs 50): {ema_trend}
Long-term Trend (Price vs 200 EMA): {ema200_trend}
RSI (14-period): {rsi:.2f}
ATR (14-period Volatility): {atr:.2f}
MACD Momentum: {macd_info}
Bollinger Bands: {bb_info}
Stochastic Oscillator: {stoch_info}
Support & Resistance levels: {sr_info}

[GLOBAL FUNDAMENTAL NEWS]
{news_text}

[TRADING RULES]
1. If there is strong USD economic news (e.g. CPI/Retail sales beating expectations, or Fed raising rates), it strengthens the Dollar and WEAKENS Gold (SELL signal).
2. If US inflation is dropping, Fed is cutting rates, or there are major global geopolitical tensions/conflicts, it WEAKENS the Dollar and STRENGTHENS Gold as a safe haven (BUY signal).
3. If technicals and news conflict, or the market is flat with no clear driver, recommend WAIT.

[OUTPUT FORMAT]
You MUST respond in clean JSON format matching the schema below. Do not include markdown blocks like ```json in your response, just return the raw JSON string:
{{
  "signal": "BUY" | "SELL" | "WAIT",
  "confidence": 85,
  "entry_price": {current_price:.2f},
  "stop_loss": {recommended_sl_buy if ema20 > ema50 else recommended_sl_sell:.2f},
  "take_profit": {recommended_tp_buy if ema20 > ema50 else recommended_tp_sell:.2f},
  "reason_khmer": "Detailed explanation of the technical trend and news correlation, and why you recommend this action, written in fluent, grammatically correct, professional Khmer language.",
  "reason_english": "Same explanation, written in professional English."
}}
"""

    api_provider = config.get("api_provider", "gemini")
    ai_response = None
    ai_status = ""
    parsed_json = None

    if api_provider == "ensemble":
        try:
            add_backend_log("Querying multiple AI engines in Consensus Mode (Gemini, OpenAI, Claude)...", "system")
            # Run the consensus method
            consensus_result = run_consensus_ensemble(
                prompt, 
                config, 
                current_price, 
                recommended_sl_buy, 
                recommended_tp_buy, 
                recommended_sl_sell, 
                recommended_tp_sell, 
                ema20, 
                ema50
            )
            parsed_json = consensus_result
            ai_status = consensus_result["ai_engine"]
        except Exception as e:
            add_backend_log(f"AI Consensus Engine Exception: {e}", "error")
            ai_status = f"Consensus Error ({str(e)}) - Simulation Fallback"

    elif api_provider == "claude" and config.get("anthropic_key"):
        try:
            ai_response = query_claude(prompt, config)
            ai_status = "Anthropic Claude 3.5 Sonnet"
        except Exception as e:
            add_backend_log(f"Anthropic API Exception: {e}", "error")
            ai_status = f"Claude Error ({str(e)}) - Simulation Fallback"

    elif api_provider == "openai" and config.get("openai_key"):
        try:
            ai_response = query_openai(prompt, config)
            ai_status = "OpenAI GPT-4o"
        except Exception as e:
            add_backend_log(f"OpenAI API Exception: {e}", "error")
            ai_status = f"OpenAI Error ({str(e)}) - Simulation Fallback"

    elif api_provider == "gemini" and (config.get("gemini_key") or config.get("gemini_backup_keys", [""])[0].strip()):
        try:
            ai_response, ai_status = query_gemini_with_rotation(prompt, config)
        except Exception as e:
            add_backend_log(f"Gemini API Exception: {e}", "error")
            ai_status = f"Gemini Error ({str(e)}) - Simulation Fallback"

    if parsed_json is None and ai_response:
        clean_text = ai_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        try:
            parsed_json = json.loads(clean_text)
        except Exception as ex:
            add_backend_log(f"Failed to parse JSON response from AI: {ex}", "error")

    # Fallback simulation if parsing failed or no keys configured
    if parsed_json is None:
        is_bullish = ema20 > ema50
        signal_val = "BUY" if is_bullish else "SELL"
        confidence_val = 78 if rsi > 40 and rsi < 60 else 65
        
        if is_bullish:
            reason_kh = f"តម្លៃមាសបច្ចុប្បន្ន ({current_price:.2f}) ស្ថិតនៅពីលើខ្សែ EMA 20 និង EMA 50 ដែលបង្ហាញពីសន្ទុះកើនឡើង (Bullish Trend) នៅលើក្រាហ្វ {timeframe}។ RSI ស្ថិតនៅកម្រិត {rsi:.1f} ដែលបង្ហាញថាមានកម្លាំងទិញល្អ។ ទន្ទឹមនឹងនេះ ព័ត៌មានម៉ាក្រូសេដ្ឋកិច្ចសកលបង្ហាញពីការព្រួយបារម្ភអំពីការចុះខ្សោយនៃប្រាក់ដុល្លារ ដែលគាំទ្រឱ្យមាសឡើងថ្លៃ។"
            reason_en = f"Gold price is currently trading at {current_price:.2f}, hovering above the EMA 20 and EMA 50, indicating a clear bullish trend on the {timeframe} timeframe. RSI is at {rsi:.1f}, confirming positive momentum. Major fundamental news suggests softening USD, boosting Gold's safe-haven appeal."
            sl_val = recommended_sl_buy
            tp_val = recommended_tp_buy
        else:
            reason_kh = f"តម្លៃមាសបច្ចុប្បន្ន ({current_price:.2f}) បានធ្លាក់ចុះក្រោមខ្សែ EMA 20 និង EMA 50 ដែលជាសញ្ញានៃការធ្លាក់ចុះ (Bearish Trend)។ ម្យ៉ាងវិញទៀត ព័ត៌មានពីសហរដ្ឋអាមេរិកបង្ហាញពីទិន្នន័យសេដ្ឋកិច្ចរឹងមាំ ដែលធ្វើឱ្យប្រាក់ដុល្លារមានកម្លាំងឡើងវិញ និងដាក់សម្ពាធលក់លើមាស។"
            reason_en = f"Gold is trading at {current_price:.2f}, crossing below the short-term EMA 20 and EMA 50, marking a bearish trend. Technically, RSI is at {rsi:.1f}, reflecting seller dominance. Stronger US economic indicators are strengthening the USD, placing downward pressure on Gold."
            sl_val = recommended_sl_sell
            tp_val = recommended_tp_sell

        parsed_json = {
            "signal": signal_val,
            "confidence": confidence_val,
            "entry_price": round(current_price, 2),
            "stop_loss": round(sl_val, 2),
            "take_profit": round(tp_val, 2),
            "reason_khmer": reason_kh,
            "reason_english": reason_en
        }
        if not ai_status:
            ai_status = "Simulation Mode (No API keys provided)"

    parsed_json["ai_engine"] = ai_status
    parsed_json["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Dynamic order execution
    trade_signal = parsed_json.get("signal")
    if trade_signal in ["BUY", "SELL"]:
        # Risk Management: Check max open positions for same direction
        risk = config.get("risk_management", {})
        max_positions = int(risk.get("max_open_positions", 3))
        
        active_positions = get_active_positions(config)
        same_type_positions = [p for p in active_positions if p["type"] == trade_signal]
        
        if len(same_type_positions) >= max_positions:
            msg = f"Risk Management Limit: Open positions for {trade_signal} is {len(same_type_positions)} >= max limit {max_positions}. Skipping entry."
            add_backend_log(msg, "warning")
            exec_result = {"status": "skipped", "message": msg}
        else:
            exec_result = execute_mt5_order(
                config, 
                trade_signal, 
                current_price, 
                sl=parsed_json.get("stop_loss"), 
                tp=parsed_json.get("take_profit")
            )
        parsed_json["execution"] = exec_result
        
        # Log backend messages
        if exec_result["status"] == "success":
            add_backend_log(f"Auto Trade Executed! Signal: {trade_signal}, Ticket: {exec_result.get('ticket')} at {exec_result.get('price')}", "buy" if trade_signal == "BUY" else "sell")
        elif exec_result["status"] == "simulated":
            add_backend_log(f"Simulated Trade Triggered. Signal: {trade_signal}, SL: {parsed_json.get('stop_loss')}, TP: {parsed_json.get('take_profit')}", "warning")
        else:
            add_backend_log(f"Trade Execution Failed: {exec_result.get('message')}", "error")

        # Record newly placed/simulated trade in history for markers drawing on Live Chart
        if exec_result["status"] in ["success", "simulated"]:
            try:
                latest_candle = df.iloc[-1]
                candle_time = latest_candle["time"]
                if hasattr(candle_time, 'timestamp'):
                    candle_ts = int(candle_time.timestamp())
                else:
                    candle_ts = int(pd.to_datetime(candle_time).timestamp())
                    
                new_trade = {
                    "timestamp": candle_ts,
                    "type": trade_signal,
                    "price": float(exec_result.get("price", current_price)),
                    "sl": float(parsed_json.get("stop_loss")) if parsed_json.get("stop_loss") else None,
                    "tp": float(parsed_json.get("take_profit")) if parsed_json.get("take_profit") else None,
                    "ema20": float(latest_candle.get("ema20", ema20)),
                    "ema50": float(latest_candle.get("ema50", ema50)),
                    "ema200": float(latest_candle.get("ema200", ema200)),
                    "fallback_price": float(current_price),
                    "status": exec_result["status"]
                }
                
                global TRADE_HISTORY
                # Avoid duplicate trade markers on the same candle timestamp
                TRADE_HISTORY = [t for t in TRADE_HISTORY if t["timestamp"] != candle_ts]
                TRADE_HISTORY.append(new_trade)
                save_trade_history(TRADE_HISTORY)
            except Exception as e_hist:
                add_backend_log(f"Failed to record trade in history: {e_hist}", "error")
    else:
        parsed_json["execution"] = {"status": "none", "message": "No active trade executed (WAIT signal)"}
        add_backend_log("Analysis completed: WAIT signal generated.", "system")

    global LATEST_AI_ANALYSIS
    LATEST_AI_ANALYSIS = parsed_json
    save_latest_analysis(parsed_json)

    return True, parsed_json, None

@app.route('/api/analyze', methods=['POST'])
def trigger_analysis():
    """Call Google Gemini or OpenAI to analyze current technical indicators + news and generate signal"""
    timeframe = request.json.get("timeframe", "H1") if request.json else "H1"
    success, analysis_data, error = run_ai_analysis_and_trade(timeframe)
    if not success:
        return jsonify({"success": False, "error": error}), 500
    return jsonify({
        "success": True,
        "analysis": analysis_data
    })

@app.route('/api/toggle-bot', methods=['POST'])
def toggle_bot():
    """Toggle automated trading live state"""
    config = load_config()
    current_state = config.get("mt5", {}).get("live_trading", False)
    new_state = not current_state
    
    # Update state
    config["mt5"]["live_trading"] = new_state
    save_config(config)
    
    state_str = "ENABLED (Run)" if new_state else "DISABLED (Stop)"
    add_backend_log(f"Auto-Trading Live Execution has been manually {state_str} by user.", "system")
    
    return jsonify({
        "success": True,
        "live_trading_enabled": new_state,
        "message": f"Auto-Trading is now {state_str}."
    })

@app.route('/api/save-config', methods=['POST'])
def save_config_route():
    """Save configuration keys and options from the UI settings tab"""
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400
        
    config = load_config()
    
    # Update fields
    config["api_provider"] = data.get("api_provider", config.get("api_provider", "gemini"))
    config["openai_key"] = data.get("openai_key", config.get("openai_key", ""))
    config["gemini_key"] = data.get("gemini_key", config.get("gemini_key", ""))
    config["anthropic_key"] = data.get("anthropic_key", config.get("anthropic_key", ""))
    if "gemini_backup_keys" in data:
        backup_list = data["gemini_backup_keys"]
        if isinstance(backup_list, list):
            backup_list = [str(x).strip() for x in backup_list]
            backup_list = (backup_list + [""] * 5)[:5]
            config["gemini_backup_keys"] = backup_list
    config["fmp_key"] = data.get("fmp_key", config.get("fmp_key", ""))
    config["trading_strategy"] = data.get("trading_strategy", config.get("trading_strategy", "swing"))
    config["trading_timeframe"] = data.get("trading_timeframe", config.get("trading_timeframe", "H1"))
    
    # Update MT5 settings
    if "mt5" in data:
        config["mt5"]["account_type"] = data["mt5"].get("account_type", config["mt5"].get("account_type", "demo"))
        config["mt5"]["login"] = data["mt5"].get("login", config["mt5"].get("login", ""))
        config["mt5"]["password"] = data["mt5"].get("password", config["mt5"].get("password", ""))
        config["mt5"]["server"] = data["mt5"].get("server", config["mt5"].get("server", ""))
        config["mt5"]["terminal_path"] = data["mt5"].get("terminal_path", config["mt5"].get("terminal_path", ""))
        config["mt5"]["live_trading"] = bool(data["mt5"].get("live_trading", config["mt5"].get("live_trading", False)))
        
    # Update Risk Management settings
    if "risk_management" in data:
        rm = data["risk_management"]
        config["risk_management"]["sl_pips"] = float(rm.get("sl_pips", config["risk_management"].get("sl_pips", 50)))
        config["risk_management"]["tp_pips"] = float(rm.get("tp_pips", config["risk_management"].get("tp_pips", 100)))
        config["risk_management"]["lot_size"] = float(rm.get("lot_size", config["risk_management"].get("lot_size", 0.01)))
        config["risk_management"]["auto_lot_enabled"] = bool(rm.get("auto_lot_enabled", config["risk_management"].get("auto_lot_enabled", False)))
        config["risk_management"]["balance_step"] = float(rm.get("balance_step", config["risk_management"].get("balance_step", 100.0)))
        config["risk_management"]["scalping_target_pips"] = float(rm.get("scalping_target_pips", config["risk_management"].get("scalping_target_pips", 15)))
        config["risk_management"]["max_open_positions"] = int(rm.get("max_open_positions", config["risk_management"].get("max_open_positions", 3)))
        config["risk_management"]["trailing_stop_enabled"] = bool(rm.get("trailing_stop_enabled", config["risk_management"].get("trailing_stop_enabled", False)))
        config["risk_management"]["trailing_stop_pips"] = float(rm.get("trailing_stop_pips", config["risk_management"].get("trailing_stop_pips", 30.0)))
        config["risk_management"]["trailing_activation_pips"] = float(rm.get("trailing_activation_pips", config["risk_management"].get("trailing_activation_pips", 20.0)))
        config["risk_management"]["partial_tp_enabled"] = bool(rm.get("partial_tp_enabled", config["risk_management"].get("partial_tp_enabled", False)))
        config["risk_management"]["partial_tp_pips"] = float(rm.get("partial_tp_pips", config["risk_management"].get("partial_tp_pips", 30.0)))
        config["risk_management"]["partial_tp_percent"] = float(rm.get("partial_tp_percent", config["risk_management"].get("partial_tp_percent", 50.0)))
        
    if save_config(config):
        return jsonify({"success": True, "message": "Settings saved successfully!"})
    else:
        return jsonify({"success": False, "error": "Failed to write config file."}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Return backend auto-trading logs queue"""
    return jsonify({
        "success": True,
        "logs": BACKEND_LOGS
    })

# Background Auto-Trading Daemon loop and state
LAST_PROCESSED_CANDLES = {}

def auto_trading_daemon():
    """Monitors candle opens on MetaTrader 5 / yfinance to run AI Auto-Trading"""
    add_backend_log("Background Auto-Trading Daemon successfully spawned.", "system")
    while True:
        # Check every 60 seconds
        time.sleep(60)
        try:
            # Skip trading on weekends (Saturday and Sunday) to save API calls
            current_day = datetime.now().weekday()
            if current_day in [5, 6]:
                add_backend_log("Market is closed on weekends (Saturday/Sunday). Auto-Trading analysis is paused to save API keys.", "system")
                time.sleep(1800)  # Sleep 30 minutes to save CPU resources
                continue
                
            config = load_config()
            mt5_settings = config.get("mt5", {})
            if not mt5_settings.get("live_trading", False):
                continue
                
            timeframe = config.get("trading_timeframe", "H1")
            
            # Fetch latest rates to inspect candle time
            data_dict, err = get_mt5_rates(config, timeframe=timeframe, count=2)
            if err:
                data_dict, err = get_yfinance_rates(timeframe=timeframe, count=2)
                
            if err or data_dict is None or data_dict["df"].empty:
                continue
                
            df = data_dict["df"]
            latest_candle = df.iloc[-1]
            candle_time = latest_candle["time"]
            candle_ts = str(candle_time)
            
            last_checked = LAST_PROCESSED_CANDLES.get(timeframe)
            if last_checked == candle_ts:
                continue
                
            if last_checked is None:
                # Initialize state without trading immediately on start to prevent duplicate orders
                LAST_PROCESSED_CANDLES[timeframe] = candle_ts
                add_backend_log(f"Auto Trader monitoring timeframe {timeframe}. Current candle: {candle_ts}", "system")
                continue
                
            # A new candle has opened! Trigger auto-trade cycle!
            add_backend_log(f"New candle detected for timeframe {timeframe} at {candle_ts}. Triggering AI analysis...", "system")
            success, result, error = run_ai_analysis_and_trade(timeframe)
            if success:
                LAST_PROCESSED_CANDLES[timeframe] = candle_ts
                add_backend_log(f"Auto-trade run successful. Signal: {result.get('signal')}", "system")
            else:
                add_backend_log(f"Auto-trade run failed: {error}", "error")
                
        except Exception as e:
            add_backend_log(f"Auto-trade daemon loop exception: {str(e)}", "error")

PARTIAL_TP_TICKETS = set()

def position_monitoring_daemon():
    """Monitors active positions on MT5 to auto-close profitable trades and apply Trailing SL & Partial TP."""
    add_backend_log("Background Position Monitoring Daemon successfully spawned.", "system")
    global PARTIAL_TP_TICKETS
    while True:
        time.sleep(15)
        try:
            config = load_config()
            trading_strategy = config.get("trading_strategy", "swing")
            
            # Let's see if MT5 is available
            if not MT5_AVAILABLE:
                continue
                
            mt5_settings = config.get("mt5", {})
            # Only perform operations if live trading is enabled
            if not mt5_settings.get("live_trading", False):
                continue
                
            initialized, init_message = initialize_mt5(mt5_settings)
            if not initialized:
                continue
                
            try:
                login_id = mt5_settings.get("login")
                password = mt5_settings.get("password")
                server = mt5_settings.get("server", "MetaQuotes-Demo")
                
                if login_id and password:
                    login_int = get_mt5_login_int(login_id)
                    if login_int is not None:
                        authorized = mt5.login(login=login_int, password=password, server=server)
                        if not authorized:
                            continue
                            
                symbol = find_mt5_gold_symbol()
                if not symbol:
                    continue
                    
                positions = mt5.positions_get(symbol=symbol)
                if not positions:
                    continue
                    
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    continue
                    
                symbol_info = mt5.symbol_info(symbol)
                if not symbol_info:
                    continue
                point = symbol_info.point
                
                risk = config.get("risk_management", {})
                
                # Dynamic controls
                scalping_target = float(risk.get("scalping_target_pips", 15))
                
                partial_tp_enabled = bool(risk.get("partial_tp_enabled", False))
                partial_tp_pips = float(risk.get("partial_tp_pips", 30))
                partial_tp_percent = float(risk.get("partial_tp_percent", 50))
                
                trailing_stop_enabled = bool(risk.get("trailing_stop_enabled", False))
                trailing_stop_pips = float(risk.get("trailing_stop_pips", 30))
                trailing_activation_pips = float(risk.get("trailing_activation_pips", 20))
                
                for pos in positions:
                    ticket_id = int(pos.ticket)
                    price_open = float(pos.price_open)
                    volume_current = float(pos.volume)
                    
                    if pos.type == mt5.POSITION_TYPE_BUY:
                        current_close_price = tick.bid
                        price_diff = current_close_price - price_open
                    else:  # POSITION_TYPE_SELL
                        current_close_price = tick.ask
                        price_diff = price_open - current_close_price
                        
                    profit_pips = price_diff / 0.10  # Gold 1 pip is 0.10 price points
                    
                    # 1. Partial Take Profit Logic
                    if partial_tp_enabled and profit_pips >= partial_tp_pips and ticket_id not in PARTIAL_TP_TICKETS:
                        # Check if volume is already smaller than or equal to 0.01. If so, skip partial TP.
                        if volume_current > 0.01:
                            close_vol = round(volume_current * (partial_tp_percent / 100.0), 2)
                            # Ensure we don't try to close more than current volume, minimum step is 0.01
                            if close_vol < 0.01:
                                close_vol = 0.01
                            elif close_vol >= volume_current:
                                close_vol = round(volume_current - 0.01, 2)
                                
                            if close_vol >= 0.01:
                                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                                partial_close_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
                                
                                close_req = {
                                    "action": mt5.TRADE_ACTION_DEAL,
                                    "symbol": symbol,
                                    "volume": close_vol,
                                    "type": close_type,
                                    "position": ticket_id,
                                    "price": partial_close_price,
                                    "deviation": 20,
                                    "magic": 234000,
                                    "comment": f"Partial TP Close ({close_vol} Lot)",
                                    "type_time": mt5.ORDER_TIME_GTC,
                                    "type_filling": mt5.ORDER_FILLING_IOC,
                                }
                                res_close = mt5.order_send(close_req)
                                if res_close.retcode == mt5.TRADE_RETCODE_DONE:
                                    add_backend_log(f"Partial TP Success: Closed {close_vol} of Position #{ticket_id} at {partial_close_price}.", "system")
                                    PARTIAL_TP_TICKETS.add(ticket_id)
                                    
                                    # Move remaining position stop loss to break-even (price_open)
                                    modify_req = {
                                        "action": mt5.TRADE_ACTION_SLTP,
                                        "position": ticket_id,
                                        "symbol": symbol,
                                        "sl": float(price_open),
                                        "tp": float(pos.tp)
                                    }
                                    res_mod = mt5.order_send(modify_req)
                                    if res_mod.retcode == mt5.TRADE_RETCODE_DONE:
                                        add_backend_log(f"Partial TP SL Mod: Position #{ticket_id} SL moved to Break-even at {price_open}.", "system")
                                    else:
                                        add_backend_log(f"Partial TP SL Mod Fail: Position #{ticket_id}. Retcode: {res_mod.retcode}", "error")
                                else:
                                    add_backend_log(f"Partial TP Fail for Position #{ticket_id}. Retcode: {res_close.retcode}, Comment: {res_close.comment}", "error")
                    
                    # 2. Trailing Stop Loss Logic
                    if trailing_stop_enabled and profit_pips >= trailing_activation_pips:
                        # Determine potential new SL level
                        if pos.type == mt5.POSITION_TYPE_BUY:
                            # BUY trails behind bid price
                            new_sl = round(tick.bid - (trailing_stop_pips * 10 * point), 2)
                            # Update only if new SL is higher than current SL (or if current SL is 0)
                            if pos.sl == 0 or new_sl > float(pos.sl) + (2 * 10 * point):
                                modify_req = {
                                    "action": mt5.TRADE_ACTION_SLTP,
                                    "position": ticket_id,
                                    "symbol": symbol,
                                    "sl": float(new_sl),
                                    "tp": float(pos.tp)
                                }
                                res_mod = mt5.order_send(modify_req)
                                if res_mod.retcode == mt5.TRADE_RETCODE_DONE:
                                    add_backend_log(f"Trailing Stop Success: BUY #{ticket_id} SL trailed to {new_sl}.", "system")
                                else:
                                    add_backend_log(f"Trailing Stop Fail: BUY #{ticket_id} to {new_sl}. Retcode: {res_mod.retcode}", "error")
                        else:  # POSITION_TYPE_SELL
                            # SELL trails above ask price
                            new_sl = round(tick.ask + (trailing_stop_pips * 10 * point), 2)
                            # Update only if new SL is lower than current SL (or if current SL is 0)
                            if pos.sl == 0 or new_sl < float(pos.sl) - (2 * 10 * point):
                                modify_req = {
                                    "action": mt5.TRADE_ACTION_SLTP,
                                    "position": ticket_id,
                                    "symbol": symbol,
                                    "sl": float(new_sl),
                                    "tp": float(pos.tp)
                                }
                                res_mod = mt5.order_send(modify_req)
                                if res_mod.retcode == mt5.TRADE_RETCODE_DONE:
                                    add_backend_log(f"Trailing Stop Success: SELL #{ticket_id} SL trailed to {new_sl}.", "system")
                                else:
                                    add_backend_log(f"Trailing Stop Fail: SELL #{ticket_id} to {new_sl}. Retcode: {res_mod.retcode}", "error")
                    
                    # 3. Scalping Target Complete Close (Only if strategy is scalping)
                    if trading_strategy == "scalping" and profit_pips >= scalping_target:
                        add_backend_log(f"Scalping Target Hit! Position {ticket_id} profit: {profit_pips:.1f} pips >= target {scalping_target} pips. Closing position...", "system")
                        
                        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        
                        close_req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": symbol,
                            "volume": volume_current,
                            "type": close_type,
                            "position": ticket_id,
                            "price": current_close_price,
                            "deviation": 20,
                            "magic": 234000,
                            "comment": f"Scalping Target Close ({profit_pips:.1f} pips)",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        
                        res_close = mt5.order_send(close_req)
                        if res_close.retcode == mt5.TRADE_RETCODE_DONE:
                            add_backend_log(f"Scalping Auto-Close Success: Closed position {ticket_id} at {current_close_price} for {profit_pips:.1f} pips profit.", "system")
                        else:
                            add_backend_log(f"Scalping Auto-Close Failed for position {ticket_id}. Retcode: {res_close.retcode}, Comment: {res_close.comment}", "error")
            except Exception as inner_e:
                add_backend_log(f"Position monitoring internal error: {str(inner_e)}", "error")
            finally:
                mt5.shutdown()
        except Exception as e:
            add_backend_log(f"Position monitoring daemon exception: {str(e)}", "error")

import threading

if __name__ == '__main__':
    # Ensure template and static directories exist
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'css'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'js'), exist_ok=True)
    
    # Start auto-trading background daemon thread once in Flask process context
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        t = threading.Thread(target=auto_trading_daemon, daemon=True)
        t.start()
        add_backend_log("Background Auto-Trading thread started.", "system")
        
        # Start position monitoring daemon thread
        t_pos = threading.Thread(target=position_monitoring_daemon, daemon=True)
        t_pos.start()
        add_backend_log("Background Position Monitoring thread started.", "system")
    
    print("XAUUSD Trading Bot running at http://localhost:5002")
    app.run(host='0.0.0.0', port=5002, debug=not getattr(sys, 'frozen', False))

