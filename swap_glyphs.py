import csv
import re
import unicodedata
import os

def swap_glyphs():
    replacements = {}
    with open('osm_mapping_template.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            arpabet = row['ARPABET'].strip()
            new_glyph = row['New_Glyph'].strip()
            if new_glyph:
                try:
                    uname = unicodedata.name(new_glyph)
                    replacements[arpabet] = (uname, new_glyph)
                except ValueError:
                    print(f"  SKIP  {arpabet:6s}  — could not resolve Unicode name for '{new_glyph}'")

    with open('g2p_cli2.py', 'r', encoding='utf-8') as f:
        content = f.read()

    changed, current, failed = 0, 0, 0

    for arpabet, (uname, glyph) in replacements.items():
        # Match lines like:  "P": "\N{SHAVIAN LETTER PEEP}",    # 𐑐
        pattern = r'("' + re.escape(arpabet) + r'":\s*)"\\N\{.*?\}"(.*?#\s*).*'
        repl = r'\1"\\N{' + uname + r'}"\2' + glyph

        new_content = re.sub(pattern, repl, content)
        if new_content == content:
            # Check whether the pattern even matched (genuine failure vs already current)
            if re.search(pattern, content):
                current += 1
            else:
                print(f"  FAIL  {arpabet:6s}  — no matching line found in g2p_cli2.py")
                failed += 1
        else:
            print(f"  SWAP  {arpabet:6s}  → {glyph}  ({uname})")
            changed += 1
            content = new_content

    with open('g2p_cli2.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\nDone: {changed} changed, {current} already current, {failed} failed.")

if __name__ == '__main__':
    swap_glyphs()
