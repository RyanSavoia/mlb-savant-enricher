from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from playwright.async_api import async_playwright
import json
import os
from urllib.parse import quote
import asyncio

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this for your needs
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

class MLBMatchupScraper:
    def __init__(self):
        self.player_cache = self.load_player_cache()
        
    def load_player_cache(self):
        """Load player ID cache from file if exists"""
        if os.path.exists("player_ids.json"):
            with open("player_ids.json", "r") as f:
                return json.load(f)
        return {}
    
    def save_player_cache(self):
        """Save player ID cache to file"""
        with open("player_ids.json", "w") as f:
            json.dump(self.player_cache, f, indent=2)
    
    def clean_player_name(self, name):
        """Remove handedness markers and clean name"""
        # Remove (R), (L), (S) and position info
        name = name.split("(")[0].strip()
        # Remove numbers and positions from lineup format
        parts = name.split()
        # Filter out numbers and position abbreviations
        clean_parts = [p for p in parts if not p.isdigit() and p not in 
                      ['C', 'P', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']]
        return " ".join(clean_parts)
    
    def get_player_id(self, player_name):
        """Get player ID from cache or API"""
        clean_name = self.clean_player_name(player_name)
        
        # Check cache
        if clean_name in self.player_cache:
            return self.player_cache[clean_name], clean_name
        
        # Try MLB lookup service
        url = f"https://lookup-service-prod.mlb.com/json/named.search_player_all.bam?sport_code='mlb'&active_sw='Y'&name_part='{quote(clean_name)}'"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = data.get("search_player_all", {}).get("queryResults", {})
                if results.get("totalSize") != "0":
                    player = results["row"][0] if isinstance(results.get("row"), list) else results.get("row")
                    if player:
                        player_id = int(player["player_id"])
                        full_name = player["name_display_first_last"]
                        
                        # Cache it
                        self.player_cache[clean_name] = player_id
                        self.save_player_cache()
                        
                        return player_id, full_name
        except Exception as e:
            print(f"Error looking up {clean_name}: {e}")
        
        return None, None
    
    async def scrape_pitcher_arsenal(self, pitcher_name, player_id):
        """Scrape pitcher arsenal from Baseball Savant"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = await browser.new_page()
            
            url = f"https://baseballsavant.mlb.com/savant-player/{pitcher_name.lower().replace(' ', '-')}-{player_id}?stats=statcast-r-pitching-mlb"
            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(5000)
            
            # Scroll to load content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            # Get text
            text = await page.inner_text('body')
            lines = text.split('\n')
            
            # Extract arsenal
            arsenal = []
            for i, line in enumerate(lines):
                if "Statcast Pitch Arsenal" in line:
                    j = i + 1
                    while j < len(lines) and j < i + 20:
                        current = lines[j].strip()
                        if j + 1 < len(lines):
                            next_line = lines[j + 1].strip()
                            if "%" in next_line and "(" in next_line:
                                arsenal.append({
                                    "pitch": current,
                                    "usage": next_line
                                })
                                j += 2
                                continue
                        j += 1
                    break
            
            await browser.close()
            return arsenal
    
    async def scrape_batter_stats(self, batter_name, player_id):
        """Scrape batter stats vs pitch types"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = await browser.new_page()
            
            url = f"https://baseballsavant.mlb.com/savant-player/{batter_name.lower().replace(' ', '-')}-{player_id}?stats=statcast-r-hitting-mlb"
            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(5000)
            
            # Scroll to load content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            # Get all tables
            tables = await page.locator('table').all()
            
            pitch_stats = []
            
            # Look through each table
            for table in tables:
                try:
                    table_text = await table.inner_text()
                    if "Pitch Type" in table_text:
                        # Get all rows
                        rows = await table.locator('tr').all()
                        
                        for row in rows:
                            row_text = await row.inner_text()
                            # Look for 2025 data rows
                            if row_text.strip().startswith("2025"):
                                # Get individual cells
                                cells = await row.locator('td').all()
                                if len(cells) >= 11:
                                    pitch_stat = {
                                        "pitch_type": await cells[1].inner_text(),
                                        "batting_avg": await cells[8].inner_text(),
                                        "slugging": await cells[9].inner_text(), 
                                        "whiff_rate": await cells[11].inner_text() if len(cells) > 11 else "N/A"
                                    }
                                    pitch_stats.append(pitch_stat)
                except:
                    continue
            
            await browser.close()
            return pitch_stats
    
    async def process_game(self, game, max_batters=5):
        """Process a single game's matchup data"""
        result = {
            "game": f"{game['away_team']} @ {game['home_team']}",
            "away_pitcher": {"name": None, "arsenal": []},
            "home_pitcher": {"name": None, "arsenal": []},
            "away_lineup": [],
            "home_lineup": []
        }
        
        # Process pitchers
        away_pitcher = game["away_pitcher"]
        away_id, away_full = self.get_player_id(away_pitcher)
        if away_id:
            arsenal = await self.scrape_pitcher_arsenal(away_full, away_id)
            result["away_pitcher"] = {
                "name": away_full,
                "arsenal": arsenal
            }
        
        home_pitcher = game["home_pitcher"]
        home_id, home_full = self.get_player_id(home_pitcher)
        if home_id:
            arsenal = await self.scrape_pitcher_arsenal(home_full, home_id)
            result["home_pitcher"] = {
                "name": home_full,
                "arsenal": arsenal
            }
        
        # Process batters (limited to max_batters to save time)
        for i, batter_str in enumerate(game["away_lineup"][:max_batters]):
            batter_id, batter_full = self.get_player_id(batter_str)
            if batter_id:
                stats = await self.scrape_batter_stats(batter_full, batter_id)
                result["away_lineup"].append({
                    "order": i + 1,
                    "name": batter_full,
                    "vs_pitches": stats
                })
                await asyncio.sleep(1)  # Be nice to the server
        
        for i, batter_str in enumerate(game["home_lineup"][:max_batters]):
            batter_id, batter_full = self.get_player_id(batter_str)
            if batter_id:
                stats = await self.scrape_batter_stats(batter_full, batter_id)
                result["home_lineup"].append({
                    "order": i + 1,
                    "name": batter_full,
                    "vs_pitches": stats
                })
                await asyncio.sleep(1)  # Be nice to the server
        
        return result

# Initialize scraper
scraper = MLBMatchupScraper()

@app.get("/")
async def get_first_game_analysis():
    """Get pitcher arsenals and batter stats for the first game"""
    try:
        # Get lineups
        response = requests.get("https://mlb-matchup-analysis-api.onrender.com/")
        lineups = response.json()
        
        if not lineups:
            raise HTTPException(status_code=404, detail="No games found")
        
        # Process first game
        game = lineups[0]
        result = await scraper.process_game(game, max_batters=3)  # Only top 3 batters for speed
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/game/{game_index}")
async def get_game_analysis(game_index: int):
    """Get analysis for a specific game by index"""
    try:
        # Get lineups
        response = requests.get("https://mlb-matchup-analysis-api.onrender.com/")
        lineups = response.json()
        
        if game_index >= len(lineups):
            raise HTTPException(status_code=404, detail="Game index out of range")
        
        # Process specified game
        game = lineups[game_index]
        result = await scraper.process_game(game, max_batters=3)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
