import sys
import re
import argparse
from collections import Counter
from g2p_en import G2p
from nltk.corpus import cmudict, brown

# =========================================================================== #
# FORWARD MAPPING: ARPABET → Shavian (single phonemes)
# You can modify these values to your preferred Shavian characters.
# Each key is an ARPABET phoneme (stress digits stripped before lookup).
# Each value uses Python's \N{UNICODE NAME} syntax for clarity.
# =========================================================================== #
ARPABET_TO_SHAVIAN = {
    # Consonants
    "P":  "\N{SHAVIAN LETTER PEEP}",
    "B":  "\N{SHAVIAN LETTER BIB}",
    "T":  "\N{SHAVIAN LETTER TOT}",
    "D":  "\N{SHAVIAN LETTER DEAD}",
    "K":  "\N{SHAVIAN LETTER KICK}",
    "G":  "\N{SHAVIAN LETTER GAG}",
    "F":  "\N{SHAVIAN LETTER FEE}",
    "V":  "\N{SHAVIAN LETTER VOW}",
    "TH": "\N{SHAVIAN LETTER THIGH}",
    "DH": "\N{SHAVIAN LETTER THEY}",
    "S":  "\N{SHAVIAN LETTER SO}",
    "Z":  "\N{SHAVIAN LETTER ZOO}",
    "SH": "\N{SHAVIAN LETTER SURE}",
    "ZH": "\N{SHAVIAN LETTER MEASURE}",
    "CH": "\N{SHAVIAN LETTER CHURCH}",
    "JH": "\N{SHAVIAN LETTER JUDGE}",
    "M":  "\N{SHAVIAN LETTER MIME}",
    "N":  "\N{SHAVIAN LETTER NUN}",
    "NG": "\N{SHAVIAN LETTER HUNG}",
    "L":  "\N{SHAVIAN LETTER LOLL}",
    "R":  "\N{SHAVIAN LETTER ROAR}",
    "Y":  "\N{SHAVIAN LETTER YEA}",
    "W":  "\N{SHAVIAN LETTER WOE}",
    "HH": "\N{SHAVIAN LETTER HA-HA}",
    # Vowels
    "AA": "\N{SHAVIAN LETTER AH}",
    "AE": "\N{SHAVIAN LETTER ASH}",
    "AH": "\N{SHAVIAN LETTER UP}",   # stressed; see also ADO (𐑩) for schwa
    "AO": "\N{SHAVIAN LETTER AWE}",
    "AW": "\N{SHAVIAN LETTER OUT}",
    "AY": "\N{SHAVIAN LETTER ICE}",
    "EH": "\N{SHAVIAN LETTER EGG}",
    "ER": "\N{SHAVIAN LETTER ERR}",
    "EY": "\N{SHAVIAN LETTER AGE}",
    "IH": "\N{SHAVIAN LETTER IF}",
    "IY": "\N{SHAVIAN LETTER EAT}",
    "OW": "\N{SHAVIAN LETTER OAK}",
    "OY": "\N{SHAVIAN LETTER OIL}",
    "UH": "\N{SHAVIAN LETTER WOOL}",
    "UW": "\N{SHAVIAN LETTER OOZE}",
}

# =========================================================================== #
# COMPOUND SHAVIAN VOWELS (ARPABET bigram → single Shavian character)
#
# Shavian has dedicated letters for common vowel+R combinations.
# These are checked BEFORE the single-phoneme table during forward
# translation so that, e.g., EH + R → 𐑺 (AIR) instead of 𐑧𐑮 (EGG+ROAR).
# =========================================================================== #
ARPABET_COMPOUNDS = {
    ("EH", "R"):  "\N{SHAVIAN LETTER AIR}",    # air, there, bear
    ("AO", "R"):  "\N{SHAVIAN LETTER OR}",      # or, for, more
    ("AA", "R"):  "\N{SHAVIAN LETTER ARE}",     # are, car, far
    ("IH", "R"):  "\N{SHAVIAN LETTER EAR}",     # near, here (IH variant)
    ("IY", "R"):  "\N{SHAVIAN LETTER EAR}",     # ear, here  (IY variant)
}

# =========================================================================== #
# REVERSE MAPPINGS (auto-built from the tables above)
# =========================================================================== #

