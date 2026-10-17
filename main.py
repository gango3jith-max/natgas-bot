import os
import time
import datetime
import threading
import requests
import pandas as pd
import numpy as np
import pyotp
from flask import Flask
from SmartApi import SmartConnect

# Render Web Service-ന് വേണ്ടിയുള്ള ഡമ്മി സെർവർ
app = Flask(__name__)

@app.route('/')
def home():
    return "NatGas Bot is Running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ==========================================
# 1. നിങ്ങളുടെ ക്രെഡൻഷ്യലുകൾ ഇവിടെ നൽകുക
# ==========================================
API_KEY = "44VJPrN7"
CLIENT_CODE = "J69899"
PIN = "1284"
TOTP_SECRET = "PM265VKABP26Z6AI3CYBH4FIUM"

TELEGRAM_TOKEN = "8904699405:AAEg1dAgJV9wAOlKHaAXLG0HTsR3_aPnYDI"
CHAT_ID = "590931716"
              

# ==========================================
# 2. ടെലഗ്രാം അലേർട്ട് അയക്കുന്ന ഫംഗ്ഷൻ
# ==========================================
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ==========================================
# 3. ഓട്ടോമാറ്റിക് കറന്റ് മന്ത് ടോക്കൺ കണ്ടെത്തൽ
# ==========================================
def get_current_natgas_token():
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        res = requests.get(url).json()
        df = pd.DataFrame(res)

        ng_contracts = df[(df['exch_seg'] == 'MCX') & 
                          (df['name'] == 'NATURALGAS') & 
                          (df['instrumenttype'] == 'FUTCOM')].copy()

        ng_contracts['expiry_date'] = pd.to_datetime(ng_contracts['expiry'], format='%d%b%Y')
        today = datetime.datetime.now()
        valid_contracts = ng_contracts[ng_contracts['expiry_date'] >= today].sort_values(by='expiry_date')

        current_contract = valid_contracts.iloc[0]
        print(f"Active Contract: {current_contract['symbol']} | Token: {current_contract['token']}")
        return str(current_contract['token']), str(current_contract['symbol'])
    except Exception as e:
        print(f"Token Fetch Error: {e}")
        return None, None

# ==========================================
# 4. ഇൻഡിക്കേറ്ററുകൾ കാൽക്കുലേറ്റ് ചെയ്യുന്നു
# ==========================================
def calculate_indicators(df):
    df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()

    df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
    df['VP'] = df['Typical_Price'] * df['volume']
    df['VWAP'] = df['VP'].cumsum() / df['volume'].cumsum()

    atr_period = 10
    multiplier = 3
    df['tr'] = np.maximum(
        df['high'] - df['low'], 
        np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1)))
    )
    df['atr'] = df['tr'].rolling(atr_period).mean()

    df['hl2'] = (df['high'] + df['low']) / 2
    df['basic_ub'] = df['hl2'] + (multiplier * df['atr'])
    df['basic_lb'] = df['hl2'] - (multiplier * df['atr'])

    df['ST_Trend'] = np.where(df['close'] > df['basic_ub'].shift(1), "BUY", 
                     np.where(df['close'] < df['basic_lb'].shift(1), "SELL", "HOLD"))

    return df

def calculate_cpr(prev_high, prev_low, prev_close):
    pivot = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2
    tc = (pivot - bc) + pivot
    top_cpr = max(tc, bc)
    bottom_cpr = min(tc, bc)
    return pivot, top_cpr, bottom_cpr

# ==========================================
# 5. ബോട്ട് റൺ ചെയ്യുന്ന ലൂപ്പ്
# ==========================================
def run_trading_bot():
    print("Connecting to Angel One...")
    try:
        smartApi = SmartConnect(API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        smartApi.generateSession(CLIENT_CODE, PIN, totp)
        print("Login Successful!")

        token, symbol = get_current_natgas_token()
        last_signal = None

        send_telegram_alert(f"🤖 *Natural Gas Bot Activated*\nMonitoring: `{symbol}`")

        while True:
            try:
                now = datetime.datetime.now()
                today_str = now.strftime("%Y-%m-%d")

                historicParam = {
                    "exchange": "MCX",
                    "symboltoken": token,
                    "interval": "FIVE_MINUTE",
                    "fromdate": f"{today_str} 09:00",
                    "todate": f"{today_str} 23:30"
                }
                res = smartApi.getCandleData(historicParam)

                if res and res.get('data'):
                    df = pd.DataFrame(res['data'], columns=['time', 'open', 'high', 'low', 'close', 'volume'])
                    df = calculate_indicators(df)
                    
                    last_row = df.iloc[-1]
                    close = last_row['close']
                    vwap = last_row['VWAP']
                    ema = last_row['EMA_20']
                    supertrend = last_row['ST_Trend']

                    day_high = df['high'].max()
                    day_low = df['low'].min()
                    day_close = close
                    pivot, top_cpr, bottom_cpr = calculate_cpr(day_high, day_low, day_close)

                    atm_strike = int(round(close / 5.0) * 5)

                    if close > top_cpr and close > vwap and close > ema and supertrend == "BUY":
                        if last_signal != "BUY":
                            msg = (
                                f"🚀 *NATURAL GAS BUY SIGNAL (CE)*\n\n"
                                f"🔹 *Contract:* {symbol}\n"
                                f"🔹 *Price:* {close}\n"
                                f"🔹 *VWAP:* {round(vwap, 2)} | *EMA20:* {round(ema, 2)}\n"
                                f"🔹 *CPR:* Above Top CPR ({round(top_cpr, 2)})\n"
                                f"🔹 *Supertrend:* Bullish (Green)\n\n"
                                f"🎯 *Recommended Strike:* `{atm_strike} CE`\n"
                                f"🛑 *Stop Loss:* 20 EMA ({round(ema, 2)})"
                            )
                            send_telegram_alert(msg)
                            last_signal = "BUY"

                    elif close < bottom_cpr and close < vwap and close < ema and supertrend == "SELL":
                        if last_signal != "SELL":
                            msg = (
                                f"🔻 *NATURAL GAS SELL SIGNAL (PE)*\n\n"
                                f"🔹 *Contract:* {symbol}\n"
                                f"🔹 *Price:* {close}\n"
                                f"🔹 *VWAP:* {round(vwap, 2)} | *EMA20:* {round(ema, 2)}\n"
                                f"🔹 *CPR:* Below Bottom CPR ({round(bottom_cpr, 2)})\n"
                                f"🔹 *Supertrend:* Bearish (Red)\n\n"
                                f"🎯 *Recommended Strike:* `{atm_strike} PE`\n"
                                f"🛑 *Stop Loss:* 20 EMA ({round(ema, 2)})"
                            )
                            send_telegram_alert(msg)
                            last_signal = "SELL"

                time.sleep(300)

            except Exception as e:
                print(f"Loop Error: {e}")
                time.sleep(60)

    except Exception as e:
        print(f"Angel One Login Failed: {e}")

if __name__ == "__main__":
    # വെബ് സെർവർ ഒരു ത്രെഡിലും, ബോട്ട് മറ്റൊരു ത്രെഡിലും ഒരേസമയം റൺ ചെയ്യുന്നു
    t = threading.Thread(target=run_trading_bot)
    t.start()
    run_web()
