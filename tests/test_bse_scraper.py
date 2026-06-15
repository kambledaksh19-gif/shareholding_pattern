import os
import unittest
import json
from backend.scraper import resolve_scrip_code, search_companies, get_shareholding_pattern
from backend.excel_generator import create_excel_workbook

class TestBSEScraper(unittest.TestCase):
    
    def test_search_companies(self):
        """
        Verify that searching for SBIN returns State Bank of India details.
        """
        results = search_companies("SBIN")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        # Verify first item contains SBIN
        self.assertEqual(results[0]["symbol"].upper(), "SBIN")
        self.assertEqual(results[0]["scrip_code"], "500112")
        
    def test_resolve_scrip_code(self):
        """
        Verify that symbol SBIN resolves to 500112.
        """
        code, name = resolve_scrip_code("SBIN")
        self.assertEqual(code, "500112")
        self.assertIn("STATE BANK OF INDIA", name.upper())
        
    def test_get_shareholding_pattern(self):
        """
        Verify that fetching shareholding returns a valid dictionary structure and writes cache.
        """
        scrip_code = "500112"
        data = get_shareholding_pattern(scrip_code)
        
        self.assertNotIn("error", data)
        self.assertEqual(data["scrip_code"], scrip_code)
        self.assertEqual(data["symbol"], "SBIN")
        self.assertIn("years", data)
        self.assertGreater(len(data["years"]), 0)
        
        # Verify cache file exists
        cache_path = os.path.join("cache", f"{scrip_code}_data.json")
        self.assertTrue(os.path.exists(cache_path))
        
    def test_excel_generation(self):
        """
        Verify that compiling the Excel workbook creates the spreadsheet file.
        """
        scrip_code = "500112"
        cache_path = os.path.join("cache", f"{scrip_code}_data.json")
        
        # Ensure cache exists
        self.assertTrue(os.path.exists(cache_path))
        
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        output_xlsx = os.path.join("cache", "test_output_verification.xlsx")
        # Remove if exists
        if os.path.exists(output_xlsx):
            os.remove(output_xlsx)
            
        create_excel_workbook(data, output_xlsx)
        self.assertTrue(os.path.exists(output_xlsx))

    def test_csv_parsing(self):
        """
        Verify that extract_symbols_from_csv handles headers and extracts symbols.
        """
        from batch_process import extract_symbols_from_csv
        
        # Test CSV with "symbol" header
        csv_data = "Symbol,Company Name\nSBIN,State Bank\nTCS,Tata Consultancy Services\nINFY,Infosys"
        symbols = extract_symbols_from_csv(csv_data)
        self.assertEqual(symbols, [
            {"bse": "State Bank", "nse": "SBIN"},
            {"bse": "Tata Consultancy Services", "nse": "TCS"},
            {"bse": "Infosys", "nse": "INFY"}
        ])
        
        # Test CSV without headers (should take first column)
        csv_data_no_header = "500112\n500209\n500325"
        symbols_no_header = extract_symbols_from_csv(csv_data_no_header)
        self.assertEqual(symbols_no_header, [
            {"bse": "500112", "nse": "500112"},
            {"bse": "500209", "nse": "500209"},
            {"bse": "500325", "nse": "500325"}
        ])

    def test_run_batch_compilation(self):
        """
        Verify that run_batch_compilation compiles symbols and writes a consolidated Excel workbook.
        """
        from batch_process import run_batch_compilation
        
        symbols = ["500112"]
        output_xlsx = os.path.join("cache", "test_batch_output.xlsx")
        
        if os.path.exists(output_xlsx):
            os.remove(output_xlsx)
            
        completed, failed = run_batch_compilation(symbols, output_xlsx)
        self.assertEqual(completed, 1)
        self.assertEqual(failed, 0)
        self.assertTrue(os.path.exists(output_xlsx))
        
        # Clean up
        if os.path.exists(output_xlsx):
            os.remove(output_xlsx)

    def test_price_fetcher(self):
        """
        Verify that PriceFetcher downloads price history and matches closest date close prices.
        """
        from backend.price_helper import PriceFetcher
        
        fetcher = PriceFetcher("500112", "SBIN")
        self.assertIsNotNone(fetcher.history)
        
        # Test fetching close price on a weekday
        price = fetcher.get_price_on_date("2023-09-29")
        self.assertIsNotNone(price)
        self.assertGreater(price, 0.0)
        
        # Test fetching on a future date (should return None)
        future_price = fetcher.get_price_on_date("2030-01-01")
        self.assertIsNone(future_price)

if __name__ == "__main__":
    unittest.main()
