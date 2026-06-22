import os
import sys
import uuid
import shutil
import zipfile

# Add current directory to path to allow importing local modules on hosting environments
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.scraper import search_companies, get_shareholding_pattern, resolve_scrip_code
from backend.excel_generator import create_excel_workbook
from batch_process import extract_symbols_from_csv, run_batch_compilation

app = FastAPI(
    title="BSE India Shareholding Pattern Compiler",
    description="APIs to search BSE listed companies, fetch historical annual shareholding, and compile to Excel.",
    version="1.0.0"
)

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory configs
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    CACHE_DIR = "/tmp/cache"
else:
    CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)
STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)

BATCH_JOBS_DIR = os.path.join(CACHE_DIR, "batch_jobs")
os.makedirs(BATCH_JOBS_DIR, exist_ok=True)

batch_jobs = {}

@app.get("/api/search")
def api_search(symbol: str = Query(..., description="The symbol or name to search on BSE")):
    """
    Searches for listed companies on BSE.
    """
    results = search_companies(symbol)
    return results

@app.get("/api/shareholding")
def api_shareholding(scripcode: str = Query(..., description="The 6-digit BSE scrip code")):
    """
    Retrieves the complete historical shareholding pattern.
    Uses cached data if available, otherwise initiates a fresh scrape.
    """
    if not (scripcode.isdigit() and len(scripcode) == 6):
        # Try to resolve if it is a symbol
        code, name = resolve_scrip_code(scripcode)
        if not code:
            raise HTTPException(status_code=400, detail="Invalid scrip code or symbol format.")
        scripcode = code
        
    data = get_shareholding_pattern(scripcode)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data

