import sys
import re
import json
import argparse
import urllib.request
import urllib.parse
from collections import Counter, defaultdict
from g2p_en import G2p
from nltk.corpus import cmudict, brown
from nltk import pos_tag as nltk_pos_tag

# =========================================================================== #
# ORTHOGRAPHIC MAPPINGS
# =========================================================================== #
class ShavianOrthography:
    """Encapsulates the mapping logic for OSM (Optimized Shavian Mode)."""

    # Known g2p-en voicing errors: g2p produces DH where CMU says TH.
    # Maps word -> correct CMU-aligned ARPABET override.
    G2P_OVERRIDES = {
        "mouth":  ["M", "AW1", "TH"],
    }

    # Common English clitic suffixes for contraction expansion
    CLITIC_MAP = {
        "'d":  ("would",),   # had/would — ambiguous, default 'would'
        "'ll": ("will",),
        "'ve": ("have",),
        "'re": ("are",),
        "'s":  ("is",),      # is/has — ambiguous, default 'is'
        "'m":  ("am",),
        "'t":  ("not",),     # for n't contractions
    }
    
    ARPABET_TO_SHAVIAN = {
        # Unvoiced Obstruents (Ascenders)
        "P": "\N{SHAVIAN LETTER PEEP}",    # 𐑐
        "T": "\N{RIGHT CEILING}",     # ⌉
        "K": "\N{LEFT CEILING}",    # ⌈
        "F": "\N{CANADIAN SYLLABICS RA}",     # ᕋ
        "TH": "\N{CANADIAN SYLLABICS BLACKFOOT WA}",  # ᖷ
        "S": "\N{CANADIAN SYLLABICS YE}",      # ᔦ
        "SH": "\N{CANADIAN SYLLABICS YI}",   # ᔨ
        "CH": "\N{CANADIAN SYLLABICS TH-CREE THI}", # ᖨ
        "HH": "\N{CANADIAN SYLLABICS BLACKFOOT KE}",   # ᖼ

        # Voiced Obstruents (Descenders)
        "B": "\N{SHAVIAN LETTER FEE}",     # 𐑓
        "D": "\N{RIGHT FLOOR}",    # ⌋
        "G": "\N{LEFT FLOOR}",     # ⌊
        "V": "\N{CANADIAN SYLLABICS WEST-CREE LA}",     # ᕍ
        "DH": "\N{CANADIAN SYLLABICS BLACKFOOT WI}",   # ᖵ
        "Z": "\N{CANADIAN SYLLABICS YO}",     # ᔪ
        "ZH": "\N{CANADIAN SYLLABICS YA}",# ᔭ
        "JH": "\N{CANADIAN SYLLABICS TH-CREE THA}",  # ᖬ

        # Sonorants (X-Height)
        "M": "\N{CANADIAN SYLLABICS SAYISI HE}",    # ᗀ
        "N": "\N{CANADIAN SYLLABICS BLACKFOOT NI}",     # ᖹ
        "NG": "\N{CANADIAN SYLLABICS BLACKFOOT NO}",     # ᖺ
        "L": "\N{SHAVIAN LETTER LOLL}",    # 𐑤
        "R": "\N{SHAVIAN LETTER ROAR}",    # 𐑮
        "W": "\N{CANADIAN SYLLABICS SO}",      # ᓱ
        "Y": "\N{CANADIAN SYLLABICS SA}",     # ᓴ
        
        # Vowels (X-Height)
        "IY": "\N{MINUS SIGN}",    # −
        "IH": "\N{BOX DRAWINGS LIGHT DOWN}",     # ╷
        "EY": "\N{CANADIAN SYLLABICS CARRIER THU}",    # ᗜ
        "EH": "\N{UNION}",    # ∪
        "AE": "\N{INTERSECTION}",    # ∩
        "AA": "\N{LATIN SMALL LETTER O}",     # o
        "AO": "\N{LATIN SMALL LETTER O}",     # o
        "AH": "\N{PHOENICIAN WORD SEPARATOR}",    # 𐤟
        "UH": "\N{LOGICAL AND}",   # ∧
        "UW": "\N{LOGICAL OR}",   # ∨
        "AY": "\N{CANADIAN SYLLABICS CARRIER THO}",    # ᗝ
        "OY": "\N{LATIN CAPITAL LETTER O WITH MACRON}",    # Ō
        "AW": "\N{SHAVIAN LETTER OUT}",    # 𐑬
        "OW": "\N{LATIN CAPITAL LETTER O WITH CIRCUMFLEX}",    # Ô
        "ER": "\N{SHAVIAN LETTER ERR}",    # 𐑻 (Rhotic)
    }

    COMPOUNDS = {
        ("EH", "R"): "\N{SHAVIAN LETTER AIR}",
        ("AO", "R"): "\N{SHAVIAN LETTER OR}",
        ("AA", "R"): "\N{SHAVIAN LETTER ARE}",
        ("IH", "R"): "\N{SHAVIAN LETTER EAR}",
        ("IY", "R"): "\N{SHAVIAN LETTER EAR}",
        ("AH", "R"): "\N{SHAVIAN LETTER ARRAY}",
    }

    SHAVIAN_TO_ARPABET = {v: k for k, v in ARPABET_TO_SHAVIAN.items()}
    SHAVIAN_COMPOUND_TO_ARPABET = {
        "\N{SHAVIAN LETTER AIR}": ("EH", "R"),
        "\N{SHAVIAN LETTER OR}": ("AO", "R"),
        "\N{SHAVIAN LETTER ARE}": ("AA", "R"),
        "\N{SHAVIAN LETTER EAR}": ("IH", "R"),
        "\N{SHAVIAN LETTER ARRAY}": ("AH", "R"),
    }

    MERGER_MAP = {"AO": "AA"}  # Cot-Caught merger handled in phoneme norm
    # TH/DH voicing neutralization: g2p-en sometimes voices final TH.
    # In WCE, this distinction is allophonic (not meaning-bearing) in most
    # positions, so we neutralize DH→TH during reverse lookup to ensure
    # round-trip fidelity.
    VOICING_NEUTRAL = {"DH": "TH"}

    # Dynamically build the set of all OSM characters from the mapping dicts.
    # This replaces the old hardcoded SHAVIAN_RANGE and automatically stays
    # correct whenever glyphs are swapped via the mapping template CSV.
    OSM_CHARS = (
        set(ARPABET_TO_SHAVIAN.values())
        | set(COMPOUNDS.values())
        | set(SHAVIAN_COMPOUND_TO_ARPABET.keys())
    )

    @staticmethod
    def strip_stress(phoneme):
        return re.sub(r'\d+', '', phoneme)

    @classmethod
    def normalize_phonemes(cls, phonemes, neutralize_voicing=False):
        """Applies dialectical normalisation (e.g., cot-caught merger).
        
        If neutralize_voicing is True, also applies TH/DH neutralization
        to improve round-trip lookup success for g2p-en voicing bugs.
        """
        out = []
        for i, p in enumerate(phonemes):
            base = cls.strip_stress(p)
            next_base = cls.strip_stress(phonemes[i + 1]) if i + 1 < len(phonemes) else None
            
            # WCE Mergers
            if base in cls.MERGER_MAP and next_base != "R":
                out.append(cls.MERGER_MAP[base])
            # IY/IH neutralization before R (EAR glyph merger)
            elif base == "IY" and next_base == "R":
                out.append("IH")
            # TH/DH neutralization for g2p-en bugs
            elif neutralize_voicing and base in cls.VOICING_NEUTRAL:
                out.append(cls.VOICING_NEUTRAL[base])
            else:
                out.append(base)
        return tuple(out)

    @classmethod
    def expand_contraction(cls, word):
        """Splits an unknown contraction into (base, clitic_expansion).
        
        Returns (base, expansion) if a known clitic is found, else (word, None).
        Example: "Suzie'd" -> ("Suzie", "would")
        """
        lower = word.lower()
        # Try longest clitic first to avoid matching 've as just 'e
        for clitic in sorted(cls.CLITIC_MAP.keys(), key=len, reverse=True):
            # Handle both straight and curly apostrophes
            for apos in ["'", "\u2019"]:
                suffix = clitic.replace("'", apos)
                if lower.endswith(suffix):
                    base = word[:len(word) - len(suffix)]
                    if base:  # Don't split if base is empty
                        return base, cls.CLITIC_MAP[clitic][0]
        return word, None

    @classmethod
    def to_shavian(cls, phonemes):
        """Forward translation: ARPABET list -> OSM string."""
        shavian, i = [], 0
        while i < len(phonemes):
            p = cls.strip_stress(phonemes[i])
            if i + 1 < len(phonemes):
                p_next = cls.strip_stress(phonemes[i + 1])
                if (p, p_next) in cls.COMPOUNDS:
                    shavian.append(cls.COMPOUNDS[(p, p_next)])
                    i += 2
                    continue
            
            shavian.append(cls.ARPABET_TO_SHAVIAN.get(p, phonemes[i]))
            i += 1
        return "".join(shavian)

    @classmethod
    def to_arpabet(cls, shavian_word):
        """Reverse translation: OSM string -> ARPABET list."""
        phonemes = []
        for ch in shavian_word:
            if ch in cls.SHAVIAN_COMPOUND_TO_ARPABET:
                phonemes.extend(cls.SHAVIAN_COMPOUND_TO_ARPABET[ch])
            elif ch in cls.SHAVIAN_TO_ARPABET:
                phonemes.append(cls.SHAVIAN_TO_ARPABET[ch])
        return phonemes

    @classmethod
    def is_osm(cls, ch):
        """Check whether a character belongs to the OSM glyph set."""
        return ch in cls.OSM_CHARS

    @classmethod
    def tokenize(cls, text):
        """Split text into tagged tokens: ('osm', ...), ('space', ...), ('punct', ...).
        
        Uses the dynamically-built OSM_CHARS set instead of a hardcoded
        Unicode range, so it works correctly regardless of which glyphs
        are currently assigned to phonemes.
        """
        tokens = []
        current = []
        current_type = None

        for ch in text:
            if ch.isspace():
                ch_type = "space"
            elif cls.is_osm(ch):
                ch_type = "osm"
            else:
                ch_type = "punct"

            if ch_type == current_type:
                current.append(ch)
            else:
                if current:
                    tokens.append((current_type, "".join(current)))
                current = [ch]
                current_type = ch_type

        if current:
            tokens.append((current_type, "".join(current)))

        return tokens

