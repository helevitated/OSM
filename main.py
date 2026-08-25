from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

from g2p_cli2 import ShavianOrthography, DisambiguationPipeline, PhoneticLexicon, Translator

app = FastAPI(title="OSM Translator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the pipeline once globally
lexicon = PhoneticLexicon()
pipeline = DisambiguationPipeline(lexicon)
forward_translator = Translator(lexicon)

# ── Request / Response models ─────────────────────────────────────────────

class TranslationRequest(BaseModel):
    text: str
    direction: str = "to-osm"  # 'to-osm' or 'from-osm'

class TranslationResponse(BaseModel):
    original: str
    translated: str
    diagnostics: list[str] = []

# ── Translation endpoint ──────────────────────────────────────────────────

@app.post("/api/translate", response_model=TranslationResponse)
async def translate(req: TranslationRequest):
    diagnostics: list[str] = []
    translated_text = ""

    try:
        if req.direction == "to-osm":
            translated_text, _, diagnostics = forward_translator.execute_forward(req.text)
        elif req.direction == "from-osm":
            translated_text, diagnostics = pipeline.execute_reverse(req.text)
        else:
            translated_text = "Error: Invalid translation direction."

        return TranslationResponse(
            original=req.text,
            translated=translated_text,
            diagnostics=diagnostics,
        )
    except Exception as e:
        return TranslationResponse(
            original=req.text,
            translated=f"Error during translation: {e}",
            diagnostics=[str(e)],
        )

# ── Hero text endpoint ────────────────────────────────────────────────────
# Returns the OSM rendering of "awesome" using the live glyph mappings,
# so the web app subtitle always reflects the current glyph set.

@app.get("/api/hero-text")
async def hero_text():
    osm, _, _ = forward_translator.execute_forward("awesome")
    return {"osm": osm}

# ── Keyboard layout endpoint ─────────────────────────────────────────────
# Groups glyphs by their phonetic category using the ordering and comments
# in ARPABET_TO_SHAVIAN.  Deduplicates merged phonemes (e.g. AA/AO).

_KEYBOARD_SECTIONS = [
    # (label, ARPABET keys)
    ("Unvoiced",  ["P", "T", "K", "F", "TH", "S", "SH", "CH", "HH"]),
    ("Voiced",    ["B", "D", "G", "V", "DH", "Z", "ZH", "JH"]),
    ("Sonorants", ["M", "N", "NG", "L", "R", "W", "Y"]),
    ("Vowels",    ["IY", "IH", "EY", "EH", "AE", "AA", "AH", "UH", "UW"]),
    ("Diphthongs & Rhotics", ["AY", "OY", "AW", "OW", "ER"]),
]

@app.get("/api/keyboard-layout")
async def get_keyboard_layout():
    rows = []
    for label, keys in _KEYBOARD_SECTIONS:
        seen = set()
        glyphs = []
        for k in keys:
            g = ShavianOrthography.ARPABET_TO_SHAVIAN.get(k)
            if g and g not in seen:
                glyphs.append(g)
                seen.add(g)
        rows.append({"label": label, "keys": glyphs})

    # Compound glyphs (ligatures) as their own row, deduplicated
    compound_glyphs = list(dict.fromkeys(ShavianOrthography.COMPOUNDS.values()))
    rows.append({"label": "Compounds", "keys": compound_glyphs})

    return {"rows": rows}

# ── Static file serving ───────────────────────────────────────────────────

frontend_dir = os.path.join(os.path.dirname(__file__), "public")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="public")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
