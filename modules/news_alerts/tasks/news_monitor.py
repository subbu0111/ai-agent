import asyncio
import json
from datetime import datetime
from modules.trading.tools.search import get_news, search_web
from modules.trading.tools.realtime import get_stock_price, get_crypto_price
from modules.trading.nifty500 import NIFTY500_MAP
from ai_client import ask_ai
from telegram.ext import ContextTypes
import os
import re

watchlists_file = 'data/watchlists.json'
prices_file = 'data/user_prices.json'

dedup_news = set()  # snippet hashes, clear daily

def load_data():
    watchlists = {}
    prices = {}
    if os.path.exists(watchlists_file):
        with open(watchlists_file, 'r') as f:
            watchlists = json.load(f)
    if os.path.exists(prices_file):
        with open(prices_file, 'r') as f:
            prices = json.load(f)
    return watchlists, prices

def save_prices(prices):
    with open(prices_file, 'w') as f:
        json.dump(prices, f)

def get_symbol(ticker_str):
    # Map shorts to symbols
    words = ticker_str.lower().split()
    for name in NIFTY500_MAP:
        if name.split()[0].lower() in words:
            return NIFTY500_MAP[name]
    crypto_map = {'btc': 'BTC-USD', 'bitcoin': 'BTC-USD', 'eth': 'ETH-USD'}
    nasdaq_map = {'apple': 'AAPL', 'msft': 'MSFT', 'nvda': 'NVDA'}
    for w in words:
        if w in crypto_map:
            return crypto_map[w]
        if w in nasdaq_map:
            return nasdaq_map[w]
    return ticker_str  # Assume direct symbol

async def proactive_news(chat_id, context: ContextTypes.DEFAULT_TYPE, user_id: str):
    dedup_news = set()  # snippet hashes, clear daily
    while True:
        try:
            watchlists, prices = load_data()
            user_watch = watchlists.get(user_id, {}).get('watch', [])
            user_alerts = watchlists.get(user_id, {}).get('alerts', ['ipl', 'tennis', 'f1'])

            # Price alerts for watchlist (>2% change)
            user_prices = prices.get(user_id, {})
            for item in user_watch:
                symbol = get_symbol(item)
                if symbol:
                    try:
                        if '.NS' in symbol or symbol.startswith('^NSE'):
                            price_str = get_stock_price(symbol)
                            curr_price = float(price_str.split()[-1].replace(',', '').replace('₹', ''))
                        else:
                            price_str = get_crypto_price(symbol.split('-')[0]) if '-USD' in symbol else get_stock_price(symbol)
                            curr_price = float(price_str.split('$')[-1].replace(',', ''))
                        last_price = user_prices.get(item, curr_price)
                        change_pct = abs((curr_price - last_price) / last_price * 100) if last_price else 0
                        if change_pct > 2:
                            msg = f"📈 {symbol}: {curr_price:.2f} ({change_pct:.1f}% {'↑' if curr_price > last_price else '↓'} )"
                            await context.bot.send_message(chat_id=chat_id, text=msg)
                            user_prices[item] = curr_price
                    except:
                        pass

            # News alerts (Breaking focus, dedup)
            now_str = datetime.now().strftime('%Y-%m-%d')
            if now_str not in dedup_news:  # Daily reset
                dedup_news.clear()
            for interest in user_alerts:
                query = f"{interest} live OR result OR breaking OR score OR update india"
                news = get_news(query, timelimit='h')
                web = search_web(query)
                full_news = (news or '') + '\n' + (web or '')
                if full_news.strip():
                    snippet_str = full_news[:300].strip()
                    snippet_hash = hash(snippet_str)
                    filter_prompt = f"Relevant breaking news for '{interest}'? Yes/No: {full_news[:800]}"
                    relevant = 'yes' in ask_ai(filter_prompt).lower()
                    if relevant and snippet_hash not in dedup_news:
                        msg = f"🚨 BREAKING {interest.upper()}: {full_news[:500]}"
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        dedup_news.add(snippet_hash)

            save_prices({user_id: user_prices})
        except Exception as e:
            print(f"Proactive error: {e}")
        await asyncio.sleep(1800)  # 30min

async def start_proactive(chat_id, context, user_id):
    task = asyncio.create_task(proactive_news(chat_id, context, str(user_id)))
    return task