# =========================================================================== #
# LINGUISTIC RESOURCES (Lazy Initialization & Caching)
# =========================================================================== #
class PhoneticLexicon:
    """Manages memory and access for heavy NLTK corpora and models."""
    
    _TAG_NORM = {
        'NN': 'n', 'NNS': 'n', 'NP': 'np', 'NPS': 'np', 'NNP': 'np', 'NNPS': 'np',
        'VB': 'v', 'VBD': 'v', 'VBG': 'v', 'VBN': 'v', 'VBP': 'v', 'VBZ': 'v',
        'IN': 'prep', 'CD': 'num', 'DT': 'det', 'AT': 'det',
        'JJ': 'adj', 'JJR': 'adj', 'JJS': 'adj',
        'RB': 'adv', 'RBR': 'adv', 'RBS': 'adv',
        'PRP': 'pron', 'PRP$': 'pron', 'PP$': 'pron', 'UH': 'uh',
    }

    def __init__(self):
        self._freq = None
        self._pos_map = None
        self._reverse_cmu = None
        self._g2p = None
        self._bigrams = None

    @property
    def g2p(self):
        if self._g2p is None:
            self._g2p = G2p()
        return self._g2p

    @property
    def word_freq(self):
        if self._freq is None:
            self._freq = Counter(w.lower() for w in brown.words())
        return self._freq

    @property
    def reverse_cmu(self):
        if self._reverse_cmu is None:
            self._reverse_cmu = defaultdict(list)
            for word, phonemes in cmudict.entries():
                key = ShavianOrthography.normalize_phonemes(phonemes)
                self._reverse_cmu[key].append(word)
        return self._reverse_cmu

    @property
    def bigrams(self):
        """Bigram frequency table from the Brown corpus.
        
        Maps (word_a, word_b) -> count, where word_a immediately precedes
        word_b in the corpus.  Used by the bigram disambiguation pass to
        score how naturally a homophone candidate fits its local context.
        """
        if self._bigrams is None:
            self._bigrams = Counter()
            words = [w.lower() for w in brown.words()]
            for i in range(len(words) - 1):
                self._bigrams[(words[i], words[i + 1])] += 1
        return self._bigrams

    @property
    def word_pos_map(self):
        if self._pos_map is None:
            self._pos_map = defaultdict(Counter)
            for word, tag in brown.tagged_words():
                self._pos_map[word.lower()][self._TAG_NORM.get(tag, tag)] += 1
        return self._pos_map

    def normalize_tag(self, tag):
        return self._TAG_NORM.get(tag, tag)

    def pos_score(self, word, context_tag):
        w = word.lower()
        if w not in self.word_pos_map:
            return 0.0
        counts = self.word_pos_map[w]
        total = sum(counts.values())
        return counts.get(self.normalize_tag(context_tag), 0) / total if total else 0.0

    def pick_highest_frequency(self, candidates):
        clean = [w for w in candidates if w.isalpha()]
        pool = clean if clean else candidates
        return max(pool, key=lambda w: self.word_freq.get(w, 0))

