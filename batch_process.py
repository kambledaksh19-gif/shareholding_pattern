import os
import csv
import io
import sys
import time
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime

# Add current directory to path to allow importing backend modules
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from backend.scraper import get_quarterly_shareholding_pattern
from backend.price_helper import PriceFetcher, get_quarter_end_date, add_months

def extract_symbols_from_csv(csv_content_or_path):
    """
    Parses CSV and returns a list of symbols/scrip codes.
    Checks headers for common names or defaults to first column.
    """
    symbols = []
    rows = []
    
    try:
        if os.path.exists(csv_content_or_path):
            with open(csv_content_or_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = list(reader)
        else:
            # Treat as raw CSV string content
            f = io.StringIO(csv_content_or_path)
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as e:
        print(f"Error reading CSV content: {e}")
        return []
        
    if not rows:
        return []
        
    # Clean rows of empty rows
    rows = [r for r in rows if r and any(cell.strip() for cell in r)]
    if not rows:
        return []
        
    # Find header row and target column index
    header = [str(x).strip().lower() for x in rows[0]]
    col_idx = 0
    
    # Common names for symbol/scrip code columns
    target_names = ["symbol", "ticker", "scripcode", "scrip code", "code", "scrip_code", "company symbol", "company code"]
    for idx, col in enumerate(header):
        if any(name in col for name in target_names):
            col_idx = idx
            break
            
    has_header = any(name in header[col_idx] for name in target_names) or not (header[col_idx].isdigit() or (header[col_idx].isupper() and len(header[col_idx]) <= 10))
    # If header contains one of target names or isn't a digit/ticker code, skip first row
    start_row = 1 if has_header else 0
    
    for r in rows[start_row:]:
        if len(r) > col_idx:
            val = str(r[col_idx]).strip()
            if val:
                symbols.append(val)
                
    # Deduplicate symbols keeping order
    seen = set()
    deduped = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
            
    return deduped

def run_batch_compilation(symbols, output_xlsx_path, progress_callback=None):
    """
    Scrapes quarterly holdings, fetches stock prices, calculates changes, 
    and writes a consolidated Excel file.
    """
    total = len(symbols)
    completed = 0
    failed = 0
    
    # Store all compiled rows across all companies
    all_data_rows = []
    
    for idx, sym in enumerate(symbols, 1):
        print(f"[{idx}/{total}] Processing {sym}...")
        if progress_callback:
            progress_callback(sym, idx, total, completed, failed, "processing")
            
        try:
            # 1. Fetch quarterly data
            data = get_quarterly_shareholding_pattern(sym)
            if "error" in data:
                print(f"Error scraping {sym}: {data['error']}")
                failed += 1
                if progress_callback:
                    progress_callback(sym, idx, total, completed, failed, "failed")
                continue
                
            company_name = data.get("company_name", sym)
            scrip_code = data.get("scrip_code", sym)
            symbol_ticker = data.get("symbol", "")
            
            # 2. Sort quarters chronologically
            quarters_dict = data.get("quarters", {})
            if not quarters_dict:
                print(f"No quarterly data found for {sym}.")
                failed += 1
                if progress_callback:
                    progress_callback(sym, idx, total, completed, failed, "failed")
                continue
                
            # Helper to parse year/month for sorting
            months_order = ['Mar', 'Jun', 'Sep', 'Dec']
            quarters_sorted = sorted(
                quarters_dict.items(),
                key=lambda x: (int(x[1]["year"]), months_order.index(x[1]["qtr_month"]))
            )
            
            # 3. Instantiate PriceFetcher
            print(f"Fetching historical prices for {company_name} ({scrip_code})...")
            price_fetcher = PriceFetcher(scrip_code, symbol_ticker)
            
            # Helper to get promoter holding percentage
            def get_promoter_pct(qtr_data):
                for item in qtr_data.get("summary", []):
                    if "(A)" in item.get("category", ""):
                        return float(item.get("percentage", 0.0))
                return 0.0
            
            # 4. Calculate quarterly change and match prices
            company_rows = []
            for t, (qtr_key, qtr_data) in enumerate(quarters_sorted):
                year = qtr_data["year"]
                qtr_month = qtr_data["qtr_month"]
                promoter_pct = get_promoter_pct(qtr_data)
                
                # Calculate change from previous quarter
                if t == 0:
                    change = 0.0
                else:
                    prev_qtr_data = quarters_sorted[t-1][1]
                    prev_promoter_pct = get_promoter_pct(prev_qtr_data)
                    change = promoter_pct - prev_promoter_pct
                    
                # Format change percentage string
                change_str = f"+{change:.2f}%" if change > 0 else (f"{change:.2f}%" if change < 0 else "0.00%")
                
                # Date calculation
                quarter_end_date = get_quarter_end_date(year, qtr_month)
                cmp_price = None
                cmp_18 = None
                cmp_24 = None
                
                if quarter_end_date:
                    date_obj = datetime.strptime(quarter_end_date, "%Y-%m-%d")
                    # base date is quarter end date + 1 month (CMP after one month)
                    base_date_obj = add_months(date_obj, 1)
                    base_date_str = base_date_obj.strftime("%Y-%m-%d")
                    cmp_price = price_fetcher.get_price_on_date(base_date_str)
                    
                    # 18 months date starting from CMP after one month
                    date_18_str = add_months(base_date_obj, 18).strftime("%Y-%m-%d")
                    cmp_18 = price_fetcher.get_price_on_date(date_18_str)
                    
                    # 24 months date starting from CMP after one month
                    date_24_str = add_months(base_date_obj, 24).strftime("%Y-%m-%d")
                    cmp_24 = price_fetcher.get_price_on_date(date_24_str)
                
                # Append row
                company_rows.append({
                    "company_name": company_name,
                    "change": change,
                    "change_str": change_str,
                    "quarter": f"{qtr_month}-{year}",
                    "cmp": cmp_price,
                    "cmp_18": cmp_18,
                    "cmp_24": cmp_24,
                    # For sorting all rows at the end if desired (oldest first)
                    "sort_key": (int(year), months_order.index(qtr_month))
                })
                
            all_data_rows.extend(company_rows)
            completed += 1
            if progress_callback:
                progress_callback(sym, idx, total, completed, failed, "success")
        except Exception as e:
            print(f"Exception processing {sym}: {e}")
            failed += 1
            if progress_callback:
                progress_callback(sym, idx, total, completed, failed, "failed")
                
        # Polite spacing between stocks in batch
        if idx < total:
            time.sleep(1.0)
            
    # 5. Write to consolidated Excel sheet
    if completed > 0:
        os.makedirs(os.path.dirname(output_xlsx_path), exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Shareholding Performance"
        
        # Gridlines visible
        ws.views.sheetView[0].showGridLines = True
        
        # Define styles
        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_body = Font(name="Calibri", size=11, bold=False)
        fill_header = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        
        align_left = Alignment(horizontal="left", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")
        align_center = Alignment(horizontal="center", vertical="center")
        
        border_side = Side(style='thin', color='D9D9D9')
        border_cell = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)
        
        # Write headers
        headers = [
            "company name",
            "change in promoter holding",
            "change in which quarter",
            "CMP after one month",
            "CMP after 18 months",
            "Returns(Between CMP after one month and CMP after 18 months)",
            "CMP after 24 months",
            "Returns(Between CMP after one month and CMP after 24 months)"
        ]
        
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center if col_idx == 3 else (align_left if col_idx == 1 else align_right)
            cell.border = border_cell
            
        # Write data rows
        # Sort rows: Company Name alphabetical, then quarter chronological
        all_data_rows_sorted = sorted(
            all_data_rows,
            key=lambda x: (x["company_name"].lower(), x["sort_key"][0], x["sort_key"][1])
        )
        
        for row_idx, data_row in enumerate(all_data_rows_sorted, 2):
            # Company name
            c1 = ws.cell(row=row_idx, column=1, value=data_row["company_name"])
            c1.font = font_body
            c1.alignment = align_left
            c1.border = border_cell
            
            # Change in promoter holding
            change = data_row["change"]
            c2 = ws.cell(row=row_idx, column=2, value=change / 100.0)
            c2.font = font_body
            c2.alignment = align_right
            c2.border = border_cell
            c2.number_format = '+0.00%;-0.00%;0.00%'
            # Color code change text color (green for increase, red for decrease)
            if change > 0.001:
                c2.font = Font(name="Calibri", size=11, bold=False, color="385723") # Dark Green
            elif change < -0.001:
                c2.font = Font(name="Calibri", size=11, bold=False, color="C00000") # Dark Red
                
            # Change Quarter
            c3 = ws.cell(row=row_idx, column=3, value=data_row["quarter"])
            c3.font = font_body
            c3.alignment = align_center
            c3.border = border_cell
            
            # Column 4: CMP after one month
            val_cmp = data_row["cmp"]
            c4 = ws.cell(row=row_idx, column=4)
            if val_cmp is not None:
                c4.value = float(val_cmp)
                c4.number_format = '0.00'
                c4.font = font_body
            else:
                c4.value = "N/A"
                c4.font = Font(name="Calibri", size=11, italic=True, color="7F7F7F")
            c4.alignment = align_right
            c4.border = border_cell
            
            # Column 5: CMP after 18 months
            val_18 = data_row["cmp_18"]
            c5 = ws.cell(row=row_idx, column=5)
            if val_18 is not None:
                c5.value = float(val_18)
                c5.number_format = '0.00'
                c5.font = font_body
            else:
                c5.value = "N/A"
                c5.font = Font(name="Calibri", size=11, italic=True, color="7F7F7F")
            c5.alignment = align_right
            c5.border = border_cell
            
            # Column 6: Returns (Between CMP after one month and CMP after 18 months)
            c6 = ws.cell(row=row_idx, column=6)
            c6.value = f'=IF(AND(ISNUMBER(D{row_idx}), ISNUMBER(E{row_idx})), (E{row_idx}-D{row_idx})/D{row_idx}, "N/A")'
            c6.number_format = '+0.00%;-0.00%;0.00%'
            c6.font = font_body
            c6.alignment = align_right
            c6.border = border_cell
            
            # Column 7: CMP after 24 months
            val_24 = data_row["cmp_24"]
            c7 = ws.cell(row=row_idx, column=7)
            if val_24 is not None:
                c7.value = float(val_24)
                c7.number_format = '0.00'
                c7.font = font_body
            else:
                c7.value = "N/A"
                c7.font = Font(name="Calibri", size=11, italic=True, color="7F7F7F")
            c7.alignment = align_right
            c7.border = border_cell
            
            # Column 8: Returns (Between CMP after one month and CMP after 24 months)
            c8 = ws.cell(row=row_idx, column=8)
            c8.value = f'=IF(AND(ISNUMBER(D{row_idx}), ISNUMBER(G{row_idx})), (G{row_idx}-D{row_idx})/D{row_idx}, "N/A")'
            c8.number_format = '+0.00%;-0.00%;0.00%'
            c8.font = font_body
            c8.alignment = align_right
            c8.border = border_cell
            
        # Auto-size columns
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                # Ignore formula strings for column sizing
                if val.startswith("="):
                    continue
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
        wb.save(output_xlsx_path)
        print(f"Batch quarterly performance compilation finished. Created Excel file at: {output_xlsx_path}")
    else:
        print("No sheets successfully compiled. Excel file not created.")
        
    return completed, failed

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python batch_process.py <csv_file_path> [output_xlsx_path]")
        sys.exit(1)
        
    csv_path = sys.argv[1]
    xlsx_path = sys.argv[2] if len(sys.argv) > 2 else "compiled_quarterly_shareholding_performance.xlsx"
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)
        
    print(f"Parsing CSV: {csv_path}...")
    symbols = extract_symbols_from_csv(csv_path)
    print(f"Found {len(symbols)} unique symbols/codes: {symbols}")
    
    if not symbols:
        print("No symbols found in CSV.")
        sys.exit(1)
        
    completed, failed = run_batch_compilation(symbols, xlsx_path)
    print(f"\nSummary: Successfully compiled {completed}/{len(symbols)} stocks. Failed: {failed}.")
