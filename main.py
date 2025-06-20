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

async def get_pitcher_arsenal(pitcher_name: str):
    """Get pitcher arsenal using Baseball Savant's search"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = await browser.new_page()
        
        try:
            print(f"Searching for pitcher: {pitcher_name}")
            
            # Go to Baseball Savant
            await page.goto("https://baseballsavant.mlb.com/", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # Find and use the search box
            search_box = await page.query_selector('input[type="text"]')
            if search_box:
                print(f"Found search box, typing: {pitcher_name}")
                await search_box.type(pitcher_name)
                await page.wait_for_timeout(3000)  # More time for results
                
                # Check what's on the page after typing
                page_text = await page.evaluate('() => document.body.innerText')
                print(f"Page contains: {page_text[:200]}...")  # First 200 chars
                
                # Try multiple selectors for search results
                first_result = await page.query_selector('.ui-menu-item a')
                if not first_result:
                    first_result = await page.query_selector('a[href*="savant-player"]')
                if not first_result:
                    first_result = await page.query_selector('.search-results a')
                if not first_result:
                    # Try to find any link with the player's name
                    all_links = await page.query_selector_all('a')
                    print(f"Found {len(all_links)} total links on page")
                    for link in all_links:
                        text = await link.text_content()
                        if text and pitcher_name.lower() in text.lower():
                            first_result = link
                            break
                
                if first_result:
                    await first_result.click()
                    await page.wait_for_timeout(3000)
                else:
                    print(f"No search results for {pitcher_name}")
                    await browser.close()
                    return []
            else:
                print("Could not find search box")
                # Let's see what inputs are on the page
                all_inputs = await page.query_selector_all('input')
                print(f"Found {len(all_inputs)} input elements")
                for i, inp in enumerate(all_inputs):
                    inp_type = await inp.get_attribute('type')
                    inp_placeholder = await inp.get_attribute('placeholder')
                    print(f"Input {i}: type={inp_type}, placeholder={inp_placeholder}")
                await browser.close()
                return []
            
            # Extract arsenal text
            arsenal = await page.evaluate('''
                () => {
                    const elements = document.querySelectorAll('*');
                    for (const el of elements) {
                        if (el.textContent.includes('relies on') && el.textContent.includes('pitches')) {
                            const parent = el.parentElement;
                            const text = parent.textContent;
                            
                            // Extract pitch types and percentages
                            const pitches = [];
                            const matches = text.matchAll(/([A-Za-z\s]+)\\s*\\(([\\d.]+)%\\)/g);
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
            
            print(f"Arsenal for {pitcher_name}: {arsenal}")
            await browser.close()
            return arsenal
            
        except Exception as e:
            print(f"Error getting arsenal for {pitcher_name}: {str(e)}")
            await browser.close()
            return []

async def get_batter_vs_pitches(batter_name: str):
    """Get batter stats using Baseball Savant's search"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = await browser.new_page()
        
        try:
            print(f"Searching for batter: {batter_name}")
            
            # Go to Baseball Savant
            await page.goto("https://baseballsavant.mlb.com/", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # Find and use the search box
            search_box = await page.query_selector('input[type="text"]')
            if search_box:
                await search_box.type(batter_name)
                await page.wait_for_timeout(3000)  # More time for results
                
                # Try multiple selectors for search results
                first_result = await page.query_selector('.ui-menu-item a')
                if not first_result:
                    first_result = await page.query_selector('a[href*="savant-player"]')
                if not first_result:
                    first_result = await page.query_selector('.search-results a')
                if not first_result:
                    # Try to find any link with the player's name
                    all_links = await page.query_selector_all('a')
                    for link in all_links:
                        text = await link.text_content()
                        if text and batter_name.lower() in text.lower():
                            first_result = link
                            break
                
                if first_result:
                    await first_result.click()
                    await page.wait_for_timeout(3000)
                else:
                    print(f"No search results for {batter_name}")
                    await browser.close()
                    return {}
            else:
                print("Could not find search box")
                await browser.close()
                return {}
            
            # Extract Run Values by Pitch Type table
            pitch_data = await page.evaluate('''
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
            
            print(f"Pitch data for {batter_name}: {pitch_data}")
            await browser.close()
            return pitch_data
            
        except Exception as e:
            print(f"Error getting stats for {batter_name}: {str(e)}")
            await browser.close()
            return {}

async def analyze_game(game_data: dict):
    """Analyze a single game"""
    result = {
        "game": f"{game_data['away_team']} @ {game_data['home_team']}",
        "pitchers": {
            "away": {
                "name": game_data['away_pitcher'],
                "arsenal": []
            },
            "home": {
                "name": game_data['home_pitcher'],
                "arsenal": []
            }
        },
        "key_matchups": []
    }
    
    # Get pitcher arsenals (remove handedness markers)
    away_pitcher_name = game_data['away_pitcher'].replace('(R)', '').replace('(L)', '').strip()
    home_pitcher_name = game_data['home_pitcher'].replace('(R)', '').replace('(L)', '').strip()
    
    result['pitchers']['away']['arsenal'] = await get_pitcher_arsenal(away_pitcher_name)
    result['pitchers']['home']['arsenal'] = await get_pitcher_arsenal(home_pitcher_name)
    
    # Get top 3 batters from each team
    for i in range(min(3, len(game_data['away_lineup']))):
        # Extract batter name from away lineup format: "1   J.P. Crawford (L) SS"
        parts = game_data['away_lineup'][i].split()
        name_parts = []
        for part in parts[1:]:  # Skip the number
            if '(' in part:
                break
            name_parts.append(part)
        batter_name = ' '.join(name_parts)
        
        # Get batter stats
        batter_stats = await get_batter_vs_pitches(batter_name)
        
        # Match with home pitcher's arsenal
        matchup = {
            "batter": batter_name,
            "team": game_data['away_team'],
            "vs_pitcher": home_pitcher_name,
            "performance": []
        }
        
        for pitch in result['pitchers']['home']['arsenal']:
            pitch_type = pitch['pitch_type']
            if pitch_type in batter_stats:
                matchup['performance'].append({
                    "pitch_type": pitch_type,
                    "pitcher_usage": pitch['usage'],
                    "batter_stats": batter_stats[pitch_type]
                })
        
        if matchup['performance']:
            result['key_matchups'].append(matchup)
        
        await asyncio.sleep(1)  # Rate limiting
    
    # Do the same for home batters
    for i in range(min(3, len(game_data['home_lineup']))):
        # Extract batter name from home lineup format: "LF (S) Ian Happ   1"
        parts = game_data['home_lineup'][i].split()
        name_parts = []
        found_handedness = False
        for part in parts:
            if ')' in part:
                found_handedness = True
                continue
            if found_handedness and not part.isdigit():
                name_parts.append(part)
        batter_name = ' '.join(name_parts)
        
        # Get batter stats
        batter_stats = await get_batter_vs_pitches(batter_name)
        
        # Match with away pitcher's arsenal
        matchup = {
            "batter": batter_name,
            "team": game_data['home_team'],
            "vs_pitcher": away_pitcher_name,
            "performance": []
        }
        
        for pitch in result['pitchers']['away']['arsenal']:
            pitch_type = pitch['pitch_type']
            if pitch_type in batter_stats:
                matchup['performance'].append({
                    "pitch_type": pitch_type,
                    "pitcher_usage": pitch['usage'],
                    "batter_stats": batter_stats[pitch_type]
                })
        
        if matchup['performance']:
            result['key_matchups'].append(matchup)
        
        await asyncio.sleep(1)  # Rate limiting
    
    return result

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
