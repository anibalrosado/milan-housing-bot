"""Regenerate public/map.html from the current sheet data without scraping."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
import yaml
from src.dedupe import DedupeStore
from src.geocoder import Geocoder
from src.map_generator import MapGenerator
from src.sheets import SheetsWriter

with open("config.yaml") as f:
    config = yaml.safe_load(f)

json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
with open(json_path) as f:
    creds = json.load(f)

sheet_id = os.environ["GOOGLE_SHEET_ID"]
dedupe   = DedupeStore()
sheets   = SheetsWriter(sheet_id, creds, config["sheet_columns"])
geocoder = Geocoder(config, dedupe)
gen      = MapGenerator(config, sheets, geocoder, sheet_id)
path     = gen.generate()
print(f"Map written to {path}")