# Single Shavian char → single ARPABET phoneme
SHAVIAN_TO_ARPABET = {v: k for k, v in ARPABET_TO_SHAVIAN.items()}

# Compound Shavian char → tuple of ARPABET phonemes
SHAVIAN_COMPOUND_TO_ARPABET = {
    "\N{SHAVIAN LETTER AIR}":   ("EH", "R"),
    "\N{SHAVIAN LETTER OR}":    ("AO", "R"),
    "\N{SHAVIAN LETTER ARE}":   ("AA", "R"),
    "\N{SHAVIAN LETTER EAR}":   ("IH", "R"),
    "\N{SHAVIAN LETTER ARRAY}": ("AH", "R"),
}

# =========================================================================== #
# WESTERN CANADIAN ENGLISH — COT-CAUGHT MERGER
#
# AO ≈ AA when NOT immediately before R.  Before R the distinction is
# preserved (START ≠ NORTH), so compound vowels ARE (𐑸) and OR (𐑹)
# remain separate.
# =========================================================================== #
MERGER_MAP = {"AO": "AA"}

def _normalize_phoneme_list(phonemes):
    """Apply cot-caught merger only to vowels NOT followed by R."""
    out = []
    for i, p in enumerate(phonemes):
        base = re.sub(r'\d+', '', p)
        next_base = re.sub(r'\d+', '', phonemes[i + 1]) if i + 1 < len(phonemes) else None
        if base in MERGER_MAP and next_base != "R":
            out.append(MERGER_MAP[base])
        else:
            out.append(base)
    return tuple(out)

# =========================================================================== #
# WORD-FREQUENCY TABLE  (Brown corpus)
# =========================================================================== #
_WORD_FREQ = None

def _get_word_freq():
    global _WORD_FREQ
    if _WORD_FREQ is None:
        _WORD_FREQ = Counter(w.lower() for w in brown.words())
    return _WORD_FREQ

# =========================================================================== #
# POS-TAG REFINEMENT
#
# After round-trip verification picks candidates, POS-tag the full sentence
# and check whether an alternative homophone is a better POS fit.  This
# catches noun/verb confusions (hew→hue), proper-vs-common noun issues
# (Hugh→hue), preposition/number mix-ups (four→for), etc.
# =========================================================================== #
from nltk import pos_tag as nltk_pos_tag
import urllib.request
import urllib.parse
import json
import re

def _languagetool_pass(words, slot_candidates):
    """
    Query the LanguageTool API once for the entire sentence.
    Returns a dict mapping word_index -> chosen_candidate.
    """
    url = "https://api.languagetool.org/v2/check"
    
    # Reconstruct text and build offset mapping
    text = ""
    offset_to_idx = {}
    for i, w in enumerate(words):
        if i > 0 and w[0].isalpha():
            text += " "
        start_offset = len(text)
        text += w
        # Map every character index of this word to its word index
        for j in range(len(w)):
            offset_to_idx[start_offset + j] = i
            
    try:
        data = urllib.parse.urlencode({'language': 'en-US', 'text': text}).encode('utf-8')
        req = urllib.request.Request(url, data=data)
        req.add_header('User-Agent', 'g2p_cli_shavian_tool/1.0')
        with urllib.request.urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode('utf-8'))
            
        resolutions = {}
        for m in res.get('matches', []):
            if not m.get('replacements'):
                continue
            offset = m['offset']
            if offset in offset_to_idx:
                idx = offset_to_idx[offset]
                cands = slot_candidates[idx]
                if not cands:
                    continue
                
                # Check if LT's suggested replacements match any of our phonetic candidates
                for rep in m['replacements']:
                    val = rep['value'].lower()
                    if val in cands:
                        resolutions[idx] = val
                        break
        return resolutions
    except Exception as e:
        return {} # Fallback gracefully on API failure

_TAG_NORM = {
    # Penn Treebank / Brown tags → broad category
    'NN': 'n', 'NNS': 'n',
    'NP': 'np', 'NPS': 'np', 'NNP': 'np', 'NNPS': 'np', 'NP$': 'np',
    'VB': 'v', 'VBD': 'v', 'VBG': 'v', 'VBN': 'v', 'VBP': 'v', 'VBZ': 'v',
    'IN': 'prep', 'CD': 'num', 'DT': 'det', 'AT': 'det',
    'JJ': 'adj', 'JJR': 'adj', 'JJS': 'adj',
    'RB': 'adv', 'RBR': 'adv', 'RBS': 'adv',
    'PRP': 'pron', 'PRP$': 'pron', 'PP$': 'pron',
    'UH': 'uh',
}

