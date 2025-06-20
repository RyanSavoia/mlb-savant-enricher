from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import asyncio
import httpx

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

async def get_savant_data_for_game(away_team: str, home_team: str):
    """Get pitcher and batter data from Baseball Savant for a specific game"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = await browser.new_page()
        
        try:
            # Go to Baseball Savant main page
            await page.goto("https://baseballsavant.mlb.com/", timeout=30000)
            await page.wait_for_timeout(3000)
            
            # Find the game and hover over it
            game_found = False
            game_elements = await page.query_selector_all('[class*="game"], [class*="matchup"], div')
            
            for element in game_elements:
                text = await element.text_content()
                # Look for DET and TB in the same element (they're stacked)
                if text and "DET" in text and "TB" in text:
                    # Hover over the game
                    await element.hover()
                    await page.wait_for_timeout(1000)
                    
                    # Look for the preview link that appears on hover
                    preview_link = await page.query_selector('text="Preview Now"')
                    if not preview_link:
                        preview_link = await page.query_selector('text="Preview Matchup"')
                    if not preview_link:
                        # Try finding by partial text
                        preview_link = await page.query_selector('[class*="preview"], a:has-text("Flaherty")')
                    
                    if preview_link:
                        await preview_link.click()
                        game_found = True
                        break
            
            if not game_found:
                await browser.close()
                return {"error": "Game not found"}
            
            await page.wait_for_timeout(3000)
            
            # Get all clickable player names
            player_data = {
                "pitchers": {},
                "batters": {}
            }
            
            # Click each player and get their data
            player_links = await page.query_selector_all('a[href*="savant-player"]')
            
            for i, link in enumerate(player_links):
                player_name = await link.text_content()
                
                # Click the player in a new tab
                page2 = await browser.new_page()
                href = await link.get_attribute('href')
                await page2.goto(f"https://baseballsavant.mlb.com{href}", timeout=30000)
                await page2.wait_for_timeout(2000)
                
                # Check if it's a pitcher or batter page
                url = page2.url
                
                if 'pitching' in url:
                    # Get pitcher arsenal
                    arsenal_text = await page2.evaluate('''
                        () => {
                            const elements = document.querySelectorAll('*');
                            for (const el of elements) {
                                if (el.textContent.includes('relies on') && el.textContent.includes('pitches')) {
                                    const parent = el.parentElement;
                                    const text = parent.textContent;
                                    
                                    // Extract pitch types and percentages
                                    const pitches = [];
                                    const matches = text.matchAll(/([A-Za-z\s]+)\s*\((\d+\.?\d*)%\)/g);
                                    for (const match of matches) {
                                        pitches.push({
                                            pitch_type: match[1].trim(),
                                            usage: match[2] + '%'
                                        });
                                    }
                                    return pitches;
                                }
                            }
                            return [];
                        }
                    ''')
                    
                    player_data["pitchers"][player_name] = arsenal_text
                    
                elif 'hitting' in url:
                    # Get batter's run values by pitch type
                    pitch_data = await page2.evaluate('''
                        () => {
                            const data = {};
                            const tables = document.querySelectorAll('table');
                            
                            for (const table of tables) {
                                // Check if this is the run values table
                                const prevElement = table.previousElementSibling;
                                if (prevElement && prevElement.textContent.includes('Run Values by Pitch Type')) {
                                    const rows = table.querySelectorAll('tbody tr');
                                    
                                    rows.forEach(row => {
                                        const cells = row.querySelectorAll('td');
                                        if (cells.length > 10) {
                                            const year = cells[0]?.textContent.trim();
                                            // Only get 2025 data
                                            if (year === '2025') {
                                                const pitchType = cells[1]?.textContent.trim();
                                                data[pitchType] = {
                                                    pa: cells[7]?.textContent.trim(),
                                                    ba: cells[8]?.textContent.trim(),
                                                    slg: cells[9]?.textContent.trim(),
                                                    woba: cells[10]?.textContent.trim()
                                                };
                                            }
                                        }
                                    });
                                    return data;
                                }
                            }
                            return data;
                        }
                    ''')
                    
                    player_data["batters"][player_name] = pitch_data
                
                await page2.close()
                
                # Rate limiting
                if i < len(player_links) - 1:
                    await asyncio.sleep(1)
            
            await browser.close()
            return player_data
            
        except Exception as e:
            await browser.close()
            return {"error": str(e)}

async def analyze_game(game_data: dict):
    """Analyze a single game with lineup and Savant data"""
    # Get Savant data for this game
    savant_data = await get_savant_data_for_game(
        game_data["away_team"],
        game_data["home_team"]
    )
    
    if "error" in savant_data:
        return {
            "game": f"{game_data['away_team']} @ {game_data['home_team']}",
            "error": savant_data["error"]
        }
    
    # Structure the analysis
    analysis = {
        "game": f"{game_data['away_team']} @ {game_data['home_team']}",
        "pitchers": savant_data["pitchers"],
        "matchups": []
    }
    
    # For each batter, show how they hit against the opposing pitcher's arsenal
    for batter_name, batter_stats in savant_data["batters"].items():
        # Determine which pitcher this batter faces
        # This is simplified - you'd need to match based on team
        batter_matchup = {
            "batter": batter_name,
            "vs_pitches": []
        }
        
        # Match with pitcher arsenal
        for pitcher_name, arsenal in savant_data["pitchers"].items():
            for pitch in arsenal:
                pitch_type = pitch["pitch_type"]
                if pitch_type in batter_stats:
                    batter_matchup["vs_pitches"].append({
                        "pitch_type": pitch_type,
                        "pitcher_usage": pitch["usage"],
                        "batter_stats": batter_stats[pitch_type]
                    })
        
        if batter_matchup["vs_pitches"]:
            analysis["matchups"].append(batter_matchup)
    
    return analysis

@app.get("/")
async def get_matchup_analysis():
    """Get matchup analysis for DET @ TB game"""
    try:
        # Get lineups
        lineup_data = await get_lineups()
        
        if not lineup_data:
            return {"error": "No games found"}
        
        # Find DET @ TB game
        game = None
        for g in lineup_data:
            if g["away_team"] == "DET" and g["home_team"] == "TB":
                game = g
                break
        
        if not game:
            return {"error": "DET @ TB game not found"}
        
        # Analyze the game
        analysis = await analyze_game(game)
        
        return analysis
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/game/{away_team}/{home_team}")
async def get_specific_game(away_team: str, home_team: str):
    """Get analysis for a specific game"""
    try:
        # Get lineups
        lineup_data = await get_lineups()
        
        # Find the game
        game = None
        for g in lineup_data:
            if g["away_team"].upper() == away_team.upper() and g["home_team"].upper() == home_team.upper():
                game = g
                break
        
        if not game:
            return {"error": "Game not found"}
        
        # Analyze the game
        analysis = await analyze_game(game)
        
        return analysis
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/test-lineup-api")
async def test_lineup_api():
    """Test connection to lineup API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(LINEUP_API_URL, timeout=30.0)
            return {
                "status": "success",
                "status_code": response.status_code,
                "data_length": len(response.json()) if response.status_code == 200 else 0
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
