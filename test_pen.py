import sys
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

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pen.py <font.ttf>")
        sys.exit(1)
    
    font = TTFont(sys.argv[1])
    glyphSet = font.getGlyphSet()
    
    # Test 'A' and 'O' and 'p'
    for gname in ['q', 'seven', 'nine', 'd']:
        if gname not in glyphSet:
            continue
        g = glyphSet[gname]
        
        # Bounds
        bp = BoundsPen(glyphSet)
        g.draw(bp)
        bounds = bp.bounds
        
        # Shape (Kiki/Bouba)
        sp = ShapePen(glyphSet)
        g.draw(sp)
        
        # Statistics
        stat_pen = StatisticsPen(glyphset=glyphSet)
        g.draw(stat_pen)
        
        print(f"--- {gname} ---")
        print(f"Bounds: {bounds}")
        print(f"Lines: {sp.lines}, Curves: {sp.curves}")
        if bounds:
            bbox_center_x = (bounds[0] + bounds[2]) / 2.0
            print(f"BBox Center X: {bbox_center_x}")
        try:
            print(f"Statistics: area={stat_pen.area}, meanX={stat_pen.meanX}, meanY={stat_pen.meanY}")
        except Exception as e:
            print(f"Statistics error: {e}")