def _norm_tag(tag):
    return _TAG_NORM.get(tag, tag)

_WORD_POS = None

def _get_word_pos_map():
    """word → {normalised_tag: count} from Brown tagged corpus."""
    global _WORD_POS
    if _WORD_POS is None:
        _WORD_POS = {}
        for word, tag in brown.tagged_words():
            w = word.lower()
            nt = _norm_tag(tag)
            _WORD_POS.setdefault(w, Counter())[nt] += 1
    return _WORD_POS

def _pos_score(word, context_tag, wpm):
    """How often does *word* appear with the normalised *context_tag*?"""
    w = word.lower()
    if w not in wpm:
        return 0.0          # unknown word — never override a known one
    counts = wpm[w]
    total = sum(counts.values())
    return counts.get(_norm_tag(context_tag), 0) / total if total else 0.0

def _pos_refine(words, candidates_per_word, interactive=False):
    """
    Second pass: POS-tag the sentence, rescore ambiguous positions.
    Returns (refined_words, list_of_refinement_messages).
    """
    if not words:
        return words, []

    # Capitalize 'i' so the POS tagger correctly identifies it as a pronoun
    tag_input = [w.capitalize() if w == 'i' else w for w in words]
    tagged = nltk_pos_tag(tag_input)       # [(word, POS), …]
    wpm = _get_word_pos_map()
    refined = list(words)
    notes = []

    # Pre-pass for interactive grouping
    choice_cache = {}
    ambiguities = {}
    
    for i, (word_cased, pos) in enumerate(tagged):
        if i >= len(candidates_per_word):
            break
        cands = candidates_per_word[i]
        if not cands or len(cands) <= 1:
            continue
        
        scored_cands = sorted([(c, _pos_score(c, pos, wpm)) for c in cands], 
                              key=lambda x: x[1], reverse=True)
        top_score = scored_cands[0][1]
        runner_up_score = scored_cands[1][1] if len(scored_cands) > 1 else 0
        
        # True ambiguity condition
        if abs(top_score - runner_up_score) < 0.15 or top_score < 0.3:
            cands_list = [c for c, _ in scored_cands]
            cands_tuple = tuple(cands_list)
            ambiguities.setdefault(cands_tuple, []).append((i, pos))
            
    # Prompt user for each group (if interactive mode is on)
    if interactive:
        for cands_tuple, instances in ambiguities.items():
            print(f"\n[Ambiguity Group] Options: {', '.join(cands_tuple)} (Appears {len(instances)} times)")
            for j, (idx, pos) in enumerate(instances, 1):
                ctx = " ".join(words[max(0, idx-3):idx]) + " ___ " + " ".join(words[idx+1:idx+4])
                print(f"  Context {j}: \"{ctx}\" (POS={pos})")
            
            for idx, c in enumerate(cands_tuple, 1):
                print(f"  {idx}) {c}")
            
            while True:
                choice = input(f"Select choice for ALL instances (1-{len(cands_tuple)}) [default 1]: ").strip()
                if not choice:
                    choice_cache[cands_tuple] = cands_tuple[0]
                    break
                if choice.isdigit() and 1 <= int(choice) <= len(cands_tuple):
                    choice_cache[cands_tuple] = cands_tuple[int(choice)-1]
                    break
                print("Invalid choice.")

    for i, (word_cased, pos) in enumerate(tagged):
        word = words[i]
        if i >= len(candidates_per_word):
            break
        cands = candidates_per_word[i]
        if not cands or len(cands) <= 1:
            continue

        current_score = _pos_score(word, pos, wpm)
        best, best_score = word, current_score

        # Check if we already resolved this via interactive mode
        scored_cands = sorted([(c, _pos_score(c, pos, wpm)) for c in cands], 
                              key=lambda x: x[1], reverse=True)
        cands_tuple = tuple(c for c, _ in scored_cands)
        
        if interactive and cands_tuple in choice_cache:
            best = choice_cache[cands_tuple]
            if best != word:
                refined[i] = best
                notes.append(
                    f"  USER: '{word}' → '{best}' "
                    f"(context POS={pos}, manually selected)")
            continue

        for c in cands:
            if c == word:
                continue
            s = _pos_score(c, pos, wpm)
            if s > best_score:
                best, best_score = c, s

        # Automated swap logic (only swap if the original word is a poor fit and improvement is clear)
        if best != word and current_score < 0.5 and (best_score - current_score) > 0.15:
            refined[i] = best
            notes.append(
                f"  POS: '{word}' → '{best}' "
                f"(context POS={pos}, score {current_score:.2f}→{best_score:.2f})")

    return refined, notes