# =========================================================================== #
# DISAMBIGUATION PIPELINE
# =========================================================================== #
class DisambiguationPipeline:
    """Executes the 5-pass verification algorithm."""
    
    def __init__(self, lexicon: PhoneticLexicon, interactive=False):
        self.lexicon = lexicon
        self.interactive = interactive

    def pass_1_round_trip(self, tokens):
        """Pass 1: Salva veritate check via g2p re-encoding."""
        slots, slot_candidates, details = [], [], []

        for kind, tok in tokens:
            if kind != "osm":
                slots.append(("other", tok))
                continue

            arpabet = ShavianOrthography.to_arpabet(tok)
            key = ShavianOrthography.normalize_phonemes(arpabet)
            candidates = self.lexicon.reverse_cmu.get(key, [])

            if not candidates:
                fallback = "/" + " ".join(arpabet) + "/"
                slots.append(("other", fallback))
                details.append(f"  {tok}  →  (no CMU match: {fallback})")
                continue

            unique = sorted(set(candidates))
            pool = [w for w in unique if w.isalpha()] or unique
            ranked = sorted(pool, key=lambda w: self.lexicon.word_freq.get(w, 0), reverse=True)

            chosen = None
            for cand in ranked[:10]:
                re_shavian = ShavianOrthography.to_shavian(self.lexicon.g2p(cand))
                if re_shavian == tok:
                    chosen = cand
                    break

            if chosen is None:
                chosen = ranked[0]
                re_shavian = ShavianOrthography.to_shavian(self.lexicon.g2p(chosen))
                tag = f"⚠ re-encodes as {re_shavian}"
            else:
                tag = "✅"

            slots.append(("word", chosen))
            slot_candidates.append(pool)
            if len(unique) > 1:
                details.append(f"  {tok}  →  {chosen} {tag}  (candidates: {', '.join(unique)})")

        return slots, slot_candidates, details

    def pass_2_languagetool(self, words, slot_candidates):
        """Pass 2: Sentence-level grammar resolution via API."""
        url = "https://api.languagetool.org/v2/check"
        text = ""
        offset_to_idx = {}
        
        for i, w in enumerate(words):
            if i > 0 and w[0].isalpha():
                text += " "
            start_offset = len(text)
            text += w
            for j in range(len(w)):
                offset_to_idx[start_offset + j] = i
                
        try:
            data = urllib.parse.urlencode({'language': 'en-US', 'text': text}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'User-Agent': 'g2p_shavian_tool/1.0'})
            
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
                    for rep in m['replacements']:
                        val = rep['value'].lower()
                        if val in cands:
                            resolutions[idx] = val
                            break
            return resolutions
        except Exception:
            return {} 

    def pass_3_and_4_pos(self, words, slot_candidates):
        """Pass 3 & 4: Local POS tagging and Interactive Fallback."""
        if not words:
            return words, []

        tag_input = [w.capitalize() if w == 'i' else w for w in words]
        tagged = nltk_pos_tag(tag_input)
        refined = list(words)
        notes = []
        choice_cache = {}
        ambiguities = defaultdict(list)
        
        # Identify true ambiguities
        for i, (word_cased, pos) in enumerate(tagged):
            if i >= len(slot_candidates): break
            cands = slot_candidates[i]
            if not cands or len(cands) <= 1: continue
            
            scored = sorted([(c, self.lexicon.pos_score(c, pos)) for c in cands], 
                            key=lambda x: x[1], reverse=True)
            top_score = scored[0][1]
            runner_up_score = scored[1][1] if len(scored) > 1 else 0
            
            if abs(top_score - runner_up_score) < 0.15 or top_score < 0.3:
                cands_tuple = tuple(c for c, _ in scored)
                ambiguities[cands_tuple].append((i, pos))
                
        # Interactive Arbitration (Pass 4)
        if self.interactive:
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

        # POS Resolution
        for i, (word_cased, pos) in enumerate(tagged):
            word = words[i]
            if i >= len(slot_candidates): break
            cands = slot_candidates[i]
            if not cands or len(cands) <= 1: continue

            current_score = self.lexicon.pos_score(word, pos)
            best, best_score = word, current_score

            scored_cands = sorted([(c, self.lexicon.pos_score(c, pos)) for c in cands], 
                                  key=lambda x: x[1], reverse=True)
            cands_tuple = tuple(c for c, _ in scored_cands)
            
            if self.interactive and cands_tuple in choice_cache:
                best = choice_cache[cands_tuple]
                if best != word:
                    refined[i] = best
                    notes.append(f"  USER: '{word}' → '{best}' (context POS={pos}, manually selected)")
                continue

            for c in cands:
                if c == word: continue
                s = self.lexicon.pos_score(c, pos)
                if s > best_score:
                    best, best_score = c, s

            if best != word and current_score < 0.1 and (best_score - current_score) > 0.4:
                # Cross-check: only swap if bigrams don't oppose the change
                import math
                bigrams = self.lexicon.bigrams
                prev_w = words[i - 1].lower() if i > 0 else None
                next_w = words[i + 1].lower() if i + 1 < len(words) else None
                old_bi = 0.0
                new_bi = 0.0
                if prev_w:
                    old_bi += math.log(bigrams.get((prev_w, word), 0) + 1)
                    new_bi += math.log(bigrams.get((prev_w, best), 0) + 1)
                if next_w:
                    old_bi += math.log(bigrams.get((word, next_w), 0) + 1)
                    new_bi += math.log(bigrams.get((best, next_w), 0) + 1)
                
                if new_bi >= old_bi:  # Only swap if bigrams agree or are neutral
                    refined[i] = best
                    notes.append(f"  POS: '{word}' → '{best}' (context POS={pos}, score {current_score:.2f}→{best_score:.2f})")

        return refined, notes

    def pass_bigram_context(self, words, slot_candidates):
        """Pass 2.5: Bigram context scoring.
        
        For each ambiguous word position, scores each homophone candidate
        by how naturally it fits with its left and right neighbors using
        bigram frequencies from the Brown corpus.  This catches cases that
        POS tagging misses (e.g., flour/flower, pear/pair, bee/be) because
        it leverages *which words actually co-occur* rather than just their
        grammatical category.
        
        Scoring formula for candidate c at position i:
          score(c) = log(bigram(word[i-1], c) + 1) + log(bigram(c, word[i+1]) + 1)
        """
        import math
        bigrams = self.lexicon.bigrams
        refined = list(words)
        notes = []
        
        for i, word in enumerate(words):
            if i >= len(slot_candidates):
                break
            cands = slot_candidates[i]
            if not cands or len(cands) <= 1:
                continue
            # Don't override common function words — Pass 1 frequency
            # ranking almost always gets these right, and overriding them
            # with oddball homophones (e.g. "a"→"uh") produces garbage.
            if word.lower() in {'a', 'the', 'of', 'to', 'in', 'on', 'an',
                                'is', 'it', 'or', 'i', 'by', 'at', 'we',
                                'no', 'do', 'so', 'he', 'if', 'as',
                                'and', 'for', 'but', 'not', 'are', 'was',
                                'all', 'her', 'his', 'our', 'has', 'had',
                                'its', 'too', 'new', 'who', 'she'}:
                continue
            
            prev_word = words[i - 1].lower() if i > 0 else None
            next_word = words[i + 1].lower() if i + 1 < len(words) else None
            
            best_cand = word
            best_score = 0.0
            
            # Prefer real words over abbreviations/single-letter entries
            real_cands = [c for c in cands if len(c) > 1 and c.isalpha()]
            score_pool = real_cands if real_cands else cands
            
            for c in score_pool:
                score = 0.0
                if prev_word:
                    score += math.log(bigrams.get((prev_word, c), 0) + 1)
                if next_word:
                    score += math.log(bigrams.get((c, next_word), 0) + 1)
                if score > best_score:
                    best_score = score
                    best_cand = c
            
            if best_cand != word:
                refined[i] = best_cand
                notes.append(
                    f"  BIGRAM: '{word}' → '{best_cand}' "
                    f"(context: {words[i-1] if i > 0 else '∅'} ___ "
                    f"{words[i+1] if i+1 < len(words) else '∅'})")
        
        return refined, notes

    def pass_semantic_context(self, words, slot_candidates):
        """Pass 2.75: Semantic Context via Masked Language Model.
        
        Uses a local HuggingFace transformer (distilbert) to score homophones
        based on the deep semantic meaning of the surrounding sentence.
        """
        # Lazy load the transformer model to avoid slow startup for simple phrases
        if not hasattr(self, '_mlm'):
            try:
                from transformers import pipeline
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    # Use device=-1 for CPU inference
                    self._mlm = pipeline('fill-mask', model='distilbert-base-uncased', device=-1)
            except ImportError:
                return words, ["  SEMANTIC: Skipped (transformers/torch not installed)"]
            except Exception as e:
                return words, [f"  SEMANTIC: Skipped (model load failed: {e})"]

        refined = list(words)
        notes = []
        
        for i, word in enumerate(words):
            if i >= len(slot_candidates):
                break
            cands = slot_candidates[i]
            if not cands or len(cands) <= 1:
                continue
            
            # Don't override common function words (just like in bigram pass)
            if word.lower() in {'a', 'the', 'of', 'to', 'in', 'on', 'an',
                                'is', 'it', 'or', 'i', 'by', 'at', 'we',
                                'no', 'do', 'so', 'he', 'if', 'as',
                                'and', 'for', 'but', 'not', 'are', 'was',
                                'all', 'her', 'his', 'our', 'has', 'had',
                                'its', 'too', 'new', 'who', 'she'}:
                continue
                
            # Filter to real words
            real_cands = [c for c in cands if len(c) > 1 and c.isalpha()]
            score_pool = real_cands if len(real_cands) > 1 else cands
            
            if len(score_pool) <= 1:
                continue
                
            # Build the masked sentence context
            masked_words = list(words)
            masked_words[i] = "[MASK]"
            sentence = " ".join(masked_words)
            
            try:
                # Target filtering allows us to only evaluate the probabilities of our homophones
                results = self._mlm(sentence, targets=score_pool)
                # Pipeline returns a list of dicts. Order is descending by score.
                if isinstance(results, dict):
                    results = [results]
                    
                # Find the highest scoring candidate that is in our pool
                # We do this because sometimes the model tokenizer might return variants
                best_cand = word
                best_score = -1
                for res in results:
                    tok = res["token_str"].strip().lower()
                    if tok in score_pool and res["score"] > best_score:
                        best_score = res["score"]
                        best_cand = tok
                        
                if best_cand != word:
                    refined[i] = best_cand
                    notes.append(f"  SEMANTIC: '{word}' → '{best_cand}' (confidence: {best_score:.2f})")
            except Exception as e:
                notes.append(f"  SEMANTIC ERROR on '{word}': {str(e)}")
                
        return refined, notes

    def execute_reverse(self, shavian_text):
        tokens = ShavianOrthography.tokenize(shavian_text)
        slots, slot_candidates, details = self.pass_1_round_trip(tokens)
        
        word_indices = [i for i, (k, _) in enumerate(slots) if k == "word"]
        words = [slots[i][1] for i in word_indices]

        # Pass 2: LanguageTool grammar check
        lt_resolutions = self.pass_2_languagetool(words, slot_candidates)
        for idx, best in lt_resolutions.items():
            word = words[idx]
            if best != word:
                details.append(f"  API: '{word}' → '{best}' (resolved by LanguageTool)")
                slots[word_indices[idx]] = ("word", best)
                words[idx] = best

        # Pass 2.5/2.75: Context scoring (Semantic Transformer -> Bigram Fallback)
        try:
            import transformers
            context_words, context_notes = self.pass_semantic_context(words, slot_candidates)
        except ImportError:
            context_words, context_notes = self.pass_bigram_context(words, slot_candidates)
            
        for j, idx in enumerate(word_indices):
            if j < len(context_words):
                slots[idx] = ("word", context_words[j])
                words[j] = context_words[j]
        details.extend(context_notes)

        # Pass 3 & 4: POS tagging + Interactive
        refined_words, pos_notes = self.pass_3_and_4_pos(words, slot_candidates)
        for j, idx in enumerate(word_indices):
            slots[idx] = ("word", refined_words[j])
            
        details.extend(pos_notes)
        return "".join(v for _, v in slots), details

