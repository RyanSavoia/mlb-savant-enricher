from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import asyncio
import httpx
from typing import Dict, List, Optional

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.thebettinginsider.com"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Your lineup API URL
LINEUP_API_URL = "https://mlb-matchup-analysis-api.onrender.com/"

async def get_lineups():
    """Fetch lineups from your existing API"""
    async with httpx.AsyncClient() as client:
        response = await client.get(LINEUP_API_URL, timeout=30.0)
        return response.json()

async def get_pitcher_arsenal(pitcher_name: str):
    """Get pitcher's arsenal from Baseball Savant"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = await browser.new_page()
        
        try:
            # Search for pitcher and navigate to their page
            url_name = pitcher_name.lower().replace(' ', '-')
            await page.goto(f"https://baseballsavant.mlb.com/savant-player/{url_name}", timeout=30000)
            
            # If 404, search for the player
            if page.url.includes('404'):
                await page.goto("https://baseballsavant.mlb.com/", timeout=30000)
                await page.type('input[type="text"]', pitcher_name)
                await page.wait_for_timeout(2000)
                await page.click('.ui-menu-item a:first-child')
                await page.wait_for_timeout(3000)
            
            # Navigate to pitching stats
            if '?stats=' not in page.url:
                await page.goto(page.url + '?stats=statcast-r-pitching-mlb', timeout=30000)
            
            await page.wait_for_timeout(3000)
            
            # Extract arsenal data from the movement profile section
            arsenal = await page.evaluate('''
                () => {
                    const pitches = [];
                    // Look for the usage table
                    const tables = document.querySelectorAll('table');
                    
                    for (const table of tables) {
                        const headers = Array.from(table.querySelectorAll('th')).map(th => th.textContent.trim());
                        
                        // Find the usage table
                        if (headers.some(h => h.toLowerCase().includes('usage'))) {
                            const rows = table.querySelectorAll('tbody tr');
                            
                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 3) {
                                    pitches.push({
                                        pitch_type: cells[0].textContent.trim(),
                                        usage: cells[1].textContent.trim(),
                                        velocity: cells[2].textContent.trim()
                                    });
                                }
                            });
                            break;
                        }
                    }
                    
                    return pitches;
                }
            ''')
            
            await browser.close()
            return arsenal
            
        except Exception as e:
            await browser.close()
            return []

async def get_batter_vs_pitches(batter_name: str):
    """Get batter's performance against pitch types from Baseball Savant"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = await browser.new_page()
        
        try:
            # Search for batter and navigate to their page
            url_name = batter_name.lower().replace(' ', '-')
            await page.goto(f"https://baseballsavant.mlb.com/savant-player/{url_name}", timeout=30000)
            
            # If 404, search for the player
            if page.url.includes('404'):
                await page.goto("https://baseballsavant.mlb.com/", timeout=30000)
                await page.type('input[type="text"]', batter_name)
                await page.wait_for_timeout(2000)
                await page.click('.ui-menu-item a:first-child')
                await page.wait_for_timeout(3000)
            
            # Navigate to hitting stats
            if '?stats=' not in page.url:
                await page.goto(page.url + '?stats=statcast-r-hitting-mlb', timeout=30000)
            
            await page.wait_for_timeout(3000)
            
            # Scroll to Run Values by Pitch Type section
            await page.evaluate('''
                () => {
                    const headers = Array.from(document.querySelectorAll('h2, h3, h4'));
                    const rvHeader = headers.find(h => h.textContent.includes('Run Values by Pitch Type'));
                    if (rvHeader) {
                        rvHeader.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                }
            ''')
            
            await page.wait_for_timeout(2000)
            
            # Extract pitch type performance
            pitch_stats = await page.evaluate('''
                () => {
                    const stats = {};
                    const tables = document.querySelectorAll('table');
                    
                    for (const table of tables) {
                        // Look for the Run Values table
                        const prevElement = table.previousElementSibling;
                        if (prevElement && prevElement.textContent.includes('Run Values by Pitch Type')) {
                            const rows = table.querySelectorAll('tbody tr');
                            
                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length > 10) {
                                    const pitchType = cells[1].textContent.trim();
                                    stats[pitchType] = {
                                        pitches: cells[5].textContent.trim(),
                                        pa: cells[7].textContent.trim(),
                                        ba: cells[8].textContent.trim(),
                                        slg: cells[9].textContent.trim(),
                                        woba: cells[10].textContent.trim(),
                                        whiff_pct: cells[11].textContent.trim(),
                                        k_pct: cells[12].textContent.trim()
                                    };
                                }
                            });
                            break;
                        }
                    }
                    
                    return stats;
                }
            ''')
            
            await browser.close()
            return pitch_stats
            
        except Exception as e:
            await browser.close()
            return {}