# =========================================================================== #
# REVERSE CMU INDEX
# =========================================================================== #
def _build_reverse_cmu_index():
    """
    Map normalised phoneme tuples → list of English words.
    Cot-caught merger is applied only to non-pre-R vowels.
    """
    index = {}
    for word, phonemes in cmudict.entries():
        key = _normalize_phoneme_list(phonemes)
        index.setdefault(key, []).append(word)
    return index

def _pick_best_candidate(candidates):
    """Choose the most natural English word from a list of homophones."""
    freq = _get_word_freq()
    # Filter out entries with periods, numbers, or other oddities
    clean = [w for w in candidates if w.isalpha()]
    pool = clean if clean else candidates
    return max(pool, key=lambda w: freq.get(w, 0))

# =========================================================================== #
# FORWARD: English → Shavian
# =========================================================================== #
def _strip_stress(phoneme):
    return re.sub(r'\d+', '', phoneme)

def translate_to_shavian(phonemes):
    """Convert a list of ARPABET phonemes to a Shavian string."""
    shavian = []
    i = 0
    while i < len(phonemes):
        p = _strip_stress(phonemes[i])
        # Try bigram compound match first
        if i + 1 < len(phonemes):
            p_next = _strip_stress(phonemes[i + 1])
            if (p, p_next) in ARPABET_COMPOUNDS:
                shavian.append(ARPABET_COMPOUNDS[(p, p_next)])
                i += 2
                continue
        # Single phoneme match
        if p in ARPABET_TO_SHAVIAN:
            shavian.append(ARPABET_TO_SHAVIAN[p])
        else:
            shavian.append(phonemes[i])   # preserve spaces / punctuation
        i += 1
    return "".join(shavian)

# =========================================================================== #
# REVERSE: Shavian → English
# =========================================================================== #
_SHAVIAN_RANGE = range(0x10450, 0x10480)

def _is_shavian(ch):
    return ord(ch) in _SHAVIAN_RANGE

def shavian_to_arpabet(shavian_word):
    """Convert Shavian characters to a flat list of ARPABET phonemes."""
    phonemes = []
    for ch in shavian_word:
        if ch in SHAVIAN_COMPOUND_TO_ARPABET:
            phonemes.extend(SHAVIAN_COMPOUND_TO_ARPABET[ch])
        elif ch in SHAVIAN_TO_ARPABET:
            phonemes.append(SHAVIAN_TO_ARPABET[ch])
        # else: skip non-Shavian chars (handled separately as punctuation)
    return phonemes

def _tokenize_shavian(text):
    """Split Shavian text into a list of (type, value) tokens."""
    pattern = r'[{0}-{1}]+|[^\S\x00]+|[^{0}-{1}\s]+'.format(
        chr(0x10450), chr(0x1047F))
    tokens = []
    for m in re.finditer(pattern, text):
        tok = m.group()
        if tok.isspace():
            tokens.append(("space", tok))
        elif any(_is_shavian(ch) for ch in tok):
            tokens.append(("shavian", tok))
        else:
            tokens.append(("punct", tok))
    return tokens

