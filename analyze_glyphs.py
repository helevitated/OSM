import sys
import csv
import os
import glob
import unicodedata
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.statisticsPen import StatisticsPen
from fontTools.pens.basePen import BasePen

class ShapePen(BasePen):
    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.lines = 0
        self.curves = 0
        
    def _moveTo(self, pt):
        pass
    def _lineTo(self, pt):
        self.lines += 1
    def _curveToOne(self, pt1, pt2, pt3):
        self.curves += 1
    def _qCurveToOne(self, pt1, pt2):
        self.curves += 1
    def _closePath(self):
        pass

# Removed TARGET_BLOCKS to analyze all available scripts (alphabets, syllabaries, logographies)
def in_target_blocks(codepoint):
    return True # Bypass filter to include everything

def analyze_font(font_path):
    print(f"Loading font {font_path}...")
    try:
        font = TTFont(font_path)
    except Exception as e:
        print(f"Could not load font: {e}")
        return []
        
    try:
        glyphSet = font.getGlyphSet()
    except Exception as e:
        print(f"Skipping font (no outlines): {e}")
        return []
    
    # Get font metrics
    os2 = font.get('OS/2')
    
    if os2 and hasattr(os2, 'sxHeight') and os2.sxHeight > 0:
        x_height = os2.sxHeight
    else:
        # Fallback to measuring 'x'
        if 'x' in glyphSet:
            bp = BoundsPen(glyphSet)
            glyphSet['x'].draw(bp)
            x_height = bp.bounds[3] if bp.bounds else 500
        else:
            x_height = 500
            
    # Base baseline
    baseline = 0
            
    results = []
    cmap = font.getBestCmap()
    if not cmap:
        return []
    
    threshold_y = x_height * 0.1 # 10% tolerance for ascender/descender
    sym_threshold = 0.05 # 5% of width tolerance for symmetry
    
    count = 0
    font_name = os.path.basename(font_path)
    
    for codepoint, gname in cmap.items():
        if not in_target_blocks(codepoint):
            continue
            
        char = chr(codepoint)
        
        # Filter out marks and non-letters if possible, but keep symbols & math
        cat = unicodedata.category(char)
        if cat.startswith('M') or cat.startswith('C') or cat.startswith('Z'):
            continue
            
        char_name = unicodedata.name(char, gname)
        
        g = glyphSet[gname]
        
        # Bounding Box
        bp = BoundsPen(glyphSet)
        try:
            g.draw(bp)
        except Exception:
            continue
            
        bounds = bp.bounds
        if not bounds:
            continue # Empty glyph (space etc)
            
        xMin, yMin, xMax, yMax = bounds
        width = xMax - xMin
        if width == 0:
            continue
            
        # Verticality
        has_ascender = yMax > (x_height + threshold_y)
        has_descender = yMin < (baseline - threshold_y)
        
        # Symmetry
        bbox_center_x = xMin + (width / 2.0)
        
        stat_pen = StatisticsPen(glyphset=glyphSet)
        try:
            g.draw(stat_pen)
            area = stat_pen.area
            mean_x = stat_pen.meanX
        except Exception:
            continue
            
        if area == 0:
            continue
            
        sym_diff = mean_x - bbox_center_x
        if sym_diff < -(width * sym_threshold):
            symmetry = "Right-Pointing"
        elif sym_diff > (width * sym_threshold):
            symmetry = "Left-Pointing"
        else:
            symmetry = "Symmetrical"
            
        # Shape (Bouba vs Kiki)
        sp = ShapePen(glyphSet)
        g.draw(sp)
        total_segments = sp.lines + sp.curves
        if total_segments > 0:
            bouba_score = round(sp.curves / total_segments, 3)
        else:
            bouba_score = 0.0
            
        results.append({
            'Unicode': f"U+{codepoint:04X}",
            'Char': char,
            'Name': char_name,
            'Ascender': has_ascender,
            'Descender': has_descender,
            'Symmetry': symmetry,
            'Bouba_Score': bouba_score,
            'Source_Font': font_name
        })
        count += 1
        
    return results

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyze_glyphs.py <font.ttf OR directory> <output.csv>")
        sys.exit(1)
        
    input_path = sys.argv[1]
    output_csv = sys.argv[2]
    
    all_results = []
    
    if os.path.isdir(input_path):
        print(f"Scanning directory: {input_path}")
        # Find all Noto Sans/Serif fonts
        fonts = glob.glob(os.path.join(input_path, '*noto*.ttf'), recursive=True) + glob.glob(os.path.join(input_path, 'Noto*.ttf'), recursive=True)
        # Deduplicate
        fonts = list(set(fonts))
        print(f"Found {len(fonts)} Noto fonts.")
        for font in fonts:
            # We skip ExtraCondensed and similar variants just to keep things fast, unless needed.
            # Let's just process Regular, Math, Syllables etc.
            if "Condensed" in font or "Italic" in font or "Bold" in font or "Black" in font or "Light" in font or "Thin" in font:
                continue
            all_results.extend(analyze_font(font))
    else:
        all_results.extend(analyze_font(input_path))
        
    # Deduplicate results based on Unicode codepoint (taking the first font that had it)
    seen_codepoints = set()
    deduped_results = []
    for r in all_results:
        if r['Unicode'] not in seen_codepoints:
            seen_codepoints.add(r['Unicode'])
            deduped_results.append(r)
            
    print(f"Analyzed {len(deduped_results)} unique glyphs. Writing to {output_csv}...")
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Unicode', 'Char', 'Name', 'Ascender', 'Descender', 'Symmetry', 'Bouba_Score', 'Source_Font'])
        writer.writeheader()
        writer.writerows(deduped_results)
        
    print("Done!")
