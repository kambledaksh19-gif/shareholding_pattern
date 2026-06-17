import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from bsedata.bse import BSE

# Create cache directory if it doesn't exist
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    CACHE_DIR = "/tmp/cache"
else:
    CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
}

def clean_int(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    val_str = str(val).strip().replace(",", "")
    if not val_str or val_str == "-" or val_str == "--":
        return 0
    try:
        return int(float(val_str))
    except ValueError:
        return 0

def clean_float(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip().replace(",", "").replace("%", "")
    if not val_str or val_str == "-" or val_str == "--":
        return 0.0
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def clean_str(val):
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str or val_str == "-" or val_str == "--":
        return None
    return val_str

def search_companies(query):
    """
    Searches for companies on BSE and returns list of dicts with scrip_code, symbol, company_name.
    """
    query = str(query).strip()
    if not query:
        return []
    url = f"https://api.bseindia.com/Msource/1D/GetQuoteAllSearch.aspx?&text={query}&flag=site"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for a in soup.find_all('a'):
            href = a.get('href', '')
            m = re.search(r'/(\d{6})/?$', href)
            if m:
                scrip_code = m.group(1)
                span = a.find('span')
                symbol = ""
                if span:
                    strong = span.find('strong')
                    if strong:
                        symbol = strong.text.strip()
                first_child = a.contents[0] if a.contents else None
                if first_child:
                    comp_name = first_child.strip() if isinstance(first_child, str) else first_child.text.strip()
                else:
                    comp_name = a.text.strip()
                
                results.append({
                    "scrip_code": scrip_code,
                    "company_name": comp_name,
                    "symbol": symbol
                })
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error searching companies for '{query}': {e}")
        return []

def resolve_scrip_code(symbol_or_code):
    """
    Resolves symbol (e.g. SBIN) or code (e.g. 500112) to (scrip_code, company_name)
    """
    symbol_or_code = str(symbol_or_code).strip()
    if symbol_or_code.isdigit() and len(symbol_or_code) == 6:
        try:
            res = search_companies(symbol_or_code)
            if res:
                return res[0]["scrip_code"], res[0]["company_name"]
            return symbol_or_code, f"Company {symbol_or_code}"
        except:
            return symbol_or_code, f"Company {symbol_or_code}"
            
    try:
        res = search_companies(symbol_or_code.upper())
        for item in res:
            if item["symbol"].upper() == symbol_or_code.upper():
                return item["scrip_code"], item["company_name"]
        if res:
            return res[0]["scrip_code"], res[0]["company_name"]
    except Exception as e:
        print(f"Error resolving symbol {symbol_or_code}: {e}")
    return None, None


def fetch_filings_list(scrip_code):
    """
    Fetches the historical filings list from BSE India API
    """
    url = f"https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?qtrid=85.00&scripcode={scrip_code}"
    print(f"Fetching filings list from {url}...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("Table", [])
    except Exception as e:
        print(f"Error fetching filings list for {scrip_code}: {e}")
    return []

def get_march_endings(filings):
    """
    Filters filings to get only March endings.
    Groups by year to take the revised filings if present.
    """
    march_filings = []
    for f in filings:
        qtr = str(f.get("qtr", "")).lower()
        if "march" in qtr or "31 mar" in qtr or "mar-" in qtr:
            march_filings.append(f)
            
    # Group by year to handle duplicates / revised filings
    # A year could be represented by "2025 - 2026", "2025-26", "2025" etc.
    # Let's clean the year or extract the year number from Qtr
    # Qtr format example: "March 2026", "31 Mar 2007"
    by_year = {}
    for f in march_filings:
        qtr_name = f.get("qtr", "")
        # Extract 4 digit year
        yr_match = re.search(r'\b(20\d{2}|19\d{2})\b', qtr_name)
        if yr_match:
            year = int(yr_match.group(1))
        else:
            # Try to parse from yr field (e.g. "2025 - 2026" -> we want March 2026)
            yr_field = str(f.get("yr", ""))
            yr_match = re.findall(r'\b(20\d{2}|19\d{2})\b', yr_field)
            if yr_match:
                year = int(yr_match[-1])  # Take the ending year
            else:
                continue
                
        qtr_id = float(f.get("qtrid", 0.0))
        
        # If year already exists, keep the one with higher qtr_id (typically revised has higher index, e.g. 129.01 vs 129.0)
        if year not in by_year:
            by_year[year] = f
        else:
            existing_qtr_id = float(by_year[year].get("qtrid", 0.0))
            if qtr_id > existing_qtr_id:
                by_year[year] = f
                
    return by_year

def fetch_modern_data(scrip_code, qtr_id):
    """
    Fetches shareholding data for qtr_id >= 88.00 using JSON APIs
    """
    qtr_code_str = f"{qtr_id:.2f}"
    urls = {
        "promoter": f"https://api.bseindia.com/BseIndiaAPI/api/Corp_shpPromoterNGroup_ng/w?SCRIPCODE={scrip_code}&QtrCode={qtr_code_str}",
        "public": f"https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPPubShold_ng/w?SCRIPCODE={scrip_code}&QtrCode={qtr_code_str}",
        "non_promoter": f"https://api.bseindia.com/BseIndiaAPI/api/Corp_SHPNonPromoterNonPublic_ng/w?SCRIPCODE={scrip_code}&QtrCode={qtr_code_str}"
    }
    
    result = {
        "summary": [],
        "promoter": [],
        "public": [],
        "non_promoter": []
    }
    
    # 1. Fetch Promoter Details
    try:
        r = requests.get(urls["promoter"], headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            table1 = data.get("Table1", [])
            for row in table1:
                result["promoter"].append({
                    "code": clean_str(row.get("Fld_Code")),
                    "category": clean_str(row.get("Fld_ShortCatg")),
                    "sub_category": clean_str(row.get("Fld_SubCategory")),
                    "shareholder_name": clean_str(row.get("Fld_ShareHolderName")),
                    "shares": clean_int(row.get("Fld_TotalNoOfShares") or row.get("Fld_NoOfFullyPaidShares")),
                    "percentage": clean_float(row.get("Fld_TotalPercentageOf_A_B_C2") or row.get("Fld_PercentAfterFullConversion")),
                    "demat_shares": clean_int(row.get("Fld_DematerializedForm")),
                    "pledged_shares": clean_int(row.get("Fld_PledgeEncumberedNoOfShares")),
                    "pledged_percentage": clean_float(row.get("Fld_PledgeEncumberedPercentage")),
                    "no_shareholders": clean_int(row.get("Fld_NoOfShareHolders"))
                })
    except Exception as e:
        print(f"Error fetching modern promoter data: {e}")
        
    # 2. Fetch Public Details
    try:
        r = requests.get(urls["public"], headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            table1 = data.get("Table1", [])
            for row in table1:
                result["public"].append({
                    "code": clean_str(row.get("Fld_Code")),
                    "category": clean_str(row.get("Fld_ShortCatg")),
                    "sub_category": clean_str(row.get("Fld_SubCategory")),
                    "shareholder_name": clean_str(row.get("Fld_ShareHolderName")),
                    "shares": clean_int(row.get("Fld_TotalNoOfShares") or row.get("Fld_NoOfFullyPaidShares")),
                    "percentage": clean_float(row.get("Fld_TotalPercentageOf_A_B_C2") or row.get("Fld_PercentAfterFullConversion")),
                    "demat_shares": clean_int(row.get("Fld_DematerializedForm")),
                    "no_shareholders": clean_int(row.get("Fld_NoOfShareHolders"))
                })
    except Exception as e:
        print(f"Error fetching modern public data: {e}")

    # 3. Fetch Non-Promoter Details
    try:
        r = requests.get(urls["non_promoter"], headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            table1 = data.get("Table1", [])
            for row in table1:
                result["non_promoter"].append({
                    "code": clean_str(row.get("Fld_Code")),
                    "category": clean_str(row.get("Fld_ShortCatg")),
                    "sub_category": clean_str(row.get("Fld_SubCategory")),
                    "shareholder_name": clean_str(row.get("Fld_ShareHolderName")),
                    "shares": clean_int(row.get("Fld_TotalNoOfShares") or row.get("Fld_NoOfFullyPaidShares")),
                    "percentage": clean_float(row.get("Fld_TotalPercentageOf_A_B_C2") or row.get("Fld_PercentAfterFullConversion")),
                    "demat_shares": clean_int(row.get("Fld_DematerializedForm")),
                    "no_shareholders": clean_int(row.get("Fld_NoOfShareHolders"))
                })
    except Exception as e:
        print(f"Error fetching modern non-promoter data: {e}")
        
    # 4. Generate Summary Statement from detail tables totals
    # We will search the promoter, public, and non-promoter lists for top-level subtotal codes
    # In SEBI format: A = Promoter, B = Public, C = Non-Promoter, Grand Total = A+B+C
    promoter_total_shares = 0
    promoter_total_percent = 0.0
    promoter_demat_shares = 0
    promoter_pledged_shares = 0
    promoter_pledged_percent = 0.0
    promoter_shareholders = 0
    
    # In Promoter, the main subtotal is STA1A2 or Category "Promoter and Promoter Group" where name is None
    for row in result["promoter"]:
        if row["code"] == "STA1A2" or (row["category"] == "Promoter and Promoter Group" and row["shareholder_name"] is None and row["sub_category"] is None):
            promoter_total_shares = row["shares"]
            promoter_total_percent = row["percentage"]
            promoter_demat_shares = row["demat_shares"]
            promoter_pledged_shares = row["pledged_shares"]
            promoter_pledged_percent = row["pledged_percentage"]
            promoter_shareholders = row["no_shareholders"]
            break
    else:
        # Fallback: sum up categories
        for row in result["promoter"]:
            if row["shareholder_name"] is None and row["sub_category"] in ["Indian", "Foreign"] and row["shares"] > 0:
                promoter_total_shares += row["shares"]
                promoter_total_percent += row["percentage"]
                promoter_demat_shares += row["demat_shares"]
                promoter_pledged_shares += row["pledged_shares"]
                promoter_shareholders += row["no_shareholders"]
        if promoter_total_shares > 0 and promoter_pledged_shares > 0:
            promoter_pledged_percent = (promoter_pledged_shares / promoter_total_shares) * 100.0
            
    public_total_shares = 0
    public_total_percent = 0.0
    public_demat_shares = 0
    public_shareholders = 0
    
    # In Public, search for total public shareholding row (usually Category "Public shareholder" total)
    for row in result["public"]:
        if row["code"] in ["STB1B2B3", "STB"] or (row["category"] == "Public shareholder" and row["shareholder_name"] is None and row["sub_category"] is None and row["shares"] > 0):
            public_total_shares = row["shares"]
            public_total_percent = row["percentage"]
            public_demat_shares = row["demat_shares"]
            public_shareholders = row["no_shareholders"]
            break
    else:
        # Fallback: sum up Institutions and Non-Institutions
        for row in result["public"]:
            if row["shareholder_name"] is None and row["sub_category"] in ["Institutions", "Non-Institutions"] and row["shares"] > 0:
                public_total_shares += row["shares"]
                public_total_percent += row["percentage"]
                public_demat_shares += row["demat_shares"]
                public_shareholders += row["no_shareholders"]

    non_promoter_total_shares = 0
    non_promoter_total_percent = 0.0
    non_promoter_demat_shares = 0
    non_promoter_shareholders = 0
    
    for row in result["non_promoter"]:
        if row["code"] in ["STC1C2", "STC"] or (row["category"] == "Non Promoter- Non Public shareholder" and row["shareholder_name"] is None and row["sub_category"] is None and row["shares"] > 0):
            non_promoter_total_shares = row["shares"]
            non_promoter_total_percent = row["percentage"]
            non_promoter_demat_shares = row["demat_shares"]
            non_promoter_shareholders = row["no_shareholders"]
            break
    else:
        # Fallback
        for row in result["non_promoter"]:
            if row["shareholder_name"] is None and row["shares"] > 0:
                non_promoter_total_shares += row["shares"]
                non_promoter_total_percent += row["percentage"]
                non_promoter_demat_shares += row["demat_shares"]
                non_promoter_shareholders += row["no_shareholders"]
                
    grand_total_shares = promoter_total_shares + public_total_shares + non_promoter_total_shares
    grand_total_percent = promoter_total_percent + public_total_percent + non_promoter_total_percent
    grand_demat_shares = promoter_demat_shares + public_demat_shares + non_promoter_demat_shares
    grand_shareholders = promoter_shareholders + public_shareholders + non_promoter_shareholders
    
    result["summary"] = [
        {
            "category": "(A) Promoter & Promoter Group",
            "no_shareholders": promoter_shareholders,
            "shares": promoter_total_shares,
            "percentage": promoter_total_percent,
            "demat_shares": promoter_demat_shares,
            "pledged_shares": promoter_pledged_shares,
            "pledged_percentage": promoter_pledged_percent
        },
        {
            "category": "(B) Public",
            "no_shareholders": public_shareholders,
            "shares": public_total_shares,
            "percentage": public_total_percent,
            "demat_shares": public_demat_shares,
            "pledged_shares": 0,
            "pledged_percentage": 0.0
        },
        {
            "category": "(C) Non Promoter-Non Public",
            "no_shareholders": non_promoter_shareholders,
            "shares": non_promoter_total_shares,
            "percentage": non_promoter_total_percent,
            "demat_shares": non_promoter_demat_shares,
            "pledged_shares": 0,
            "pledged_percentage": 0.0
        },
        {
            "category": "Grand Total",
            "no_shareholders": grand_shareholders,
            "shares": grand_total_shares,
            "percentage": grand_total_percent,
            "demat_shares": grand_demat_shares,
            "pledged_shares": promoter_pledged_shares,
            "pledged_percentage": (promoter_pledged_shares / grand_total_shares * 100.0) if grand_total_shares > 0 and promoter_pledged_shares > 0 else 0.0
        }
    ]
    
    return result

def scrape_legacy_data(scrip_code, qtr_id, nav_url):
    """
    Scrapes shareholding data for qtr_id < 88.00 from legacy ASPX endpoints
    """
    if not nav_url:
        nav_url = f"https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd={scrip_code}&flag_qtr=1&qtrid={qtr_id}&Flag=New"
    elif nav_url.startswith("/"):
        nav_url = "https://www.bseindia.com" + nav_url
        
    print(f"Scraping legacy URL: {nav_url}")
    result = {
        "summary": [],
        "promoter": [],
        "public": [],
        "non_promoter": []
    }
    
    try:
        r = requests.get(nav_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"Failed to fetch legacy summary page: {r.status_code}")
            return result
            
        soup = BeautifulSoup(r.text, 'html.parser')
        tables = soup.find_all('table')
        
        # 1. Parse Summary Statement
        # We need to find the table that has columns: 'Category of Shareholder' and 'Total No. of Shares'
        summary_table = None
        for t in tables:
            rows = t.find_all('tr')
            if len(rows) > 5:
                header_text = "".join([cell.text for cell in rows[0].find_all(['td', 'th'])]).lower()
                if 'category of shareholder' in header_text and 'total no. of shares' in header_text:
                    summary_table = t
                    break
                    
        # Check for old style pre-2007 table (three-column layout: Category, No.of Shares Held, % of Share Holding)
        is_old_style = False
        old_style_table = None
        for t in tables:
            if t.find('table'):  # Skip outer tables that contain nested tables!
                continue
            rows = t.find_all('tr')
            for r in rows:
                cells = [c.text.strip().lower() for c in r.find_all(['td', 'th'])]
                if len(cells) == 3 and 'category' in cells[0] and 'shares held' in cells[1] and 'share holding' in cells[2]:
                    old_style_table = t
                    is_old_style = True
                    break
            if is_old_style:
                break

        if summary_table:
            # We parse the summary rows:
            # Typically:
            # (A) Promoter & Promoter Group total
            # (B) Public total
            # (C) Non-Promoter Non-Public total (Custodians)
            rows = summary_table.find_all('tr')
            for r_idx, row in enumerate(rows):
                cells = [c.text.strip() for c in row.find_all(['td', 'th'])]
                if not cells:
                    continue
                label = cells[0]
                
                # Check for categories
                if "total shareholding of promoter and promoter group (a)" in label.lower() or "(a) shareholding of promoter and promoter group" in label.lower():
                    # We extract values:
                    # Column layout can be variable but usually:
                    # Label, Shareholders, Total Shares, Demat Shares, %, %, Pledged, Pledged %
                    if len(cells) >= 6:
                        result["summary"].append({
                            "category": "(A) Promoter & Promoter Group",
                            "no_shareholders": clean_int(cells[1] if cells[1] else cells[2]),
                            "shares": clean_int(cells[2] if cells[1] else cells[3]),
                            "percentage": clean_float(cells[5] if len(cells) > 5 else (cells[4] if len(cells) > 4 else 0)),
                            "demat_shares": clean_int(cells[3] if len(cells) > 3 else 0),
                            "pledged_shares": clean_int(cells[6] if len(cells) > 6 else 0),
                            "pledged_percentage": clean_float(cells[7] if len(cells) > 7 else 0)
                        })
                elif "total public shareholding (b)" in label.lower() or "(b) public shareholding" in label.lower():
                    if len(cells) >= 6:
                        result["summary"].append({
                            "category": "(B) Public",
                            "no_shareholders": clean_int(cells[1] if cells[1] else cells[2]),
                            "shares": clean_int(cells[2] if cells[1] else cells[3]),
                            "percentage": clean_float(cells[5] if len(cells) > 5 else (cells[4] if len(cells) > 4 else 0)),
                            "demat_shares": clean_int(cells[3] if len(cells) > 3 else 0),
                            "pledged_shares": 0,
                            "pledged_percentage": 0.0
                        })
                elif "total (a)+(b)+(c)" in label.lower():
                    if len(cells) >= 6:
                        result["summary"].append({
                            "category": "Grand Total",
                            "no_shareholders": clean_int(cells[1] if cells[1] else cells[2]),
                            "shares": clean_int(cells[2] if cells[1] else cells[3]),
                            "percentage": clean_float(cells[5] if len(cells) > 5 else (cells[4] if len(cells) > 4 else 0)),
                            "demat_shares": clean_int(cells[3] if len(cells) > 3 else 0),
                            "pledged_shares": clean_int(cells[6] if len(cells) > 6 else 0),
                            "pledged_percentage": clean_float(cells[7] if len(cells) > 7 else 0)
                        })
                elif "shares held by custodians" in label.lower() or "sub total" in label.lower() and r_idx > 30: # typically C is near bottom
                    # Non Promoter Non Public Custodians
                    if len(cells) >= 6 and "custodian" in label.lower():
                        result["summary"].append({
                            "category": "(C) Non Promoter-Non Public",
                            "no_shareholders": clean_int(cells[1]),
                            "shares": clean_int(cells[2]),
                            "percentage": clean_float(cells[5] if len(cells) > 5 else (cells[4] if len(cells) > 4 else 0)),
                            "demat_shares": clean_int(cells[3] if len(cells) > 3 else 0),
                            "pledged_shares": 0,
                            "pledged_percentage": 0.0
                        })
            
            # Deduplicate summary rows by keeping the one with non-zero / maximum shares
            deduped = {}
            for item in result["summary"]:
                cat = item["category"]
                if cat not in deduped or item["shares"] > deduped[cat]["shares"]:
                    deduped[cat] = item
            
            # Reconstruct result["summary"] in order: A, B, Grand Total (exclude C for calculation)
            ordered_cats = ["(A) Promoter & Promoter Group", "(B) Public", "Grand Total"]
            result["summary"] = [deduped[cat] for cat in ordered_cats if cat in deduped]
            
            # Always calculate (C) Non Promoter-Non Public as Grand Total - (A + B)
            if len(result["summary"]) >= 2:
                gt = next((x for x in result["summary"] if x["category"] == "Grand Total"), None)
                p = next((x for x in result["summary"] if x["category"] == "(A) Promoter & Promoter Group"), None)
                pub = next((x for x in result["summary"] if x["category"] == "(B) Public"), None)
                if gt and p and pub:
                    c_shares = gt["shares"] - p["shares"] - pub["shares"]
                    c_percent = gt["percentage"] - p["percentage"] - pub["percentage"]
                    c_demat = gt["demat_shares"] - p["demat_shares"] - pub["demat_shares"]
                    result["summary"].insert(2, {
                        "category": "(C) Non Promoter-Non Public",
                        "no_shareholders": max(0, gt["no_shareholders"] - p["no_shareholders"] - pub["no_shareholders"]),
                        "shares": max(0, c_shares),
                        "percentage": max(0.0, c_percent),
                        "demat_shares": max(0, c_demat),
                        "pledged_shares": 0,
                        "pledged_percentage": 0.0
                    })
        elif is_old_style:
            print("Parsing legacy pre-2007 old style table...")
            rows = old_style_table.find_all('tr')
            # In old SEBI tables, Promoter is always the first section, so initialize to promoter
            current_section = "promoter"
            public_sub_section = None
            
            promoter_shares = 0
            promoter_percent = 0.0
            public_shares = 0
            public_percent = 0.0
            grand_shares = 0
            grand_percent = 0.0
            
            for row in rows:
                cells = [c.text.strip() for c in row.find_all(['td', 'th'])]
                if len(cells) < 3:
                    continue
                label = cells[0]
                shares_val = clean_int(cells[1])
                percent_val = clean_float(cells[2])
                
                label_lower = label.lower()
                label_clean = label_lower.replace(" ", "").replace("-", "")
                
                # Section detection (check non promoter's holding first to avoid substring matching issues)
                if "non promoter's holding" in label_lower:
                    current_section = "public"
                    continue
                elif "promoter's holding" in label_lower:
                    current_section = "promoter"
                    continue
                elif "institutional investors" in label_lower:
                    public_sub_section = "institutions"
                    continue
                elif "others" in label_lower and current_section == "public":
                    public_sub_section = "non_institutions"
                    continue
                    
                # Skip header, sub-header and empty rows
                if label_lower in ["category", "promoters", "any other"] or (shares_val == 0 and percent_val == 0.0):
                    continue
                    
                # Parse sub-totals and grand totals
                if label_clean == "subtotal":
                    if current_section == "promoter":
                        promoter_shares = shares_val
                        promoter_percent = percent_val
                    elif current_section == "public":
                        public_shares += shares_val
                        public_percent += percent_val
                    continue
                elif label_clean == "grandtotal":
                    grand_shares = shares_val
                    grand_percent = percent_val
                    continue
                    
                # Parse details
                if current_section == "promoter":
                    result["promoter"].append({
                        "code": "A1",
                        "category": "Promoter and Promoter Group",
                        "sub_category": "Promoters",
                        "shareholder_name": label,
                        "shares": shares_val,
                        "percentage": percent_val,
                        "demat_shares": shares_val,
                        "pledged_shares": 0,
                        "pledged_percentage": 0.0,
                        "no_shareholders": 1
                    })
                elif current_section == "public":
                    sub_cat = "Institutions" if public_sub_section == "institutions" else "Non-Institutions"
                    result["public"].append({
                        "code": "B1" if public_sub_section == "institutions" else "B3",
                        "category": "Public shareholder",
                        "sub_category": sub_cat,
                        "shareholder_name": label,
                        "shares": shares_val,
                        "percentage": percent_val,
                        "demat_shares": shares_val,
                        "no_shareholders": 1
                    })
            
            # Populate summary
            result["summary"] = [
                {
                    "category": "(A) Promoter & Promoter Group",
                    "no_shareholders": len(result["promoter"]),
                    "shares": promoter_shares,
                    "percentage": promoter_percent,
                    "demat_shares": promoter_shares,
                    "pledged_shares": 0,
                    "pledged_percentage": 0.0
                },
                {
                    "category": "(B) Public",
                    "no_shareholders": len(result["public"]),
                    "shares": public_shares,
                    "percentage": public_percent,
                    "demat_shares": public_shares,
                    "pledged_shares": 0,
                    "pledged_percentage": 0.0
                },
                {
                    "category": "(C) Non Promoter-Non Public",
                    "no_shareholders": 0,
                    "shares": 0,
                    "percentage": 0.0,
                    "demat_shares": 0,
                    "pledged_shares": 0,
                    "pledged_percentage": 0.0
                },
                {
                    "category": "Grand Total",
                    "no_shareholders": len(result["promoter"]) + len(result["public"]),
                    "shares": grand_shares,
                    "percentage": grand_percent,
                    "demat_shares": grand_shares,
                    "pledged_shares": 0,
                    "pledged_percentage": 0.0
                }
            ]
        
        # 2. Extract Sub-page URLs from onclick handlers
        links = soup.find_all('a')
        detail_urls = {}
        for l in links:
            onclick = l.get('onclick', '')
            text = l.text.strip().lower()
            if 'window.open' in onclick:
                # Extract URL from window.open("url", ...)
                url_match = re.search(r'window\.open\("([^"]+)"', onclick)
                if url_match:
                    page_path = url_match.group(1)
                    full_page_url = "https://www.bseindia.com/corporates/" + page_path
                    
                    if "promoter and promoter group" in text:
                        detail_urls["promoter"] = full_page_url
                    elif "public" in text and "1%" in text:
                        detail_urls["public"] = full_page_url
                    elif "custodian" in text or "depository receipts" in text:
                        detail_urls["non_promoter"] = full_page_url
                        
        print(f"Found detail URLs: {list(detail_urls.keys())}")
        
        # 3. Fetch and Parse Promoter Details
        if "promoter" in detail_urls:
            try:
                pr = requests.get(detail_urls["promoter"], headers=HEADERS, timeout=15)
                if pr.status_code == 200:
                    p_soup = BeautifulSoup(pr.text, 'html.parser')
                    p_tables = p_soup.find_all('table')
                    # Find table listing promoters (contains 'President of India' or similar)
                    for pt in p_tables:
                        p_rows = pt.find_all('tr')
                        if len(p_rows) > 3:
                            # Verify if it has shareholder names
                            is_promoter_detail = False
                            for row in p_rows:
                                row_text = row.text.lower()
                                if 'name of the shareholder' in row_text or 'shareholder name' in row_text:
                                    is_promoter_detail = True
                                    break
                            if is_promoter_detail:
                                # Parse the promoter rows
                                for row in p_rows:
                                    cells = [c.text.strip() for c in row.find_all(['td', 'th'])]
                                    if len(cells) >= 4 and cells[0].isdigit():
                                        # Sl.No, Name, Shares, %
                                        result["promoter"].append({
                                            "code": "A1b",
                                            "category": "Promoter and Promoter Group",
                                            "sub_category": "Indian",
                                            "shareholder_name": clean_str(cells[1]),
                                            "shares": clean_int(cells[2]),
                                            "percentage": clean_float(cells[3]),
                                            "demat_shares": clean_int(cells[2]), # Assume demat
                                            "pledged_shares": clean_int(cells[4] if len(cells) > 4 else 0),
                                            "pledged_percentage": clean_float(cells[5] if len(cells) > 5 else 0.0),
                                            "no_shareholders": 1
                                        })
                                break
            except Exception as e:
                print(f"Error fetching legacy promoter details: {e}")
                
        # 4. Fetch and Parse Public Details (>1%)
        if "public" in detail_urls:
            try:
                pur = requests.get(detail_urls["public"], headers=HEADERS, timeout=15)
                if pur.status_code == 200:
                    pub_soup = BeautifulSoup(pur.text, 'html.parser')
                    pub_tables = pub_soup.find_all('table')
                    for pub_t in pub_tables:
                        pub_rows = pub_t.find_all('tr')
                        if len(pub_rows) > 3:
                            is_public_detail = False
                            for row in pub_rows:
                                row_text = row.text.lower()
                                if 'name of the shareholder' in row_text or 'shareholder name' in row_text:
                                    is_public_detail = True
                                    break
                            if is_public_detail:
                                for row in pub_rows:
                                    cells = [c.text.strip() for c in row.find_all(['td', 'th'])]
                                    if len(cells) >= 4 and cells[0].isdigit():
                                        # Sl.No, Name, Shares, %
                                        result["public"].append({
                                            "code": "B1",
                                            "category": "Public shareholder",
                                            "sub_category": "Institutions / Non-Institutions (>1%)",
                                            "shareholder_name": clean_str(cells[1]),
                                            "shares": clean_int(cells[2]),
                                            "percentage": clean_float(cells[3]),
                                            "demat_shares": clean_int(cells[2]),
                                            "no_shareholders": 1
                                        })
                                break
            except Exception as e:
                print(f"Error fetching legacy public details: {e}")

        # 5. Fetch and Parse Non-Promoter details (DRs / Custodians)
        if "non_promoter" in detail_urls:
            try:
                npr = requests.get(detail_urls["non_promoter"], headers=HEADERS, timeout=15)
                if npr.status_code == 200:
                    np_soup = BeautifulSoup(npr.text, 'html.parser')
                    np_tables = np_soup.find_all('table')
                    for np_t in np_tables:
                        np_rows = np_t.find_all('tr')
                        if len(np_rows) > 2:
                            is_np_detail = False
                            for row in np_rows:
                                row_text = row.text.lower()
                                if 'name of the' in row_text or 'shareholder name' in row_text or 'custodian' in row_text:
                                    is_np_detail = True
                                    break
                            if is_np_detail:
                                for row in np_rows:
                                    cells = [c.text.strip() for c in row.find_all(['td', 'th'])]
                                    if len(cells) >= 4 and (cells[0].isdigit() or (len(cells[0]) > 0 and cells[0][0].isdigit())):
                                        result["non_promoter"].append({
                                            "code": "C1",
                                            "category": "Non Promoter- Non Public shareholder",
                                            "sub_category": "Custodian/DR Holder",
                                            "shareholder_name": clean_str(cells[1]),
                                            "shares": clean_int(cells[2]),
                                            "percentage": clean_float(cells[3]),
                                            "demat_shares": clean_int(cells[2]),
                                            "no_shareholders": 1
                                        })
                                break
            except Exception as e:
                print(f"Error fetching legacy non-promoter details: {e}")
                
    except Exception as e:
        print(f"Error parsing legacy layout: {e}")
        
    return result

def filter_years_with_change(compilation):
    if not compilation or "years" not in compilation:
        return compilation
    
    sorted_years = sorted(compilation["years"].keys(), key=lambda x: int(x))
    filtered_years = {}
    prev_pct = None
    
    for yr in sorted_years:
        ydata = compilation["years"][yr]
        pct = 0.0
        for item in ydata.get("summary", []):
            if "(A)" in item.get("category", ""):
                pct = float(item.get("percentage", 0.0))
                break
                
        if prev_pct is not None:
            change = pct - prev_pct
            if abs(change) > 0.0001:
                filtered_years[yr] = ydata
        prev_pct = pct
        
    compilation["years"] = filtered_years
    return compilation

def get_shareholding_pattern(symbol_or_code):
    """
    Main entry point: gets resolved symbol/scrip code, checks cache,
    scrapes all March endings, caches, and returns unified JSON structure.
    """
    scrip_code, company_name = resolve_scrip_code(symbol_or_code)
    
    # Try loading cache first (even if resolve_scrip_code failed, it could be cached by symbol)
    cache_code = scrip_code if scrip_code else str(symbol_or_code).strip().upper()
    cache_path = os.path.join(CACHE_DIR, f"{cache_code}_data.json")
    
    if os.path.exists(cache_path):
        print(f"Found cache at {cache_path}, loading...")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                compilation = json.load(f)
                return filter_years_with_change(compilation)
        except Exception as e:
            print(f"Error reading cache: {e}. Will scrape fresh data.")
            
    if not scrip_code:
        print(f"Could not resolve BSE scrip code for {symbol_or_code}. Trying Screener fallback...")
        res_screener = scrape_screener_shareholding(symbol_or_code)
        if res_screener:
            filtered_annual = filter_years_with_change(res_screener["annual"])
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(filtered_annual, f, indent=2, ensure_ascii=False)
                q_cache_path = os.path.join(CACHE_DIR, f"{cache_code}_quarterly_data.json")
                with open(q_cache_path, "w", encoding="utf-8") as f:
                    json.dump(res_screener["quarterly"], f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Failed to cache Screener results: {e}")
            return filtered_annual
        return {"error": f"Could not resolve BSE symbol/scrip code for: {symbol_or_code}"}
            
    print(f"Scraping fresh shareholding data for {company_name} ({scrip_code})...")
    
    filings = fetch_filings_list(scrip_code)
    if not filings:
        print(f"No shareholding pattern filings found on BSE for scrip code {scrip_code}. Trying Screener fallback...")
        res_screener = scrape_screener_shareholding(symbol_or_code)
        if res_screener:
            filtered_annual = filter_years_with_change(res_screener["annual"])
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(filtered_annual, f, indent=2, ensure_ascii=False)
                q_cache_path = os.path.join(CACHE_DIR, f"{scrip_code}_quarterly_data.json")
                with open(q_cache_path, "w", encoding="utf-8") as f:
                    json.dump(res_screener["quarterly"], f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Failed to cache Screener results: {e}")
            return filtered_annual
        return {"error": f"No shareholding pattern filings found on BSE for scrip code {scrip_code}."}
        
    march_endings = get_march_endings(filings)
    print(f"Identified {len(march_endings)} March endings: {sorted(list(march_endings.keys()))}")
    
    symbol = symbol_or_code.upper()
    if symbol_or_code.isdigit():
        try:
            b = BSE()
            quote = b.getQuote(scrip_code)
            if quote and "securityID" in quote:
                symbol = quote["securityID"].upper()
            else:
                raise ValueError("securityID not in quote")
        except Exception as e:
            print(f"Error resolving symbol using bsedata: {e}")
            res = search_companies(symbol_or_code)
            if res and res[0]["symbol"] and not res[0]["symbol"].isdigit():
                symbol = res[0]["symbol"].upper()
            else:
                symbol = f"BSE_{scrip_code}"
            
    compilation = {
        "scrip_code": scrip_code,
        "company_name": company_name,
        "symbol": symbol,
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "years": {}
    }
    
    # We loop through years and fetch
    for year, filing in sorted(march_endings.items(), reverse=True):
        qtr_id = float(filing.get("qtrid", 0.0))
        qtr_label = filing.get("qtr", f"March {year}")
        nav_url = filing.get("navigateurl", "")
        
        print(f"\nProcessing Year: {year} | Qtr ID: {qtr_id} | Label: {qtr_label}")
        
        if qtr_id >= 88.0:
            # Modern JSON format
            year_data = fetch_modern_data(scrip_code, qtr_id)
        else:
            # Legacy ASPX format
            year_data = scrape_legacy_data(scrip_code, qtr_id, nav_url)
            
        compilation["years"][str(year)] = {
            "qtr_id": qtr_id,
            "qtr_label": qtr_label,
            "summary": year_data["summary"],
            "promoter": year_data["promoter"],
            "public": year_data["public"],
            "non_promoter": year_data["non_promoter"]
        }
        
        # Polite spacing between requests to not hit rate limits
        time.sleep(1.0)
        
    # Filter compilation at the end before saving
    compilation = filter_years_with_change(compilation)
    # Save cache
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(compilation, f, indent=2, ensure_ascii=False)
        print(f"Saved cache to {cache_path}")
    except Exception as e:
        print(f"Failed to save cache: {e}")
        
    return compilation

def get_quarterly_filings(filings):
    """
    Groups filings by (year, quarter_month) to select the latest filing for each quarter.
    """
    quarters = {}
    for f in filings:
        qtr_name = str(f.get("qtr", "")).lower()
        nav_url = str(f.get("navigateurl", "")).lower()
        
        # Try to parse from navigateurl first (e.g., /mar-2026/)
        m = re.search(r'/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)-(\d{4})/', nav_url)
        if m:
            month = m.group(1)
            year = int(m.group(2))
        else:
            # Fallback: parse from qtr field (e.g., "March 2026" or "21 Jul 2025")
            yr_match = re.search(r'\b(20\d{2}|19\d{2})\b', qtr_name)
            if not yr_match:
                continue
            year = int(yr_match.group(1))
            
            month_match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', qtr_name)
            if month_match:
                month = month_match.group(1)
            else:
                continue
                
        # Map month to calendar quarter month: Mar, Jun, Sep, Dec
        if month in ['jan', 'feb', 'mar']:
            qtr_month = 'Mar'
        elif month in ['apr', 'may', 'jun']:
            qtr_month = 'Jun'
        elif month in ['jul', 'aug', 'sep']:
            qtr_month = 'Sep'
        elif month in ['oct', 'nov', 'dec']:
            qtr_month = 'Dec'
        else:
            continue
            
        key = (year, qtr_month)
        qtr_id = float(f.get("qtrid", 0.0))
        
        if key not in quarters or qtr_id > float(quarters[key].get("qtrid", 0.0)):
            quarters[key] = f
            
    return quarters

def get_quarterly_shareholding_pattern(symbol_or_code):
    """
    Scrapes and compiles all available historical quarters since listing.
    Caches the unified JSON structure to cache/{scrip_code}_quarterly_data.json.
    """
    scrip_code, company_name = resolve_scrip_code(symbol_or_code)
    
    # Try loading cache first (even if resolve_scrip_code failed, it could be cached by symbol)
    cache_code = scrip_code if scrip_code else str(symbol_or_code).strip().upper()
    cache_path = os.path.join(CACHE_DIR, f"{cache_code}_quarterly_data.json")
    
    compilation = {"scrip_code": cache_code, "company_name": company_name or f"Company {cache_code}", "symbol": cache_code, "quarters": {}}
    if os.path.exists(cache_path):
        print(f"Found quarterly cache at {cache_path}, loading...")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                compilation = json.load(f)
                # If cached compilation is valid and from Screener (which doesn't have numeric symbol usually), return it
                if not scrip_code or compilation.get("symbol", "").startswith("NSE_") or not compilation.get("symbol", "").isdigit():
                    return compilation
        except Exception as e:
            print(f"Error reading quarterly cache: {e}")

    if not scrip_code:
        print(f"Could not resolve BSE scrip code for {symbol_or_code}. Trying Screener fallback...")
        res_screener = scrape_screener_shareholding(symbol_or_code)
        if res_screener:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(res_screener["quarterly"], f, indent=2, ensure_ascii=False)
                a_cache_path = os.path.join(CACHE_DIR, f"{cache_code}_data.json")
                with open(a_cache_path, "w", encoding="utf-8") as f:
                    json.dump(res_screener["annual"], f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Failed to cache Screener quarterly results: {e}")
            return res_screener["quarterly"]
        return {"error": f"Could not resolve BSE symbol/scrip code for: {symbol_or_code}"}
            
    filings = fetch_filings_list(scrip_code)
    if not filings:
        print(f"No shareholding pattern filings found on BSE for scrip code {scrip_code}. Trying Screener fallback...")
        res_screener = scrape_screener_shareholding(symbol_or_code)
        if res_screener:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(res_screener["quarterly"], f, indent=2, ensure_ascii=False)
                a_cache_path = os.path.join(CACHE_DIR, f"{scrip_code}_data.json")
                with open(a_cache_path, "w", encoding="utf-8") as f:
                    json.dump(res_screener["annual"], f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Failed to cache Screener quarterly results: {e}")
            return res_screener["quarterly"]
        return {"error": f"No shareholding pattern filings found on BSE for scrip code {scrip_code}."}
        
    # Group filings by quarter (latest revision per calendar quarter)
    quarterly_filings = get_quarterly_filings(filings)
    print(f"Identified {len(quarterly_filings)} quarters: {sorted(list(quarterly_filings.keys()))}")
    
    # Get symbol
    if not compilation.get("symbol"):
        symbol = symbol_or_code.upper()
        if symbol_or_code.isdigit():
            try:
                b = BSE()
                quote = b.getQuote(scrip_code)
                if quote and "securityID" in quote:
                    symbol = quote["securityID"].upper()
                else:
                    raise ValueError("securityID not in quote")
            except Exception as e:
                print(f"Error resolving symbol using bsedata: {e}")
                res = search_companies(symbol_or_code)
                if res and res[0]["symbol"] and not res[0]["symbol"].isdigit():
                    symbol = res[0]["symbol"].upper()
                else:
                    symbol = f"BSE_{scrip_code}"
        compilation["symbol"] = symbol

    compilation["scraped_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "quarters" not in compilation:
        compilation["quarters"] = {}
        
    # Loop and fetch each quarter if not already cached
    has_new_scrape = False
    for (year, qtr_month), filing in sorted(quarterly_filings.items(), key=lambda x: (x[0][0], ['Mar', 'Jun', 'Sep', 'Dec'].index(x[0][1])), reverse=True):
        key_str = f"{year}_{qtr_month}"
        
        # Check if already cached
        if key_str in compilation["quarters"]:
            continue
            
        qtr_id = float(filing.get("qtrid", 0.0))
        qtr_label = filing.get("qtr", f"{qtr_month} {year}")
        nav_url = filing.get("navigateurl", "")
        
        print(f"Scraping Quarter: {year} {qtr_month} | Qtr ID: {qtr_id} | Label: {qtr_label}")
        
        if qtr_id >= 88.0:
            year_data = fetch_modern_data(scrip_code, qtr_id)
        else:
            year_data = scrape_legacy_data(scrip_code, qtr_id, nav_url)
            
        compilation["quarters"][key_str] = {
            "year": year,
            "qtr_month": qtr_month,
            "qtr_id": qtr_id,
            "qtr_label": qtr_label,
            "summary": year_data["summary"],
            "promoter": year_data["promoter"],
            "public": year_data["public"],
            "non_promoter": year_data["non_promoter"]
        }
        has_new_scrape = True
        
        # Save cache incrementally
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(compilation, f, indent=2, ensure_ascii=False)
            print(f"Saved incremental quarterly cache to {cache_path}")
        except Exception as e:
            print(f"Failed to save incremental quarterly cache: {e}")
            
        # Polite spacing between requests
        time.sleep(1.0)
        
    return compilation

def clean_percent(val_str):
    val_str = val_str.replace('%', '').replace(',', '').strip()
    if not val_str or val_str == '-' or val_str == '--':
        return 0.0
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def parse_screener_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    company_name = "Company"
    h1 = soup.find('h1')
    if h1:
        company_name = h1.text.strip()
        
    sh_section = soup.find('section', id='shareholding')
    if not sh_section:
        return None
        
    tables = sh_section.find_all('table')
    if not tables:
        return None
        
    quarterly_table = None
    annual_table = None
    
    for table in tables:
        headers = [th.text.strip() for th in table.find_all('th')]
        if not headers or len(headers) < 2:
            continue
        has_non_march = any(any(m in h for m in ['Jun', 'Sep', 'Dec']) for h in headers[1:])
        if has_non_march:
            quarterly_table = table
        else:
            if not annual_table:
                annual_table = table
                
    if not quarterly_table and tables:
        quarterly_table = tables[0]
    if not annual_table and len(tables) > 1:
        annual_table = tables[1]
    elif not annual_table:
        annual_table = quarterly_table
        
    def parse_table_data(table):
        if not table:
            return {}
            
        headers = [th.text.strip() for th in table.find_all('th')]
        if not headers or len(headers) < 2:
            return {}
            
        columns = headers[1:]
        data_rows = {}
        
        for tr in table.find_all('tr'):
            cells = [td.text.strip() for td in tr.find_all(['td', 'th'])]
            if not cells or len(cells) < 2:
                continue
                
            cat_name = re.sub(r'\s+', ' ', cells[0]).replace('+', '').strip()
            if not cat_name or cat_name in columns:
                continue
                
            values = cells[1:]
            data_rows[cat_name] = values
            
        result_by_date = {}
        for idx, date_str in enumerate(columns):
            parts = date_str.split()
            if len(parts) != 2:
                continue
            month_abbr, year_str = parts
            
            promoter_pct = 0.0
            for cat_key, vals in data_rows.items():
                if idx < len(vals):
                    val_str = vals[idx]
                    pct = clean_percent(val_str)
                    if 'promoter' in cat_key.lower():
                        promoter_pct = pct
                        
            public_pct = 100.0 - promoter_pct
            
            result_by_date[date_str] = {
                "year": year_str,
                "qtr_month": month_abbr[:3],
                "promoter": promoter_pct,
                "public": public_pct
            }
            
        return result_by_date

    quarters_data = parse_table_data(quarterly_table)
    years_data = parse_table_data(annual_table)
    
    return {
        "company_name": company_name,
        "quarters": quarters_data,
        "years": years_data
    }

def scrape_screener_shareholding(symbol_or_code):
    symbol = str(symbol_or_code).strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":")[-1].strip()
        
    url = f"https://www.screener.in/company/{symbol}/"
    print(f"Scraping from Screener.in fallback: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"Failed to fetch Screener page for {symbol}. Status code: {r.status_code}")
            return None
            
        html = r.text
        parsed = parse_screener_html(html)
        if not parsed:
            print(f"Failed to parse Screener HTML for {symbol}")
            return None
            
        compilation_quarterly = {
            "scrip_code": symbol,
            "company_name": parsed["company_name"],
            "symbol": symbol,
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "quarters": {}
        }
        
        compilation_annual = {
            "scrip_code": symbol,
            "company_name": parsed["company_name"],
            "symbol": symbol,
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "years": {}
        }
        
        for date_str, qdata in parsed["quarters"].items():
            year = qdata["year"]
            qtr_month = qdata["qtr_month"]
            promoter_pct = qdata["promoter"]
            public_pct = qdata["public"]
            key_str = f"{year}_{qtr_month}"
            
            compilation_quarterly["quarters"][key_str] = {
                "year": year,
                "qtr_month": qtr_month,
                "qtr_id": 0.0,
                "qtr_label": f"{qtr_month} {year}",
                "summary": [
                    {
                        "category": "(A) Promoter & Promoter Group",
                        "shares": 0,
                        "percentage": promoter_pct,
                        "demat_shares": 0,
                        "pledged_shares": 0,
                        "pledged_percentage": 0.0,
                        "no_shareholders": 0
                    },
                    {
                        "category": "(B) Public",
                        "shares": 0,
                        "percentage": public_pct,
                        "demat_shares": 0,
                        "no_shareholders": 0
                    },
                    {
                        "category": "(C) Non Promoter- Non Public",
                        "shares": 0,
                        "percentage": 0.0,
                        "demat_shares": 0,
                        "no_shareholders": 0
                    },
                    {
                        "category": "Grand Total",
                        "shares": 0,
                        "percentage": 100.0,
                        "demat_shares": 0,
                        "no_shareholders": 0
                    }
                ],
                "promoter": [],
                "public": [],
                "non_promoter": []
            }
            
        for date_str, ydata in parsed["years"].items():
            year = ydata["year"]
            promoter_pct = ydata["promoter"]
            public_pct = ydata["public"]
            
            compilation_annual["years"][str(year)] = {
                "qtr_id": 0.0,
                "qtr_label": f"March {year}",
                "summary": [
                    {
                        "category": "(A) Promoter & Promoter Group",
                        "shares": 0,
                        "percentage": promoter_pct,
                        "demat_shares": 0,
                        "pledged_shares": 0,
                        "pledged_percentage": 0.0,
                        "no_shareholders": 0
                    },
                    {
                        "category": "(B) Public",
                        "shares": 0,
                        "percentage": public_pct,
                        "demat_shares": 0,
                        "no_shareholders": 0
                    },
                    {
                        "category": "(C) Non Promoter- Non Public",
                        "shares": 0,
                        "percentage": 0.0,
                        "demat_shares": 0,
                        "no_shareholders": 0
                    },
                    {
                        "category": "Grand Total",
                        "shares": 0,
                        "percentage": 100.0,
                        "demat_shares": 0,
                        "no_shareholders": 0
                    }
                ],
                "promoter": [],
                "public": [],
                "non_promoter": []
            }
            
        return {
            "quarterly": compilation_quarterly,
            "annual": compilation_annual
        }
    except Exception as e:
        print(f"Error scraping Screener fallback for {symbol_or_code}: {e}")
        return None

if __name__ == "__main__":
    # Test run
    res = get_shareholding_pattern("SBIN")
    print(f"Successfully scraped. Keys: {list(res.keys())}")
    print(f"Years compiled: {list(res.get('years', {}).keys())}")
