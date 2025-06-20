from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import httpx
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.thebettinginsider.com"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

LINEUP_API_URL = "https://mlb-matchup-analysis-api.onrender.com/"

async def get_pitcher_data(pitcher_name: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = await browser.new_page()
        
        await page.goto("https://baseballsavant.mlb.com/", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # Search for pitcher
        await page.type('input[type="text"]', pitcher_name)
        await page.press('input[type="text"]', 'Enter')
        await page.wait_for_timeout(5000)
        
        # Extract arsenal
        arsenal = await page.evaluate('''
            () => {
                const text = document.body.innerText;
                const pitches = [];
                
                // Find text like "Four Seamer (47.2%)"
                const matches = text.matchAll(/([A-Za-z\\s]+)\\s*\\((\\d+\\.?\\d*)%\\)/g);
                for (const match of matches) {
                    if (match[1].includes('Seamer') || match[1].includes('Slider') || 
                        match[1].includes('Change') || match[1].includes('Curve') || 
                        match[1].includes('Cutter') || match[1].includes('Sinker')) {
                        pitches.push({
                            type: match[1].trim(),
                            usage: match[2] + '%'
                        });
                    }
                }
                
                return pitches;
            }
        ''')
        
        await browser.close()
        return arsenal

@app.get("/")
async def get_matchup_data():
    # Get lineups
    async with httpx.AsyncClient() as client:
        response = await client.get(LINEUP_API_URL, timeout=30.0)
        lineups = response.json()
    
    # Get first game
    if not lineups:
        return {"error": "No games found"}
    
    game = lineups[0]
    
    # Get pitcher arsenals
    away_pitcher = game["away_pitcher"].replace("(R)", "").replace("(L)", "").strip()
    home_pitcher = game["home_pitcher"].replace("(R)", "").replace("(L)", "").strip()
    
    result = {
        "game": f"{game['away_team']} @ {game['home_team']}",
        "pitchers": {
            "away": {
                "name": away_pitcher,
                "arsenal": await get_pitcher_data(away_pitcher)
            },
            "home": {
                "name": home_pitcher,
                "arsenal": await get_pitcher_data(home_pitcher)
            }
        }
    }
    
    return result

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
