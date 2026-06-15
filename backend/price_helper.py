import os
import yfinance as yf
import requests
from datetime import datetime, timedelta

def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def add_months(sourcedate, months):
    from datetime import timedelta
    is_last = (sourcedate + timedelta(days=1)).day == 1
    
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    
    last_day = [31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month-1]
        
    day = last_day if is_last else min(sourcedate.day, last_day)
    return datetime(year, month, day)

def get_quarter_end_date(year, qtr_month):
    if qtr_month == 'Mar':
        return f"{year}-03-31"
    elif qtr_month == 'Jun':
        return f"{year}-06-30"
    elif qtr_month == 'Sep':
        return f"{year}-09-30"
    elif qtr_month == 'Dec':
        return f"{year}-12-31"
    return None

class PriceFetcher:
    def __init__(self, scrip_code, symbol=None, company_name=None):
        self.scrip_code = scrip_code
        self.history = None
        
        # Prioritize symbol ticker over scrip code ticker, and try NSE (.NS) then BSE (.BO)
        ticker_options = []
        if symbol and not symbol.isdigit() and "BSE_" not in symbol:
            ticker_options.append(f"{symbol.upper()}.NS")
            ticker_options.append(f"{symbol.upper()}.BO")
            
        # Try to resolve alphabetical ticker from Yahoo search using company name
        resolved_search_ticker = self._resolve_via_search(company_name)
        if resolved_search_ticker:
            ticker_options.append(resolved_search_ticker)
            base_symbol = resolved_search_ticker.split(".")[0]
            if resolved_search_ticker.endswith(".NS"):
                ticker_options.append(f"{base_symbol}.BO")
            else:
                ticker_options.append(f"{base_symbol}.NS")
                
        if scrip_code:
            if scrip_code.isdigit():
                ticker_options.append(f"{scrip_code}.BO")
            else:
                ticker_options.append(f"{scrip_code.upper()}.NS")
                ticker_options.append(f"{scrip_code.upper()}.BO")
                
        # Deduplicate
        seen = set()
        ticker_options = [x for x in ticker_options if not (x in seen or seen.add(x))]
        
        best_ticker = None
        best_start_date = None
        best_history = None
        
        for ticker_opt in ticker_options:
            print(f"Attempting to fetch price history for: {ticker_opt}")
            try:
                session = get_session()
                ticker = yf.Ticker(ticker_opt, session=session)
                df = ticker.history(period="max", auto_adjust=False)
                if not df.empty:
                    df.index = df.index.tz_localize(None)
                    start_date = df.index.min()
                    print(f"  Ticker {ticker_opt} start date: {start_date.strftime('%Y-%m-%d')}, shape: {df.shape}")
                    if best_start_date is None or start_date < best_start_date:
                        best_start_date = start_date
                        best_ticker = ticker_opt
                        best_history = df
            except Exception as e:
                print(f"Error fetching price history for {ticker_opt}: {e}")
                
        if best_ticker:
            print(f"Selected best ticker: {best_ticker} (earliest date: {best_start_date.strftime('%Y-%m-%d')})")
            self.ticker_symbol = best_ticker
            self.history = best_history
        else:
            self.ticker_symbol = f"{scrip_code}.NS" if not scrip_code.isdigit() else f"{scrip_code}.BO"
            self.history = None

    def _resolve_via_search(self, company_name):
        if not company_name:
            return None
            
        name = str(company_name).upper()
        # Remove common corporate suffixes to improve search matching
        for suffix in [" LTD", " LIMITED", " CORP", " CORPORATION", " INDIA"]:
            name = name.replace(suffix, "")
        query = name.strip()
        
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                quotes = data.get("quotes", [])
                for q in quotes:
                    symbol = q.get("symbol", "")
                    if symbol.endswith(".NS") or symbol.endswith(".BO"):
                        print(f"Yahoo Search resolved '{company_name}' to ticker: {symbol}")
                        return symbol
        except Exception as e:
            print(f"Error searching Yahoo ticker for {query}: {e}")
        return None

    def _fetch_history(self, ticker_str):
        try:
            session = get_session()
            ticker = yf.Ticker(ticker_str, session=session)
            # Use auto_adjust=False to get split-adjusted Close (not dividend adjusted) to match standard charts
            df = ticker.history(period="max", auto_adjust=False)
            if not df.empty:
                df.index = df.index.tz_localize(None)
                self.history = df
                return True
        except Exception as e:
            print(f"Error fetching price history for {ticker_str}: {e}")
        return False
        
    def get_price_on_date(self, target_date_str):
        if self.history is None or self.history.empty:
            return None
            
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
            # If target date is in the future relative to today
            if target_date > datetime.today():
                return None
                
            max_date = self.history.index.max()
            # If target date is too far in the future compared to history
            if target_date > max_date + timedelta(days=7):
                return None
                
            idx = self.history.index
            # Find closest date within a 10-day window
            valid_indices = idx[abs(idx - target_date) <= timedelta(days=10)]
            if valid_indices.empty:
                return None
                
            closest_date = min(valid_indices, key=lambda d: abs(d - target_date))
            price = self.history.loc[closest_date]["Close"]
            return float(price)
        except Exception as e:
            print(f"Error finding price on {target_date_str} for scrip {self.scrip_code}: {e}")
            return None