# =========================================================================== #
# FORWARD TRANSLATOR
# =========================================================================== #
class Translator:
    def __init__(self, lexicon: PhoneticLexicon):
        self.lexicon = lexicon

    def segment_g2p(self, phonemes):
        groups, cur = [], []
        for p in phonemes:
            if p == ' ':
                if cur: groups.append(cur)
                cur = []
            else:
                cur.append(p)
        if cur: groups.append(cur)
        
        return [("punct", g[0]) if len(g) == 1 and not g[0][0].isalpha() else ("word", g) for g in groups]

    def reassemble(self, original_text, shavian_words):
        tokens = re.findall(r"[A-Za-z\u2019\u2018'']+|[^\w\s]+|\s+", original_text)
        result, wi = [], 0
        for tok in tokens:
            if tok[0].isalpha() and wi < len(shavian_words):
                result.append(shavian_words[wi])
                wi += 1
            else:
                result.append(tok)
        return "".join(result)

    def _translate_word(self, word, cmu):
        """Translate a single English word to Shavian, using overrides if available."""
        lower = word.lower().rstrip("'\u2019")
        # Check for a known g2p-en override first
        if lower in ShavianOrthography.G2P_OVERRIDES:
            return ShavianOrthography.to_shavian(ShavianOrthography.G2P_OVERRIDES[lower])
        # Otherwise use the CMU pronunciation if available (more reliable than g2p)
        if lower in cmu:
            return ShavianOrthography.to_shavian(cmu[lower][0])
        return None  # Fall back to g2p

    def execute_forward(self, text):
        cmu = cmudict.dict()

        # --- Pre-processing: Expand unknown contractions ---
        raw_tokens = re.findall(r"[A-Za-z\u2019\u2018'']+|[^\w\s]+|\s+", text)
        expanded_tokens = []
        for tok in raw_tokens:
            if tok[0].isalpha():
                lower = tok.lower().rstrip("'\u2019")
                if lower not in cmu and ("'" in tok or "\u2019" in tok):
                    base, expansion = ShavianOrthography.expand_contraction(tok)
                    if expansion:
                        expanded_tokens.append(base)
                        expanded_tokens.append(" ")
                        expanded_tokens.append(expansion)
                        continue
            expanded_tokens.append(tok)

        expanded_text = "".join(expanded_tokens)
        phonemes = self.lexicon.g2p(expanded_text)
        tagged_groups = self.segment_g2p(phonemes)

        orig_tokens = re.findall(r"[A-Za-z\u2019\u2018'']+|[^\w\s]+", expanded_text)
        orig_words = [t for t in orig_tokens if t[0].isalpha()]

        shavian_words, diagnostics, wi = [], [], 0

        for kind, payload in tagged_groups:
            if kind == "punct":
                continue

            orig = orig_words[wi].lower().rstrip("'\u2019") if wi < len(orig_words) else None

            # Try CMU/override-based translation first (more accurate)
            cmu_shavian = self._translate_word(orig, cmu) if orig else None
            g2p_shavian = ShavianOrthography.to_shavian(payload)
            shavian = cmu_shavian if cmu_shavian else g2p_shavian

            shavian_words.append(shavian)
            wi += 1

            if orig is None:
                continue

            # --- Round-trip verification ---
            arp_back = ShavianOrthography.to_arpabet(shavian)
            key = ShavianOrthography.normalize_phonemes(arp_back)
            # Also try with voicing neutralization for robustness
            key_neutral = ShavianOrthography.normalize_phonemes(arp_back, neutralize_voicing=True)
            candidates = self.lexicon.reverse_cmu.get(key, []) or self.lexicon.reverse_cmu.get(key_neutral, [])
            cands_lower = [c.lower() for c in candidates]

            if orig in cands_lower:
                best = self.lexicon.pick_highest_frequency(candidates)
                if best.lower() == orig:
                    diagnostics.append(f"  {orig:20s} -> {shavian:10s} -> {best:20s} OK")
                else:
                    diagnostics.append(f"  {orig:20s} -> {shavian:10s} -> {best:20s} OK (preferred reverse: {best}; true homophone)")
            elif candidates:
                best = self.lexicon.pick_highest_frequency(candidates)
                fixed = False
                if orig in cmu:
                    for alt_pron in cmu[orig]:
                        alt_shavian = ShavianOrthography.to_shavian(alt_pron)
                        alt_arp = ShavianOrthography.to_arpabet(alt_shavian)
                        alt_key = ShavianOrthography.normalize_phonemes(alt_arp)
                        alt_cands = self.lexicon.reverse_cmu.get(alt_key, [])
                        if orig in [c.lower() for c in alt_cands]:
                            shavian_words[-1] = alt_shavian
                            diagnostics.append(f"  {orig:20s} -> {alt_shavian:10s} -> {orig:20s} FIXED (was {shavian}->{best})")
                            fixed = True
                            break
                if not fixed:
                    diagnostics.append(f"  {orig:20s} -> {shavian:10s} -> {best:20s} WARN round-trip mismatch")
            else:
                diagnostics.append(f"  {orig:20s} -> {shavian:10s} -> {'(no match)':20s} WARN")

        full_shavian = self.reassemble(expanded_text, shavian_words)
        return full_shavian, ShavianOrthography.to_shavian(phonemes), diagnostics