# =========================================================================== #
# ROUND-TRIP VERIFIED REVERSE: Shavian → English
#
# For each Shavian word with multiple homophone candidates, re-encode the
# top candidates through g2p → Shavian.  Pick the first candidate whose
# re-encoding matches the original Shavian input.  This ensures the chosen
# English word is the one that would PRODUCE this Shavian in the forward
# direction — a true salva veritate check.
# =========================================================================== #
def verified_reverse(shavian_text, g2p_model, reverse_index, interactive=False):
    tokens = _tokenize_shavian(shavian_text)
    freq = _get_word_freq()

    # ---- Pass 1: round-trip verified candidate selection ----
    # Build a list of result "slots" so we can refine word slots later.
    slots = []            # (kind, value)  — kind ∈ {word, other}
    slot_candidates = []  # parallel to word-slots only: list of clean candidates
    details = []

    for kind, tok in tokens:
        if kind != "shavian":
            slots.append(("other", tok))
            continue

        arpabet = shavian_to_arpabet(tok)
        key = _normalize_phoneme_list(arpabet)
        candidates = reverse_index.get(key, [])

        if not candidates:
            fallback = "/" + " ".join(arpabet) + "/"
            slots.append(("other", fallback))
            details.append(f"  {tok}  →  (no CMU match: {fallback})")
            continue

        unique = sorted(set(candidates))
        clean = [w for w in unique if w.isalpha()]
        pool = clean if clean else unique
        ranked = sorted(pool, key=lambda w: freq.get(w, 0), reverse=True)

        # Round-trip test: pick highest-freq candidate that re-encodes to
        # the same Shavian.  Test up to 10 candidates.
        chosen = None
        for cand in ranked[:10]:
            re_shavian = translate_to_shavian(g2p_model(cand))
            if re_shavian == tok:
                chosen = cand
                break

        if chosen is None:
            chosen = ranked[0]
            re_shavian = translate_to_shavian(g2p_model(chosen))
            tag = f"⚠ re-encodes as {re_shavian}"
        else:
            tag = "✅"

        slots.append(("word", chosen))
        slot_candidates.append(pool)
        if len(unique) > 1:
            details.append(f"  {tok}  →  {chosen} {tag}  "
                           f"(candidates: {', '.join(unique)})")

    # ---- Pass 2: POS-tag refinement ----
    word_indices = [i for i, (k, _) in enumerate(slots) if k == "word"]
    words = [slots[i][1] for i in word_indices]

    # ---- Pass 2: LanguageTool grammar API pass ----
    lt_resolutions = _languagetool_pass(words, slot_candidates)
    lt_refined = list(words)
    lt_notes = []
    
    for idx, best in lt_resolutions.items():
        word = words[idx]
        if best != word:
            lt_refined[idx] = best
            lt_notes.append(
                f"  API: '{word}' → '{best}' "
                f"(resolved by LanguageTool grammar check)")
            # Update the slots and words array so POS pass builds on this
            slots[word_indices[idx]] = ("word", best)
            words[idx] = best

    # ---- Pass 3: POS-tag refinement & Interactive Fallback ----
    refined_words, pos_notes = _pos_refine(words, slot_candidates, interactive)
    for j, idx in enumerate(word_indices):
        slots[idx] = ("word", refined_words[j])
        
    details.extend(lt_notes)
    details.extend(pos_notes)

    return "".join(v for _, v in slots), details

# =========================================================================== #
# ROUND-TRIP VERIFIED FORWARD: English → Shavian
#
# After translating, reverse-translate the Shavian output and compare
# word-by-word with the original.  Flag any words that don't survive the
# round trip (true homophones) and, where possible, try alternative CMU
# pronunciations to find a Shavian spelling that round-trips correctly.
# =========================================================================== #
def _segment_g2p(phonemes):
    """Split flat g2p output into tagged groups: ('word', phonemes) or ('punct', text)."""
    groups, cur = [], []
    for p in phonemes:
        if p == ' ':
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(p)
    if cur:
        groups.append(cur)
    # Tag each group: single non-alpha token = punctuation, else word
    tagged = []
    for g in groups:
        if len(g) == 1 and not g[0][0].isalpha():
            tagged.append(("punct", g[0]))
        else:
            tagged.append(("word", g))
    return tagged

