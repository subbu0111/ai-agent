from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import asyncio

from config import TELEGRAM_TOKEN, ALLOWED_USER_IDS
from ai_client import ask_ai_natural
from modules.trading.tasks.reminder import set_reminder
from modules.trading.tasks.executor import run_command
from modules.trading.tasks.realtime_monitor import track_asset
import modules.trading.tasks.alerts as alerts
chat_history = {}  # Short-term: per-user messages

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    await update.message.reply_text("🔊 Voice received! Transcription coming soon (add WHISPER_KEY). 📝")




def check_access(update):
    return update.effective_user.id in ALLOWED_USER_IDS


def safe_reply(text):
    if not text or text.strip() == "":
        return "❌ No response generated"
    return text


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return

    text_lower = update.message.text.lower()
    text = text_lower
    print("Incoming:", text)

    # Route trading/manual
    if any(kw in text_lower for kw in ['stock', 'nifty', 'chart', 'price', 'btc', 'nasdaq']):
        # Trading logic follows
        pass
    elif any(kw in text_lower for kw in ['news', 'deal', 'breaking']):
        from modules.trading.tools.search import get_news
        news = get_news(text_lower.replace('news ', ''), timelimit='d')
        await update.message.reply_text(news or "No recent news.")
        return

    # ⚙️ RUN COMMAND
    if text.startswith("alert "):
        # alert INFY.NS 1200
        parts = text.replace("alert ", "").split()
        if len(parts) == 2:
            asset, thresh = parts
            asyncio.create_task(alerts.monitor_price(asset, float(thresh), context, update.effective_chat.id))
            await update.message.reply_text(f"🔔 Alert set for {asset} at ₹{thresh}")
        return
    if text.startswith("run "):
        cmd = text.replace("run ", "")
        output = run_command(cmd)
        await update.message.reply_text(safe_reply(output))
        return

    # ⏰ REMINDER
    if "remind me" in text:
        try:
            parts = text.split()
            sec = int([x for x in parts if x.isdigit()][0])
            msg = text.split(str(sec))[-1]

            asyncio.create_task(
                set_reminder(sec, msg, context, update.effective_chat.id)
            )

            await update.message.reply_text("⏰ Reminder set")
        except:
            await update.message.reply_text("❌ Failed to set reminder")
        return

    # � TRACKING (keep special)
    if "track" in text:
        if "bitcoin" in text:
            asset = "bitcoin"
        elif "bank" in text and "nifty" in text:
            asset = "^NSEBANK"
        elif "nifty" in text:
            asset = "^NSEI"
        else:
            await update.message.reply_text("❌ Unknown asset")
            return

        asyncio.create_task(
            track_asset(context, update.effective_chat.id, asset)
        )

        await update.message.reply_text(f"📡 Tracking {asset}")
        return

    # 🧠 Smart GPT: Always LLM + search
    await update.message.reply_text("🤖 Thinking...")


    # 📊 CHARTS
    if any(word in text_lower for word in ['chart', 'graph', 'plot']):
        from modules.trading.tools.charts import generate_chart
        from modules.trading.nifty500 import NIFTY500_MAP
        words = [w.lower() for w in text_lower.split()]
        
        # Crypto first
        CRYPTO_MAP = {'bitcoin': 'BTC-USD', 'btc': 'BTC-USD', 'ethereum': 'ETH-USD', 'eth': 'ETH-USD'}
        symbol = None
        for kw, sym in CRYPTO_MAP.items():
            if kw in words:
                symbol = sym
                break
        
        # NASDAQ
        if not symbol:
            NASDAQ_MAP = {
                'nasdaq': '^IXIC',
                'apple': 'AAPL', 'aapl': 'AAPL',
                'microsoft': 'MSFT', 'msft': 'MSFT',
                'nvidia': 'NVDA', 'nvda': 'NVDA',
                'amazon': 'AMZN', 'amzn': 'AMZN',
                'google': 'GOOGL', 'alphabet': 'GOOGL',
                'tesla': 'TSLA', 'tsla': 'TSLA',
                'meta': 'META', 'facebook': 'META'
            }
            for kw, sym in NASDAQ_MAP.items():
                if kw in words:
                    symbol = sym
                    break
        
        # Nifty 500
        if not symbol:
            symbol_name = None
            for name in NIFTY500_MAP:
                short_name = name.split()[0].lower()
                if short_name in words:
                    symbol_name = name
                    break
            symbol = NIFTY500_MAP.get(symbol_name, '^NSEI')
        
        import re
        # Interval parse
        int_match = re.search(r'(\d+)\s*(minutes?|min|hours?|h|days?|d)', text_lower, re.I)
        interval = '1d'
        if int_match:
            num = int(int_match.group(1))
            unit = int_match.group(2).lower()
            if 'min' in unit or 'minute' in unit:
                if num == 1:
                    interval = '1m'
                elif num == 2:
                    interval = '2m'
                elif num <= 5:
                    interval = '5m'
                elif num == 10:
                    interval = '15m'  # No 10m, closest
                elif num <= 15:
                    interval = '15m'
                elif num <= 30:
                    interval = '30m'
                elif num <= 60:
                    interval = '1h'
            elif 'hour' in unit or 'h' in unit:
                interval = '1h'
            elif 'day' in unit or 'd' in unit:
                interval = '1d'

        # Period parse (existing + days/weeks)
        period_map = {
            '1d': '1d', 'daily': '1d', 'day': '1d',
            '5d': '5d', 'week': '5d', '1 week': '5d',
            '1mo': '1mo', 'month': '1mo',
            '2mo': '2mo', '2 months': '2mo',
            '3mo': '3mo', '3 months': '3mo',
            '6mo': '6mo', '6 months': '6mo',
            '1y': '1y', 'year': '1y', '12mo': '1y',
            '2y': '2y', 'ytd': 'ytd', 'max': 'max'
        }
        period_words = text_lower.split()
        period = '1mo'
        for p in period_words:
            if p in period_map:
                period = period_map[p]
                break
        # Default short period for intraday
        if interval != '1d':
            if 'mo' in period or period == '1mo':
                period = '5d'
        # Num days/months
        day_match = re.search(r'(\d+)\s*(day|days?|week|weeks?)(?:s?)', text_lower, re.I)
        target_days = None
        if day_match:
            num = int(day_match.group(1))
            unit = day_match.group(2).lower()
            if unit.startswith('day'):
                target_days = num
            elif unit.startswith('week'):
                target_days = num * 5  # Approx trading days
        # ... (keep existing period logic)
        mo_match = re.search(r'(\d+)\s*(mo|month|months?)(?:s?)', text_lower, re.I)
        if mo_match:
            num_mo = int(mo_match.group(1))
            if num_mo == 1:
                period = '1mo'
            elif num_mo <= 3:
                period = f'{num_mo}mo'
            elif num_mo <= 6:
                period = '6mo'
            elif num_mo <= 12:
                period = '1y'
            else:
                period = '2y'
        buffer = generate_chart(symbol, period, interval, target_trading_days=target_days)
        if buffer:
            is_nse = symbol.endswith('.NS') or symbol.startswith('^NSE')
            is_crypto = '-USD' in symbol
            suffix = 'Trading Hours IST' if is_nse else ('24/7 UTC' if is_crypto else 'NASDAQ/Full')
            caption = f"📊 {symbol} {period.upper()} ({interval}) - {suffix} - Last {target_days or ''} Days"
            await update.message.reply_photo(photo=buffer, caption=caption)
        else:
            await update.message.reply_photo(photo=buffer, caption=f"❌ Chart failed for {symbol} {period} ({interval})")
        return

    user_id = update.effective_user.id
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append({"role": "user", "content": update.message.text})
    if len(chat_history[user_id]) > 10:
        chat_history[user_id] = chat_history[user_id][-10:]  # Short-term limit
    result = ask_ai_natural(update.message.text, chat_history[user_id])
    chat_history[user_id].append({"role": "assistant", "content": str(result)})
    if isinstance(result, tuple) and result[0] == 'chart_buffer':
        await update.message.reply_photo(photo=result[1], caption="📊 Live Chart")
    else:
        await update.message.reply_text(safe_reply(result))


print("🚀 Reactive Smart GPT Bot READY!")
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.run_polling()