async def analyze_matchup(game: dict):
    """Analyze a single game matchup"""
    matchup_data = {
        "teams": {
            "away": game["away_team"],
            "home": game["home_team"]
        },
        "pitchers": {
            "away": {
                "name": game["away_pitcher"],
                "arsenal": []
            },
            "home": {
                "name": game["home_pitcher"],
                "arsenal": []
            }
        },
        "matchups": {
            "away_batters_vs_home_pitcher": [],
            "home_batters_vs_away_pitcher": []
        }
    }
    
    # Get pitcher arsenals (just the names, strip handedness)
    away_pitcher_name = game["away_pitcher"].replace("(R)", "").replace("(L)", "").strip()
    home_pitcher_name = game["home_pitcher"].replace("(R)", "").replace("(L)", "").strip()
    
    matchup_data["pitchers"]["away"]["arsenal"] = await get_pitcher_arsenal(away_pitcher_name)
    matchup_data["pitchers"]["home"]["arsenal"] = await get_pitcher_arsenal(home_pitcher_name)
    
    # Analyze key batters (top 3) vs opposing pitcher
    for i in range(min(3, len(game["away_lineup"]))):
        batter_line = game["away_lineup"][i]
        # Extract batter name (e.g., "1   J.P. Crawford (L) SS" -> "J.P. Crawford")
        parts = batter_line.split()
        name_parts = []
        for part in parts[1:]:
            if '(' in part:
                break
            name_parts.append(part)
        batter_name = ' '.join(name_parts)
        
        batter_stats = await get_batter_vs_pitches(batter_name)
        
        # Match with pitcher's arsenal
        vs_pitcher = []
        for pitch in matchup_data["pitchers"]["home"]["arsenal"]:
            pitch_type = pitch["pitch_type"]
            if pitch_type in batter_stats:
                vs_pitcher.append({
                    "pitch_type": pitch_type,
                    "pitcher_usage": pitch["usage"],
                    "batter_stats": batter_stats[pitch_type]
                })
        
        matchup_data["matchups"]["away_batters_vs_home_pitcher"].append({
            "batter": batter_name,
            "order": i + 1,
            "vs_pitcher": vs_pitcher
        })
        
        await asyncio.sleep(1)  # Rate limiting
    
    # Do the same for home batters vs away pitcher
    for i in range(min(3, len(game["home_lineup"]))):
        batter_line = game["home_lineup"][i]
        # Extract batter name (e.g., "LF (S) Ian Happ   1" -> "Ian Happ")
        parts = batter_line.split()
        name_parts = []
        start_name = False
        for part in parts:
            if ')' in part:
                start_name = True
                continue
            if start_name and not part.isdigit():
                name_parts.append(part)
        batter_name = ' '.join(name_parts)
        
        batter_stats = await get_batter_vs_pitches(batter_name)
        
        # Match with pitcher's arsenal
        vs_pitcher = []
        for pitch in matchup_data["pitchers"]["away"]["arsenal"]:
            pitch_type = pitch["pitch_type"]
            if pitch_type in batter_stats:
                vs_pitcher.append({
                    "pitch_type": pitch_type,
                    "pitcher_usage": pitch["usage"],
                    "batter_stats": batter_stats[pitch_type]
                })
        
        matchup_data["matchups"]["home_batters_vs_away_pitcher"].append({
            "batter": batter_name,
            "order": i + 1,
            "vs_pitcher": vs_pitcher
        })
        
        await asyncio.sleep(1)  # Rate limiting
    
    return matchup_data

@app.get("/")
async def get_all_matchups():
    """Get all matchups with Savant data"""
    # Get lineups from your API
    lineup_data = await get_lineups()
    
    # Analyze each game
    analyzed_games = []
    for game in lineup_data[:2]:  # Start with just first 2 games for testing
        analysis = await analyze_matchup(game)
        analyzed_games.append(analysis)
    
    return analyzed_games

@app.get("/matchup/{away_team}/{home_team}")
async def get_single_matchup(away_team: str, home_team: str):
    """Get a specific matchup analysis"""
    # Get lineups from your API
    lineup_data = await get_lineups()
    
    # Find the specific game
    game = None
    for g in lineup_data:
        if g["away_team"].upper() == away_team.upper() and g["home_team"].upper() == home_team.upper():
            game = g
            break
    
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Analyze the matchup
    analysis = await analyze_matchup(game)
    return analysis

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
