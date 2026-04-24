"""tradelab.live — Pine webhook receiver + live execution bridge.

Session 1 prototype: receives TradingView strategy alerts via POST /webhook,
validates them against the card registry, submits Alpaca paper orders.

Run with: python -m uvicorn tradelab.live.receiver:app --host 0.0.0.0 --port 8878
"""