# =========================================================================== #
# CLI ENTRYPOINT
# =========================================================================== #
def main():
    parser = argparse.ArgumentParser(description="Convert between English, ARPABET, and Shavian script.")
    parser.add_argument("text", nargs="+", help="Text to translate.")
    parser.add_argument("--from-shavian", action="store_true", help="Reverse mode: translate Shavian text back to English.")
    parser.add_argument("--no-verify", action="store_true", help="Skip round-trip verification.")
    parser.add_argument("-i", "--interactive", action="store_true", help="Prompt user to disambiguate true homophones.")

    args = parser.parse_args()
    text = " ".join(args.text)

    if args.no_verify:
        print("Note: Unverified mode bypasses linguistic pipelines.")
        lexicon = PhoneticLexicon()
        if args.from_shavian:
            print("Reverse unverified mode is undefined. Please run with verification.")
        else:
            out = lexicon.g2p(text)
            print(f"Input: {text}\nARPABET: {' '.join(out)}\nShavian: {ShavianOrthography.to_shavian(out)}")
        return

    print("Loading linguistic resources ...")
    lexicon = PhoneticLexicon()

    if args.from_shavian:
        pipeline = DisambiguationPipeline(lexicon, interactive=args.interactive)
        english_output, details = pipeline.execute_reverse(text)
        print(f"\nShavian Input:    {text}")
        print(f"English Output:   {english_output}")
        if details:
            print("\nVerification Pipeline Diagnostics:")
            for d in details:
                print(d)
    else:
        translator = Translator(lexicon)
        verified_shavian, raw_shavian, diagnostics = translator.execute_forward(text)
        print(f"\nInput:  {text}")
        print(f"Shavian (verified): {verified_shavian}")
        if verified_shavian != raw_shavian:
            print(f"Shavian (raw):      {raw_shavian}")
        print("\nVerification Pipeline Diagnostics:")
        for d in diagnostics:
            print(d)

if __name__ == "__main__":
    main()
