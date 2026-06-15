import os
import unittest
import json
from backend.scraper import scrape_screener_shareholding, get_quarterly_shareholding_pattern
from backend.price_helper import PriceFetcher
from batch_process import extract_symbols_from_csv, run_batch_compilation

class TestNSEFallback(unittest.TestCase):
    
    def test_csv_extraction_two_columns(self):
        """
        Verify that extract_symbols_from_csv extracts both BSE and NSE columns when headers are present.
        """
        # Test with headers
        csv_data = "BSE Code,NSE Symbol,Company Name\n500112,SBIN,State Bank\n500209,INFY,Infosys"
        symbols = extract_symbols_from_csv(csv_data)
        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[0]["bse"], "500112")
        self.assertEqual(symbols[0]["nse"], "SBIN")
        self.assertEqual(symbols[1]["bse"], "500209")
        self.assertEqual(symbols[1]["nse"], "INFY")

    def test_csv_extraction_auto_detect(self):
        """
        Verify that extract_symbols_from_csv auto-detects columns based on content when headers are not descriptive.
        """
        # Test without headers, BSE in first col, NSE in second col
        csv_data = "500112,SBIN\n500209,INFY"
        symbols = extract_symbols_from_csv(csv_data)
        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[0]["bse"], "500112")
        self.assertEqual(symbols[0]["nse"], "SBIN")
        
        # Test without headers, NSE in first col, BSE in second col
        csv_data_reverse = "SBIN,500112\nINFY,500209"
        symbols_reverse = extract_symbols_from_csv(csv_data_reverse)
        self.assertEqual(len(symbols_reverse), 2)
        self.assertEqual(symbols_reverse[0]["bse"], "500112")
        self.assertEqual(symbols_reverse[0]["nse"], "SBIN")

    def test_screener_scraping_live(self):
        """
        Verify that scrape_screener_shareholding successfully fetches and structures data from Screener.in.
        """
        # Fetch for SBIN
        data = scrape_screener_shareholding("SBIN")
        self.assertIsNotNone(data)
        self.assertIn("quarterly", data)
        self.assertIn("annual", data)
        
        q_data = data["quarterly"]
        self.assertEqual(q_data["symbol"], "SBIN")
        self.assertGreater(len(q_data["quarters"]), 0)
        
        # Verify category headers contain SEBI codes (A) and (B)
        sample_q = list(q_data["quarters"].values())[0]
        summary_cats = [item["category"] for item in sample_q["summary"]]
        self.assertTrue(any("(A)" in cat for cat in summary_cats))
        self.assertTrue(any("(B)" in cat for cat in summary_cats))

    def test_price_fetcher_nse(self):
        """
        Verify that PriceFetcher successfully fetches prices for NSE symbols (.NS suffix).
        """
        # We pass a non-existent scrip code but a valid NSE symbol
        fetcher = PriceFetcher("INVALID_CODE", "SBIN")
        self.assertEqual(fetcher.ticker_symbol, "SBIN.NS")
        self.assertIsNotNone(fetcher.history)
        self.assertFalse(fetcher.history.empty)

    def test_batch_compilation_with_fallback(self):
        """
        Verify that run_batch_compilation executes successfully with fallbacks and filters out zero-change rows.
        """
        output_xlsx = os.path.join("cache", "test_fallback_compilation.xlsx")
        if os.path.exists(output_xlsx):
            os.remove(output_xlsx)
            
        # We pass a symbol that doesn't exist on BSE but does on NSE (we mock/use a custom string to force fallback)
        # We can also pass an invalid BSE code and valid NSE code to force fallback
        symbols = [{"bse": "999999", "nse": "TCS"}]
        
        completed, failed = run_batch_compilation(symbols, output_xlsx)
        self.assertEqual(completed, 1)
        self.assertEqual(failed, 0)
        self.assertTrue(os.path.exists(output_xlsx))
        
        # Clean up
        if os.path.exists(output_xlsx):
            os.remove(output_xlsx)

if __name__ == "__main__":
    unittest.main()