@app.get("/api/download")
def api_download(scripcode: str = Query(..., description="The 6-digit BSE scrip code or symbol")):
    """
    Generates and downloads the consolidated quarterly performance Excel compilation.
    """
    import json
    # Resolve symbol if code is not 6 digits
    if not (scripcode.isdigit() and len(scripcode) == 6):
        code, name = resolve_scrip_code(scripcode)
        if not code:
            raise HTTPException(status_code=400, detail="Invalid scrip code or symbol format.")
        scripcode = code
        
    excel_filename = f"{scripcode}_quarterly_performance.xlsx"
    excel_path = os.path.join(CACHE_DIR, excel_filename)
    
    try:
        # Generate the Excel sheet using the quarterly compiler
        completed, failed = run_batch_compilation([scripcode], excel_path)
        if completed == 0:
            raise HTTPException(status_code=404, detail="No quarterly data was successfully compiled.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Excel sheet: {e}")
        
    if not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail="Generated Excel file not found.")
        
    # Get clean download name from cached quarterly pattern
    company_name = "company"
    try:
        cache_json = os.path.join(CACHE_DIR, f"{scripcode}_quarterly_data.json")
        if os.path.exists(cache_json):
            with open(cache_json, "r", encoding="utf-8") as f:
                q_data = json.load(f)
                company_name = q_data.get("company_name", "company")
    except Exception as ce:
        print(f"Error reading name from cache: {ce}")
        
    clean_company_name = "".join(x for x in company_name if x.isalnum() or x in " -_").strip()
    download_filename = f"{clean_company_name}_Quarterly_Performance_Compiled.xlsx"
    
    return FileResponse(
        path=excel_path,
        filename=download_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

def process_batch_job(job_id: str, symbols: list, output_xlsx_path: str):
    batch_jobs[job_id]["status"] = "processing"
    
    def progress_callback(sym, idx, total, completed_count, failed_count, status_str, error_msg=None):
        sym_name = sym
        if isinstance(sym, dict):
            sym_name = sym.get("nse") or sym.get("bse") or ""
        batch_jobs[job_id]["current_symbol"] = sym_name
        batch_jobs[job_id]["completed"] = completed_count
        batch_jobs[job_id]["failed"] = failed_count
        if status_str == "failed":
            batch_jobs[job_id]["errors"].append({
                "symbol": sym_name,
                "error": error_msg or "Unknown error occurred"
            })

    try:
        completed, failed = run_batch_compilation(symbols, output_xlsx_path, progress_callback)
        if completed > 0:
            batch_jobs[job_id]["status"] = "completed"
        else:
            batch_jobs[job_id]["status"] = "failed"
            batch_jobs[job_id]["error"] = "No company shareholding data was successfully compiled."
    except Exception as e:
        batch_jobs[job_id]["status"] = "failed"
        batch_jobs[job_id]["error"] = str(e)

@app.post("/api/batch")
async def api_batch_upload(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    save_path: str = Form(None)
):
    """
    Uploads a CSV file with stock symbols or scrip codes, parses it,
    and starts a background compilation task.
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")
        
    try:
        content = await file.read()
        csv_text = content.decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read CSV file: {e}")
        
    symbols = extract_symbols_from_csv(csv_text)
    if not symbols:
        raise HTTPException(status_code=400, detail="No valid symbols or scrip codes found in CSV.")
        
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(BATCH_JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    # Custom Save Path Validation
    xlsx_path = None
    if save_path:
        save_path = save_path.strip()
        if not save_path.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Save path must end with .xlsx")
        
        # Verify parent directory is writeable/creatable
        dir_name = os.path.dirname(save_path)
        if dir_name:
            try:
                os.makedirs(dir_name, exist_ok=True)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid or unwritable save path directory: {e}")
        xlsx_path = save_path
    else:
        xlsx_path = os.path.join(job_dir, "compiled_quarterly_shareholding_performance.xlsx")
    
    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "total": len(symbols),
        "completed": 0,
        "failed": 0,
        "current_symbol": "",
        "zip_path": xlsx_path,  # Keep the dict key as zip_path or change to xlsx_path to prevent UI breakout
        "error": None,
        "errors": []
    }
    
    background_tasks.add_task(process_batch_job, job_id, symbols, xlsx_path)
    
    return {"job_id": job_id, "total": len(symbols)}

@app.get("/api/batch/status")
async def api_batch_status(job_id: str = Query(..., description="The unique batch job ID")):
    """
    Returns progress information for a batch job.
    """
    if job_id not in batch_jobs:
        raise HTTPException(status_code=404, detail="Batch job not found.")
        
    job = batch_jobs[job_id]
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "failed": job["failed"],
        "current_symbol": job["current_symbol"],
        "error": job["error"],
        "errors": job.get("errors", [])
    }

@app.get("/api/batch/download")
async def api_batch_download(job_id: str = Query(..., description="The unique batch job ID")):
    """
    Downloads the completed Excel spreadsheet containing compiled quarterly holdings and stock price performance.
    """
    if job_id not in batch_jobs:
        raise HTTPException(status_code=404, detail="Batch job not found.")
        
    job = batch_jobs[job_id]
    if job["status"] == "pending":
        raise HTTPException(status_code=400, detail="Job has not started processing yet.")
        
    xlsx_path = job["zip_path"]  # stored in the zip_path field
    if not os.path.exists(xlsx_path):
        raise HTTPException(status_code=404, detail="Excel file not found on server.")
        
    return FileResponse(
        path=xlsx_path,
        filename="compiled_quarterly_shareholding_performance.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/api/fetch-prices")
def api_fetch_prices(
    symbol: str = Query(None),
    company_name: str = Query(None)
):
    from backend.price_helper import PriceFetcher
    if not symbol and not company_name:
        raise HTTPException(status_code=400, detail="Either symbol or company_name is required.")
    
    fetcher = PriceFetcher(scrip_code=symbol, symbol=symbol, company_name=company_name)
    if fetcher.history is None or fetcher.history.empty:
        raise HTTPException(status_code=404, detail="No historical price data found.")
    
    history_dict = {}
    for date_val, row in fetcher.history.iterrows():
        date_str = date_val.strftime("%Y-%m-%d")
        history_dict[date_str] = float(row["Close"])
        
    return {
        "ticker": fetcher.ticker_symbol,
        "history": history_dict
    }

# Mount static files to serve frontend
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8003))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("main:app", host=host, port=port, reload=False)