def verified_forward(text, g2p_model, reverse_index):
    cmu = cmudict.dict()
    phonemes = g2p_model(text)
    tagged_groups = _segment_g2p(phonemes)

    # Extract original words (alpha tokens only) for comparison
    orig_tokens = re.findall(r"[A-Za-z']+|[^\w\s]+", text)
    orig_words = [t for t in orig_tokens if t[0].isalpha()]

    shavian_words = []   # parallel to orig_words (word groups only)
    diagnostics = []
    wi = 0               # index into orig_words

    for kind, payload in tagged_groups:
        if kind == "punct":
            continue  # punctuation handled by _reassemble_shavian

        phons = payload
        shavian = translate_to_shavian(phons)
        orig = orig_words[wi].lower().rstrip("'") if wi < len(orig_words) else None
        shavian_words.append(shavian)
        wi += 1

        if orig is None:
            continue

        # Round-trip: reverse the Shavian back to English
        arp_back = shavian_to_arpabet(shavian)
        key = _normalize_phoneme_list(arp_back)
        candidates = reverse_index.get(key, [])
        cands_lower = [c.lower() for c in candidates]

        if orig in cands_lower:
            best = _pick_best_candidate(candidates)
            if best.lower() == orig:
                diagnostics.append(f"  {orig:20s} → {shavian:10s} → {best:20s} ✅")
            else:
                diagnostics.append(f"  {orig:20s} → {shavian:10s} → {best:20s} "
                                   f"✅ (preferred reverse: {best}; "
                                   f"true homophone)")
        elif candidates:
            best = _pick_best_candidate(candidates)
            fixed = False
            if orig in cmu:
                for alt_pron in cmu[orig]:
                    alt_shavian = translate_to_shavian(alt_pron)
                    alt_arp = shavian_to_arpabet(alt_shavian)
                    alt_key = _normalize_phoneme_list(alt_arp)
                    alt_cands = reverse_index.get(alt_key, [])
                    if orig in [c.lower() for c in alt_cands]:
                        shavian_words[-1] = alt_shavian
                        diagnostics.append(
                            f"  {orig:20s} → {alt_shavian:10s} → {orig:20s} "
                            f"🔧 corrected (was {shavian}→{best})")
                        fixed = True
                        break
            if not fixed:
                diagnostics.append(
                    f"  {orig:20s} → {shavian:10s} → {best:20s} "
                    f"⚠ round-trip mismatch")
        else:
            diagnostics.append(
                f"  {orig:20s} → {shavian:10s} → {'(no match)':20s} ⚠")

    # Reassemble with spaces
    full_shavian = _reassemble_shavian(text, shavian_words)
    return full_shavian, translate_to_shavian(phonemes), diagnostics

def _reassemble_shavian(original_text, shavian_words):
    """Re-insert punctuation and spacing from the original text."""
    tokens = re.findall(r"[A-Za-z']+|[^\w\s]+|\s+", original_text)
    result = []
    wi = 0
    for tok in tokens:
        if tok[0].isalpha():
            if wi < len(shavian_words):
                result.append(shavian_words[wi])
                wi += 1
            else:
                result.append(tok)
        else:
            result.append(tok)
    return "".join(result)

# =========================================================================== #
# CLI
# =========================================================================== #
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert between English, ARPABET, and Shavian script."
    )
    parser.add_argument(
        "text", nargs="+",
        help="Text to translate (English or Shavian, depending on mode)."
    )
    parser.add_argument(
        "--from-shavian", action="store_true",
        help="Reverse mode: translate Shavian text back to English."
    )
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip round-trip verification (faster, but less accurate)")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Prompt user to disambiguate true homophones where grammar checks fail")

    args = parser.parse_args()
    text = " ".join(args.text)

    if args.from_shavian:
        # ---- Shavian → English ----
        print("Loading resources …")
        reverse_index = _build_reverse_cmu_index()

        if args.no_verify:
            from g2p_en import G2p as _  # not needed
            english_output, details = "(use verified mode)", []
        else:
            g2p = G2p()
            english_output, details = verified_reverse(
                text, g2p, reverse_index, interactive=args.interactive)

        print(f"\nShavian Input:    {text}")
        print(f"English Output:   {english_output}")
        if details:
            print("\nRound-trip verification:")
            for d in details:
                print(d)
    else:
        # ---- English → Shavian ----
        g2p = G2p()

        if args.no_verify:
            out = g2p(text)
            shavian_output = translate_to_shavian(out)
            print(f"Input: {text}")
            print(f"ARPABET Phonemes: {' '.join(out)}")
            print(f"Shavian Output: {shavian_output}")
        else:
            print("Loading resources …")
            reverse_index = _build_reverse_cmu_index()
            verified_shavian, raw_shavian, diagnostics = verified_forward(
                text, g2p, reverse_index)

            print(f"\nInput:  {text}")
            print(f"Shavian (verified): {verified_shavian}")
            if verified_shavian != raw_shavian:
                print(f"Shavian (raw):      {raw_shavian}")
            print("\nRound-trip verification:")
            for d in diagnostics:
                print(d)
