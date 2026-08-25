import csv
from g2p_cli2 import ShavianOrthography

def generate_template():
    with open('osm_mapping_template.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ARPABET', 'Current_Glyph', 'Hex_Code', 'Unicode_Name', 'New_Glyph', 'Notes'])
        
        # Single Phonemes
        for arpa, char in ShavianOrthography.ARPABET_TO_SHAVIAN.items():
            hex_code = f"U+{ord(char):04X}"
            import unicodedata
            try:
                name = unicodedata.name(char)
            except ValueError:
                name = "UNKNOWN"
            writer.writerow([arpa, char, hex_code, name, "", ""])
            
        # Compounds
        for arpa_tuple, char in ShavianOrthography.COMPOUNDS.items():
            arpa_str = "+".join(arpa_tuple)
            hex_code = f"U+{ord(char):04X}"
            import unicodedata
            try:
                name = unicodedata.name(char)
            except ValueError:
                name = "UNKNOWN"
            writer.writerow([arpa_str, char, hex_code, name, "", ""])
            
    print("Template generated at osm_mapping_template.csv")

if __name__ == '__main__':
    generate_template()
