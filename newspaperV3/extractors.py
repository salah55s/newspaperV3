# -*- coding: utf-8 -*-
"""
Newspaper uses much of python-goose's extraction code. View their license:
https://github.com/codelucas/newspaper/blob/master/GOOSE-LICENSE.txt

Keep all html page extraction code within this file. Abstract any
lxml or soup parsing code in the parsers.py file!
"""
__title__ = 'newspaper'
__author__ = 'Lucas Ou-Yang'
__license__ = 'MIT'
__copyright__ = 'Copyright 2014, Lucas Ou-Yang'

import copy
import logging
import re
from collections import defaultdict

from dateutil.parser import parse as date_parser
from tldextract import tldextract
from urllib.parse import urljoin, urlparse, urlunparse

from . import urls
from .utils import StringReplacement, StringSplitter

import dateparser
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

MOTLEY_REPLACEMENT = StringReplacement("&#65533;", "")
ESCAPED_FRAGMENT_REPLACEMENT = StringReplacement(
    "#!", "?_escaped_fragment_=")
TITLE_REPLACEMENTS = StringReplacement("&raquo;", "»")
PIPE_SPLITTER = StringSplitter("\\|")
DASH_SPLITTER = StringSplitter(" - ")
UNDERSCORE_SPLITTER = StringSplitter("_")
SLASH_SPLITTER = StringSplitter("/")
ARROWS_SPLITTER = StringSplitter(" » ")
COLON_SPLITTER = StringSplitter(":")
SPACE_SPLITTER = StringSplitter(' ')
NO_STRINGS = set()
A_REL_TAG_SELECTOR = "a[rel=tag]"
A_HREF_TAG_SELECTOR = ("a[href*='/tag/'], a[href*='/tags/'], "
                       "a[href*='/topic/'], a[href*='?keyword=']")
RE_LANG = r'^[A-Za-z]{2}$'

good_paths = ['story', 'article', 'feature', 'featured', 'slides',
              'slideshow', 'gallery', 'news', 'video', 'media',
              'v', 'radio', 'press']
bad_chunks = ['careers', 'contact', 'about', 'faq', 'terms', 'privacy',
              'advert', 'preferences', 'feedback', 'info', 'browse', 'howto',
              'account', 'subscribe', 'donate', 'shop', 'admin']
bad_domains = ['amazon', 'doubleclick', 'twitter']




def normalize_arabic(text):
    """Normalizes Arabic text to a consistent form for matching."""
    if not text:
        return text
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'[ى]', 'ي', text)
    text = re.sub(r'[ة]', 'ه', text)
    text = re.sub(r'[\u064B-\u0652]', '', text) # Remove diacritics
    return text

# A simplified dictionary containing ONLY month names.
# This makes our Trie a highly specialized and fast month-finder.
# We include multiple sets for Arabic to maximize coverage.
DATE_KEYWORDS = {
    'en': ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December',
           'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    'es': ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
           'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
    'de': ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
           'Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'],
    'fr': ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
           'janv', 'févr', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sept', 'oct', 'nov', 'déc'],
    'ar': [ # Gregorian and Levantine months (pre-normalized)
        'يناير', 'فبراير', 'مارس', 'ابريل', 'مايو', 'يونيو', 'يوليو', 'اغسطس', 'سبتمبر', 'اكتوبر', 'نوفمبر', 'ديسمبر'
    ]
}

DATE_CLEANING_REGEXES = {
    'en': re.compile(r'^(Published|Updated|Posted on|Last updated|on)\s*[:]?\s*', re.IGNORECASE),
    'es': re.compile(r'^(Publicado|Actualizado)\s*(el)?\s*[:]?\s*', re.IGNORECASE),
    'de': re.compile(r'^(Veröffentlicht|Aktualisiert)\s*(am)?\s*[:]?\s*', re.IGNORECASE),
    'fr': re.compile(r'^(Publié|Mise à jour)\s*(le)?\s*[:]?\s*', re.IGNORECASE),
    'ar': re.compile(r'^(نشر في|تاريخ النشر|تحديث)\s*[:]?\s*', re.IGNORECASE),
}

# In newspaperV3/extractors.py

PUBLICATION_KEYWORDS = [
    # English (and common variants)
    'published', 'publication', 'posted on', 'updated', 'last updated',
    'authored', 'written by', 'on:', 'at:', 'date:', 'by:',

    # Arabic
    'نشر في', 'تاريخ النشر', 'تحديث', 'مشاركة', 'بتاريخ',

    # Spanish
    'publicado', 'actualizado', 'fecha',

    # French
    'publié le', 'mise à jour', 'date de publication',

    # German
    'veröffentlicht', 'aktualisiert', 'datum',

    # Portuguese
    'publicado em', 'atualizado em',

    # Italian
    'pubblicato il', 'aggiornato il',

    # Russian
    'опубликовано', 'обновлено', 'дата',

    # Turkish
    'yayınlanma', 'güncellenme', 'tarih',

    # Dutch
    'gepubliceerd op', 'bijgewerkt op',

    # Swedish
    'publicerad', 'uppdaterad',
    
    # Norwegian
    'publisert', 'oppdatert',
    
    # Danish
    'udgivet', 'opdateret',
    
    # Finnish
    'julkaistu', 'päivitetty',
    
    # Japanese
    '公開日', '更新日', # Kōkai-bi (Publication date), Kōshin-bi (Update date)
    
    # Chinese (Simplified)
    '发布日期', '更新日期', '发表于', # Fābù rìqí, Gēngxīn rìqí, Fābiǎo yú
]

class TrieNode:
    """A node in the Trie structure for keyword searching."""
    def __init__(self):
        self.children = defaultdict(TrieNode)
        self.is_end_of_word = False

class DateFinder:
    """A helper class to find month names in text using a Trie."""
    def __init__(self, keywords_dict):
        self.root = TrieNode()
        self._build_trie(keywords_dict)

    def _build_trie(self, keywords_dict):
        for lang, words in keywords_dict.items():
            for word in words:
                # All keywords are stored in lowercase. Arabic keywords are already normalized.
                processed_word = word.lower()
                node = self.root
                for char in processed_word:
                    node = node.children[char]
                node.is_end_of_word = True

    def contains_month(self, text):
        """
        Efficiently checks if any month name exists in the given text.
        """
        # Normalize the input text to match how keywords are stored in the Trie.
        normalized_text = normalize_arabic(text.lower())
        
        for i in range(len(normalized_text)):
            node = self.root
            for j in range(i, len(normalized_text)):
                char = normalized_text[j]
                if char not in node.children:
                    break
                node = node.children[char]
                if node.is_end_of_word:
                    # Found a keyword. We don't need to know which one, just that it exists.
                    return True
        return False
    



# From original file, kept for compatibility
MOTLEY_REPLACEMENT = StringReplacement("&#65533;", "")
ESCAPED_FRAGMENT_REPLACEMENT = StringReplacement("#!", "?_escaped_fragment_=")
TITLE_REPLACEMENTS = StringReplacement("&raquo;", "»")
PIPE_SPLITTER = StringSplitter(r"\|")
DASH_SPLITTER = StringSplitter(" - ")
UNDERSCORE_SPLITTER = StringSplitter("_")
SLASH_SPLITTER = StringSplitter("/")
ARROWS_SPLITTER = StringSplitter(" » ")
COLON_SPLITTER = StringSplitter(":")
SPACE_SPLITTER = StringSplitter(' ')
NO_STRINGS = set()
A_REL_TAG_SELECTOR = "a[rel=tag]"
A_HREF_TAG_SELECTOR = ("a[href*='/tag/'], a[href*='/tags/'], "
                       "a[href*='/topic/'], a[href*='?keyword=']")
RE_LANG = r'^[A-Za-z]{2}$'



class ContentExtractor(object):
    def __init__(self, config):
        self.config = config
        self.parser = self.config.get_parser()
        self.language = config.language
        self.stopwords_class = config.stopwords_class
        self.date_finder = DateFinder(DATE_KEYWORDS)

    def _extract_best_date_string(self, text):
        """
        A creative pipeline to extract the most likely date string from a candidate text.
        """
        # 1. Structural check: Date in parentheses
        match = re.search(r'\(([^)]+\d{4}[^)]+)\)', text)
        if match:
            return match.group(1).strip()

        # 2. Language-aware prefix stripping
        cleaned_text = text
        for lang_regex in DATE_CLEANING_REGEXES.values():
            cleaned_text = lang_regex.sub('', cleaned_text)
        
        # 3. Comprehensive text-based pattern matching (Day Month Year)
        # This regex looks for a full date with a month name.
        text_date_pattern = re.compile(
            r"""
            (?:
                \b\d{1,2}[-\s/.,th|st|nd|rd]*   # Optional day
                \b(?:[a-zA-Z\u0621-\u064A]{3,})\b # Month name (Eng or Ara)
                (?:[-\s/.,|]*)                  # Separator
                \d{1,2}[-\s/.,th|st|nd|rd]*      # Day or Year
                (?:[-\s/.,|]*)                  # Separator
                \b\d{2,4}\b                     # Year
            )
            """, re.VERBOSE | re.IGNORECASE)
        
        match = text_date_pattern.search(cleaned_text)
        if match:
            return match.group(0).strip()
            
        # 4. **CRUCIAL ADDITION**: Numeric-only pattern matching
        # This will find YYYY-MM-DD or similar formats embedded in text.
        numeric_date_pattern = re.compile(
            r"""
            (
                \b(19|20)\d{2}                     # Year (YYYY)
                [-/.]                             # Separator
                (0?[1-9]|1[0-2])                  # Month (MM)
                [-/.]                             # Separator
                (0?[1-9]|[12][0-9]|3[01])          # Day (DD)
                (?:[\s|]*                          # Optional space or pipe
                (?:[0-2]?\d:[0-5]\d)?)?            # Optional time (HH:MM)
            )
            """, re.VERBOSE)
            
        match = numeric_date_pattern.search(cleaned_text)
        if match:
            return match.group(0).strip()

        # 5. Fallback to return the partially cleaned text if no specific pattern is found.
        return cleaned_text.strip()
    def update_language(self, meta_lang):
        """Required to be called before the extraction process in some
        cases because the stopwords_class has to set incase the lang
        is not latin based
        """
        if meta_lang:
            self.language = meta_lang
            self.stopwords_class = \
                self.config.get_stopwords_class(meta_lang)

    def get_authors(self, doc):
        """Fetch the authors of the article, return as a list
        Only works for english articles
        """
        _digits = re.compile(r'\d')

        def contains_digits(d):
            return bool(_digits.search(d))

        def uniqify_list(lst):
            """Remove duplicates from provided list but maintain original order.
              Derived from http://www.peterbe.com/plog/uniqifiers-benchmark
            """
            seen = {}
            result = []
            for item in lst:
                if item.lower() in seen:
                    continue
                seen[item.lower()] = 1
                result.append(item.title())
            return result

        def parse_byline(search_str):
            """
            Takes a candidate line of html or text and
            extracts out the name(s) in list form:
            >>> parse_byline('<div>By: <strong>Lucas Ou-Yang</strong>,<strong>Alex Smith</strong></div>')
            ['Lucas Ou-Yang', 'Alex Smith']
            """
            # Remove HTML boilerplate
            search_str = re.sub('<[^<]+?>', '', search_str)

            # Remove original By statement
            search_str = re.sub(r'[bB][yY][\:\s]|[fF]rom[\:\s]', '', search_str)

            search_str = search_str.strip()

            # Chunk the line by non alphanumeric tokens (few name exceptions)
            # >>> re.split("[^\w\'\-\.]", "Tyler G. Jones, Lucas Ou, Dean O'Brian and Ronald")
            # ['Tyler', 'G.', 'Jones', '', 'Lucas', 'Ou', '', 'Dean', "O'Brian", 'and', 'Ronald']
            name_tokens = re.split(r"[^\w\'\-\.]", search_str)
            name_tokens = [s.strip() for s in name_tokens]

            _authors = []
            # List of first, last name tokens
            curname = []
            delimiters = ['and', ',', '']

            for token in name_tokens:
                if token in delimiters:
                    if len(curname) > 0:
                        _authors.append(' '.join(curname))
                        curname = []

                elif not contains_digits(token):
                    curname.append(token)

            # One last check at end
            valid_name = (len(curname) >= 2)
            if valid_name:
                _authors.append(' '.join(curname))

            return _authors

        # Try 1: Search popular author tags for authors

        ATTRS = ['name', 'rel', 'itemprop', 'class', 'id']
        VALS = ['author', 'byline', 'dc.creator', 'byl']
        matches = []
        authors = []

        for attr in ATTRS:
            for val in VALS:
                # found = doc.xpath('//*[@%s="%s"]' % (attr, val))
                found = self.parser.getElementsByTag(doc, attr=attr, value=val)
                matches.extend(found)

        for match in matches:
            content = ''
            if match.tag == 'meta':
                mm = match.xpath('@content')
                if len(mm) > 0:
                    content = mm[0]
            else:
                content = match.text_content() or ''
            if len(content) > 0:
                authors.extend(parse_byline(content))

        return uniqify_list(authors)

        # TODO Method 2: Search raw html for a by-line
        # match = re.search('By[\: ].*\\n|From[\: ].*\\n', html)
        # try:
        #    # Don't let zone be too long
        #    line = match.group(0)[:100]
        #    authors = parse_byline(line)
        # except:
        #    return [] # Failed to find anything
        # return authors

    def get_publishing_date(self, url, original_doc, top_node=None, source_doc=None, debug=False):
        """
        Final, robust, tiered strategy for finding the publication date.
        - Tiers 1 & 2 use the original, untouched document for maximum reliability.
        - Heuristic tiers use distance-based scoring relative to top_node.
        [DEBUG VERSION]
        """
        import re
        from datetime import datetime, timedelta
        if debug: print("\n[DEBUG] --- Starting get_publishing_date ---")
        now = datetime.now()

        def parse_and_validate(date_str, from_heuristic=False, from_url=False):
            if not date_str: return None
            
            # Import required modules at function start
            import re
            import dateparser
            from datetime import datetime, timedelta
            
            try:
                # Handle common URL date formats explicitly
                if from_url:
                    # Clean up URL date string
                    clean_url_date = date_str.strip('/')
                    
                    # Try common URL patterns first
                    url_patterns = [
                        r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',  # YYYY/MM/DD or YYYY-MM-DD
                        r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',  # MM/DD/YYYY or DD/MM/YYYY
                    ]
                    
                    for pattern in url_patterns:
                        match = re.search(pattern, clean_url_date)
                        if match:
                            g1, g2, g3 = match.groups()
                            
                            # If first group is 4 digits, it's likely YYYY/MM/DD
                            if len(g1) == 4:
                                try:
                                    year, month, day = int(g1), int(g2), int(g3)
                                    if 1 <= month <= 12 and 1 <= day <= 31:
                                        from datetime import datetime as dt_class
                                        dt = dt_class(year, month, day)
                                        if debug: print(f"  [DEBUG] URL Pattern Match: {clean_url_date} → {dt}")
                                        return dt
                                except (ValueError, ImportError):
                                    pass
                            
                            # Otherwise try DD/MM/YYYY or MM/DD/YYYY
                            else:
                                # Try DD/MM/YYYY first (common in many regions)
                                try:
                                    day, month, year = int(g1), int(g2), int(g3)
                                    if 1 <= month <= 12 and 1 <= day <= 31:
                                        from datetime import datetime as dt_class
                                        dt = dt_class(year, month, day)
                                        if debug: print(f"  [DEBUG] URL Pattern Match (DD/MM/YYYY): {clean_url_date} → {dt}")
                                        return dt
                                except (ValueError, ImportError):
                                    pass
                                    
                                # Fall back to MM/DD/YYYY
                                try:
                                    month, day, year = int(g1), int(g2), int(g3)
                                    if 1 <= month <= 12 and 1 <= day <= 31:
                                        from datetime import datetime as dt_class
                                        dt = dt_class(year, month, day)
                                        if debug: print(f"  [DEBUG] URL Pattern Match (MM/DD/YYYY): {clean_url_date} → {dt}")
                                        return dt
                                except (ValueError, ImportError):
                                    pass
                
                # Detect ISO format dates and handle them correctly
                # Look for ISO dates in the original string first
                iso_pattern = r'\b(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?\b'
                
                # Try ISO format in original string first
                iso_match = re.search(iso_pattern, date_str)
                
                if iso_match:
                    # Handle ISO format explicitly to avoid DATE_ORDER confusion
                    year, month, day, hour, minute, second = iso_match.groups()
                    try:
                        year, month, day = int(year), int(month), int(day)
                        hour = int(hour) if hour else 0
                        minute = int(minute) if minute else 0
                        second = int(second) if second else 0
                        
                        if 1 <= month <= 12 and 1 <= day <= 31:
                            from datetime import datetime as dt_class
                            dt = dt_class(year, month, day, hour, minute, second)
                            if debug: print(f"  [DEBUG] ISO Format Match: {iso_match.group(0)} → {dt}")
                            
                            # Handle timezone comparison
                            if dt.tzinfo is not None and now.tzinfo is None:
                                dt_naive = dt.replace(tzinfo=None)
                                comparison_time = now
                            elif dt.tzinfo is None and now.tzinfo is not None:
                                dt_naive = dt
                                comparison_time = now.replace(tzinfo=None)
                            else:
                                dt_naive = dt
                                comparison_time = now
                            
                            future_threshold = timedelta(hours=24) if from_heuristic else timedelta(days=7)
                            
                            if dt_naive > comparison_time + future_threshold:
                                if debug: print(f"  [DEBUG] REJECTED (Future Date): Parsed '{date_str}' to {dt} (threshold: {future_threshold})")
                                return None
                            
                            if debug: print(f"  [DEBUG] ACCEPTED: Parsed '{date_str}' to {dt}")
                            return dt
                            
                    except (ValueError, ImportError):
                        if debug: print(f"  [DEBUG] ISO Format parsing failed, falling back to dateparser")
                        pass
                
                # Try parsing with original string first
                parsing_attempts = [date_str]
                
                # Only add cleaned version if heuristic and original fails
                if from_heuristic:
                    best_substring = self._extract_best_date_string(date_str)
                    if best_substring != date_str and best_substring:
                        parsing_attempts.append(best_substring)
                        if debug: print(f"  [DEBUG PARSER] Will try cleaned string '{best_substring}' if original fails")
                
                if debug: print(f"  [DEBUG] Parsing attempts: {parsing_attempts}")
                
                # Try each parsing attempt
                for attempt_str in parsing_attempts:
                    if not attempt_str:
                        continue
                        
                    # Clean timezone suffixes that confuse dateparser
                    clean_attempt = attempt_str
                    # Remove common problematic timezone patterns
                    timezone_patterns = [
                        r'\s*-\s*GMT\s*\([^)]+\)\s*',  # - GMT (+3 )
                        r'\s*GMT\s*[+-]\d{1,2}\s*',    # GMT+3
                        r'\s*UTC\s*[+-]\d{1,2}\s*',    # UTC+3
                        r'\s*\([^)]*GMT[^)]*\)\s*',    # (GMT+3)
                    ]
                    for pattern in timezone_patterns:
                        clean_attempt = re.sub(pattern, '', clean_attempt).strip()
                    
                    if debug and clean_attempt != attempt_str:
                        print(f"  [DEBUG] Cleaned timezone: '{attempt_str}' → '{clean_attempt}'")
                        
                    # Fall back to dateparser with appropriate settings
                    if from_url:
                        # URLs typically use YYYY/MM/DD or YYYY-MM-DD format
                        settings = {'DATE_ORDER': 'YMD'}
                    else:
                        # Improved date order detection for text dates
                        if re.search(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', clean_attempt):
                            # ISO format: YYYY-MM-DD, YYYY/MM/DD, or YYYY.MM.DD
                            settings = {'DATE_ORDER': 'YMD'}
                            if debug: print(f"  [DEBUG] Detected ISO format (YMD) in: {clean_attempt}")
                        elif re.search(r'([1-9]|1[0-2])/([1-9]|[12][0-9]|3[01])/\d{4}', clean_attempt):
                            # American format: M/D/YYYY or MM/DD/YYYY (month 1-12, day 1-31)
                            settings = {'DATE_ORDER': 'MDY'}
                            if debug: print(f"  [DEBUG] Detected American format (MDY) in: {clean_attempt}")
                        elif re.search(r'([1-9]|[12][0-9]|3[01])/([1-9]|1[0-2])/\d{4}', clean_attempt):
                            # European format: D/M/YYYY or DD/MM/YYYY (day 1-31, month 1-12)  
                            settings = {'DATE_ORDER': 'DMY'}
                            if debug: print(f"  [DEBUG] Detected European format (DMY) in: {clean_attempt}")
                        else:
                            # Default to MDY for ambiguous cases (common in web content)
                            settings = {'DATE_ORDER': 'MDY'}
                            if debug: print(f"  [DEBUG] Using default MDY format for: {clean_attempt}")

                    if debug: print(f"  [DEBUG] Trying dateparser with '{clean_attempt}' using {settings}")
                    dt = dateparser.parse(clean_attempt, settings=settings)
                    
                    if not dt:
                        if debug: print(f"  [DEBUG] dateparser failed to parse: '{clean_attempt}'")
                        continue  # Try next parsing attempt
                    
                    if dt:
                        if debug: print(f"  [DEBUG] dateparser result: {dt}")
                        
                        # Handle timezone-aware vs naive datetime comparison
                        if dt.tzinfo is not None and now.tzinfo is None:
                            # Convert timezone-aware dt to naive for comparison
                            dt_naive = dt.replace(tzinfo=None)
                            comparison_time = now
                            if debug: print(f"  [DEBUG] Converted timezone-aware to naive: {dt_naive}")
                        elif dt.tzinfo is None and now.tzinfo is not None:
                            # Convert naive dt to timezone-aware using UTC
                            dt_naive = dt
                            comparison_time = now.replace(tzinfo=None)
                            if debug: print(f"  [DEBUG] Using naive datetime for comparison")
                        else:
                            # Both are same type (both naive or both aware)
                            dt_naive = dt
                            comparison_time = now
                            if debug: print(f"  [DEBUG] Same timezone types")
                        
                        # More lenient future date check for metadata
                        future_threshold = timedelta(hours=24) if from_heuristic else timedelta(days=7)
                        
                        if debug: print(f"  [DEBUG] Comparing {dt_naive} vs {comparison_time} (threshold: {future_threshold})")
                        
                        if dt_naive > comparison_time + future_threshold:
                            if debug: print(f"  [DEBUG] REJECTED (Future Date): Parsed '{attempt_str}' to {dt} (threshold: {future_threshold})")
                            continue  # Try next parsing attempt
                            
                        if debug: print(f"  [DEBUG] ACCEPTED: Parsed '{attempt_str}' to {dt}")
                        return dt
                
                return None
            except Exception as e:
                if debug: print(f"  [DEBUG] PARSING ERROR: {e}")
                return None
        def find_corresponding_node(source_node, source_doc, target_doc):
            """Find corresponding node using multiple strategies."""
            if source_node is None:
                return None
                
            try:
                source_tree = source_doc.getroottree()
                source_xpath = source_tree.getpath(source_node)
                if debug: print(f"[DEBUG] INFO: Source node XPath: '{source_xpath}'")
                
                target_tree = target_doc.getroottree()
                
                # Strategy 1: Try exact XPath match
                corresponding_nodes = target_tree.xpath(source_xpath)
                if corresponding_nodes:
                    corresponding_node = corresponding_nodes[0]
                    target_xpath = target_tree.getpath(corresponding_node)
                    if debug: print(f"[DEBUG] INFO: Found corresponding node using exact XPath: '{target_xpath}'")
                    return corresponding_node
                
                if debug: print(f"[DEBUG] INFO: Exact XPath failed, trying alternative strategies...")
                
                # Strategy 2: Try flexible XPath (remove specific indices)
                simplified_xpath = re.sub(r'\[\d+\]', '', source_xpath)
                if simplified_xpath != source_xpath:
                    flex_nodes = target_tree.xpath(simplified_xpath)
                    if flex_nodes:
                        target_xpath = target_tree.getpath(flex_nodes[0])
                        if debug: print(f"[DEBUG] INFO: Found corresponding node using flexible XPath: '{target_xpath}'")
                        return flex_nodes[0]
                
                if debug: print(f"[DEBUG] WARNING: All mapping strategies failed")
                return None
                    
            except Exception as e:
                if debug: print(f"[DEBUG] ERROR: Failed to find corresponding node. Error: {e}")
                return None

        def calculate_dom_distance(node1, node2):
            """
            Calculate the DOM distance between two nodes.
            Returns a distance score where lower = closer.
            """
            try:
                if node1 is None or node2 is None:
                    return float('inf')
                
                # Get paths to both nodes
                tree = node1.getroottree()
                path1 = tree.getpath(node1)
                path2 = tree.getpath(node2)
                
                # Split paths into components
                parts1 = [p for p in path1.split('/') if p]
                parts2 = [p for p in path2.split('/') if p]
                
                # Find common ancestor length
                common_length = 0
                for i in range(min(len(parts1), len(parts2))):
                    if parts1[i] == parts2[i]:
                        common_length += 1
                    else:
                        break
                
                # Distance = steps from common ancestor to node1 + steps to node2
                distance = (len(parts1) - common_length) + (len(parts2) - common_length)
                
                return distance
                
            except Exception as e:
                if debug: print(f"  [DEBUG] Distance calculation failed: {e}")
                return float('inf')

        def calculate_proximity_score(candidate_node, reference_node, max_distance=10):
            """
            Calculate proximity score based on DOM distance.
            Closer nodes get higher scores.
            """
            if reference_node is None:
                return 0
            
            distance = calculate_dom_distance(candidate_node, reference_node)
            
            if distance == float('inf'):
                return 0
            
            # Convert distance to score: closer = higher score
            # Max score of 100 for distance 0, decreasing to 0 for max_distance
            if distance >= max_distance:
                return 0
            
            score = int(100 * (1 - distance / max_distance))
            return max(0, score)

        def is_likely_date_text(text):
            """
            STRICT date detection to avoid scoring random text as dates.
            Requires multiple indicators or very specific patterns.
            """
            if not text or len(text) < 3:
                return False
                
            text_lower = text.lower().strip()
            
            # If text is too long, it's probably not a date
            if len(text) > 150:
                return False
            
            # STRICT PATTERNS: Must match one of these specific patterns
            strict_patterns = [
                # Clear date formats with numbers
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # 12/31/2025
                r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',    # 2025/12/31
                r'\b\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b',
                r'\b\d{1,2}\s+(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s*,?\s*\d{4}\b',
                r'\b\d{1,2}\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}\b',
                
                # Time patterns
                r'\b([01]?\d|2[0-3]):[0-5]\d\b',       # HH:MM
                r'\b\d{1,2}:\d{2}\s*(am|pm|ص|م)\b',    # 12:30 PM
                
                # Day + Date patterns
                r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b',
                r'\b(الاثنين|الثلاثاء|الأربعاء|الخميس|الجمعة|السبت|الأحد)\s*\d{1,2}\s*(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s*,?\s*\d{4}\b',
                
                # ISO format dates
                r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',
                
                # Published/Updated with date
                r'\b(published|updated|posted|created|تاريخ|نشر|محدث)\s*:?\s*\d',
            ]
            
            # Check strict patterns first
            for pattern in strict_patterns:
                if re.search(pattern, text_lower):
                    return True
            
            # RELAXED CHECK: Only if text is short and contains strong date indicators
            if len(text) <= 50:  # Only for short text
                # Must contain a year
                if not re.search(r'\b(19|20)\d{2}\b', text):
                    return False
                    
                # Must contain month or day name
                date_words = [
                    # English
                    'january', 'february', 'march', 'april', 'may', 'june',
                    'july', 'august', 'september', 'october', 'november', 'december',
                    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
                    
                    # Arabic - be more specific
                    'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
                    'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر',
                    'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد',
                ]
                
                has_date_word = any(word in text_lower for word in date_words)
                if has_date_word:
                    return True
            
            return False

        # Tiers 1 & 2: High-confidence structured data
        if debug: 
            print("[DEBUG TIER 1 & 2] Checking URL and Metadata...")
        date_match = re.search(urls.STRICT_DATE_REGEX, url)
        if date_match:
            dt = parse_and_validate(date_match.group(0), from_heuristic=False, from_url=True)
            if dt: 
                if debug: print(f"[DEBUG] SUCCESS (URL): {dt}")
                return dt

        # Metadata tags checking...
        PUBLISH_DATE_TAGS = [
            {'attribute': 'property', 'value': 'article:published_time'},
            {'attribute': 'itemprop', 'value': 'datePublished'},
            {'attribute': 'name', 'value': 'pubdate'},
            {'attribute': 'pubdate', 'value': 'pubdate'},
            {'attribute': 'name', 'value': 'published_time'},
            {'attribute': 'name', 'value': 'publish_date'},
            {'attribute': 'property', 'value': 'og:published_time'},
            {'attribute': 'name', 'value': 'date'},
            {'attribute': 'name', 'value': 'Date'},
            {'attribute': 'name', 'value': 'DC.date.issued'},
            {'attribute': 'name', 'value': 'dcterms.created'},
            {'attribute': 'name', 'value': 'OriginalPublicationDate'},
            {'attribute': 'name', 'value': 'sailthru.date'},
            {'attribute': 'name', 'value': 'article_date_original'},
            {'attribute': 'name', 'value': 'publication_date'},
            {'attribute': 'name', 'value': 'PublishDate'},
            {'attribute': 'name', 'value': 'datePublished'},
            {'attribute': 'property', 'value': 'rnews:datePublished'},
            {'attribute': 'name', 'value': 'datePublished'},
            {'attribute': 'span', 'value': 'data-publishdate'},
            
        ]
        for tag_info in PUBLISH_DATE_TAGS:
            content_key = 'datetime' if tag_info.get('value') == 'datePublished' else 'content'
            meta_tags = self.parser.getElementsByTag(original_doc, attr=tag_info['attribute'], value=tag_info['value'])
            if meta_tags:
                date_content = self.parser.getAttribute(meta_tags[0], content_key)
                if date_content:
                    if debug: print(f"  [DEBUG TIER 2] Found meta tag '{tag_info['value']}' with content: '{date_content}'")
                    dt = parse_and_validate(date_content, from_heuristic=False, from_url=False)
                    if dt: 
                        if debug: print(f"[DEBUG] SUCCESS (Meta): {dt}")
                        return dt

        time_tags = self.parser.getElementsByTag(original_doc, tag='time')
        for time_tag in time_tags:
            datetime_attr = self.parser.getAttribute(time_tag, 'datetime')
            if datetime_attr:
                if debug: print(f"  [DEBUG TIER 2] Found <time> tag with datetime: '{datetime_attr}'")
                dt = parse_and_validate(datetime_attr, from_heuristic=False, from_url=False)
                if dt: 
                    if debug: print(f"[DEBUG] SUCCESS (Time Tag): {dt}")
                    return dt
        if debug: print("[DEBUG TIER 1 & 2] INFO: No valid date found in URL or metadata.")

        # Heuristic Tiers with Distance-Based Scoring
        if debug: print("[DEBUG] INFO: Starting distance-based scoring for all candidates...")
        
        PUBLICATION_KEYWORDS = ['published', 'posted', 'created', 'date', 'time', 'updated', 'modified']
        
        # Map the top_node to target document
        mapped_top_node = None
        if top_node is not None and source_doc is not None:
            if debug: print(f"[DEBUG] INFO: Mapping top_node from source document to target document...")
            mapped_top_node = find_corresponding_node(top_node, source_doc, original_doc)
        
        if mapped_top_node is not None:
            tree = original_doc.getroottree()
            top_node_xpath = tree.getpath(mapped_top_node)
            if debug: print(f"[DEBUG] INFO: Successfully mapped top_node. Reference XPath: '{top_node_xpath}'")
        else:
            if debug: print(f"[DEBUG] WARNING: No mapped top_node available; distance scoring disabled.")
            
        candidates = []
        numeric_date_pattern = re.compile(r'\b(19|20)\d{2}[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12][0-9]|3[01])\b')
        
        # More specific penalty zones - avoid over-penalizing
        penalty_nodes = self.parser.getElementsByTags(original_doc, tags=['nav', 'aside', 'sidebar', 'footer'])
        all_tags = self.parser.getElementsByTags(original_doc, tags=['p', 'span', 'div', 'td', 'time'])
        
        tree = original_doc.getroottree()

        for tag in all_tags:
            tag_text = self.parser.getText(tag).strip()
            if not tag_text or len(tag_text) < 6 or len(tag_text) > 200: 
                continue

            # STRICT: Only process if it passes strict date detection OR has date-related attributes
            tag_class = self.parser.getAttribute(tag, 'class') or ''
            tag_id = self.parser.getAttribute(tag, 'id') or ''
            
            has_date_attributes = any(keyword in (tag_class + ' ' + tag_id).lower() 
                                    for keyword in ['date', 'time', 'publish', 'created', 'updated','data-publishdate'])
            
            is_date_like = (self.date_finder.contains_month(tag_text) or 
                        numeric_date_pattern.search(tag_text) or 
                        is_likely_date_text(tag_text))
            
            # Skip unless it's clearly date-related
            if not (is_date_like or has_date_attributes):
                continue
            
            # Skip very long text unless it has strong date attributes
            if len(tag_text) > 100 and not has_date_attributes:
                # Check if it's just a long sentence with an embedded date
                iso_matches = re.findall(r'\b\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?\b', tag_text)
                if iso_matches:
                    # Extract just the date part and create a virtual candidate
                    for iso_date in iso_matches:
                        if debug: print(f"  [DEBUG] Extracting embedded date: '{iso_date}' from long text")
                        
                        score = 0
                        debug_info = []
                        
                        # Give embedded dates moderate proximity scoring
                        if mapped_top_node is not None:
                            proximity_score = calculate_proximity_score(tag, mapped_top_node, max_distance=10)
                            proximity_score = int(proximity_score * 0.7)  # Reduce slightly for embedded dates
                            if proximity_score > 0:
                                score += proximity_score
                                debug_info.append(f"Proximity:+{proximity_score}")
                            else:
                                distance = calculate_dom_distance(tag, mapped_top_node)
                                debug_info.append(f"DistantNode:{distance}")
                        
                        # Bonus for clean ISO format
                        score += 80
                        debug_info.append("EmbeddedISO:+80")
                        
                        candidates.append({
                            'score': score, 
                            'text': iso_date, 
                            'debug': ", ".join(debug_info), 
                            'tag': tag
                        })
                continue  # Skip processing the long text itself
                
            if debug: print(f"  [DEBUG] Processing date candidate: '{tag_text[:60]}...'")
            
            score = 0
            debug_info = []

            # Higher base score for elements with date attributes
            if has_date_attributes:
                score += 50
                debug_info.append("DateAttrib:+50")

            # Bonus for shorter, cleaner date strings
            if len(tag_text) <= 30:
                score += 40
                debug_info.append("ShortDate:+40")
            elif len(tag_text) <= 50:
                score += 20
                debug_info.append("MediumDate:+20")

            # Distance-based scoring (reduced weight for non-attribute matches)
            if mapped_top_node is not None:
                proximity_score = calculate_proximity_score(tag, mapped_top_node, max_distance=10)
                
                # Reduce proximity weight for text without date attributes
                if not has_date_attributes:
                    proximity_score = int(proximity_score * 0.3)  # 30% weight
                    
                if proximity_score > 0:
                    score += proximity_score
                    debug_info.append(f"Proximity:+{proximity_score}")
                else:
                    distance = calculate_dom_distance(tag, mapped_top_node)
                    debug_info.append(f"DistantNode:{distance}")
            
            # Keyword scoring
            if any(kw in tag_text.lower() for kw in PUBLICATION_KEYWORDS):
                score += 100
                debug_info.append("PubKwd:+100")
            
            # Class-based scoring 
            if any(s in tag_class.lower() for s in ['publish', 'timestamp', 'date', 'entry-date', 'post-date','time']):
                score += 80  # Increased from 60
                debug_info.append("Class:+80")

            # ID-based scoring (highest priority)
            if any(s in tag_id.lower() for s in ['publish', 'date', 'time', 'created', 'updated']):
                score += 120  # Increased from 80
                debug_info.append("ID:+120")

            # Bonus for time elements
            if tag.tag == 'time':
                score += 60
                debug_info.append("TimeTag:+60")

            # IMPROVED: Less aggressive penalty zone
            in_penalty_zone = False
            parent = self.parser.getParent(tag)
            while parent is not None:
                if parent in penalty_nodes: 
                    in_penalty_zone = True
                    break
                parent = self.parser.getParent(parent)
            if in_penalty_zone:
                score -= 20  # Further reduced penalty
                debug_info.append("PenaltyZone:-20")
            
            candidates.append({'score': score, 'text': tag_text, 'debug': ", ".join(debug_info), 'tag': tag})

        if not candidates:
            if debug: print("[DEBUG] FAILED: No suitable date candidates found.")
            return None

        candidates.sort(key=lambda x: x['score'], reverse=True)

        if debug: print(f"[DEBUG] INFO: Found {len(candidates)} date candidates. Top 10:")
        for i, cand in enumerate(candidates[:10]):
            if debug: print(f"  {i+1}. Score: {cand['score']:.1f}, Text: '{cand['text'][:50]}...', ({cand['debug']})")
        
        # Try candidates with positive scores first, then others
        for candidate in candidates:
            if candidate['score'] < -30:  # Skip heavily penalized candidates only
                if debug: print(f"  [DEBUG] Skipping heavily penalized candidate: {candidate['text'][:30]}... (Score: {candidate['score']})")
                continue
                
            datetime_obj = parse_and_validate(candidate['text'], from_heuristic=True, from_url=False)
            if datetime_obj:
                if debug: print(f"[DEBUG] SUCCESS: Best candidate '{candidate['text'][:50]}...' (Score: {candidate['score']:.1f}) → {datetime_obj}")
                return datetime_obj

        if debug: print("[DEBUG] --- All tiers failed. Returning None. ---")
        return None
    
    def get_title(self, original_doc, cleaned_doc, top_node=None, debug=False):
        """
        Final, definitive, context-aware function to find the best title.
        Uses an advanced scoring system that considers a wider range of tags (h1-h6),
        proximity to top_node, attributes, and text structure. [DEBUG VERSION]
        """
        if debug: print("\n[DEBUG] --- Starting get_title ---")

        # HELPER FUNCTIONS
        def find_corresponding_node(source_node, source_doc_tree, target_doc_tree):
            if source_node is None: return None
            try:
                source_xpath = source_doc_tree.getpath(source_node)
                target_nodes = target_doc_tree.xpath(source_xpath)
                return target_nodes[0] if target_nodes else None
            except Exception as e:
                if debug: print(f"  [DEBUG] Node mapping failed: {e}")
                return None

        def calculate_dom_distance(node1, node2, tree):
            if node1 is None or node2 is None: return float('inf')
            try:
                path1 = tree.getpath(node1).split('/')
                path2 = tree.getpath(node2).split('/')
                common_len = 0
                for i in range(min(len(path1), len(path2))):
                    if path1[i] == path2[i]: common_len += 1
                    else: break
                return (len(path1) - common_len) + (len(path2) - common_len)
            except: return float('inf')

        # 1. Get baseline candidates from metadata
        title_element = self.parser.getElementsByTag(original_doc, tag='title')
        title_text = self.parser.getText(title_element[0]) if title_element else ""
        title_og = (self.get_meta_content(original_doc, 'meta[property="og:title"]') or 
                    self.get_meta_content(original_doc, 'meta[name="og:title"]') or '')

        # 2. Intelligent Heuristic Search
        candidates = []
        potential_tags = self.parser.getElementsByTags(original_doc, tags=['h1', 'h2', 'h3', 'p'])
        
        penalty_tags = ['nav', 'aside', 'sidebar', 'footer']
        penalty_selectors = ['.related-posts', '.comments', '.e-loop-item', '.post-navigation']
        penalty_nodes = self.parser.getElementsByTags(original_doc, tags=penalty_tags)
        for selector in penalty_selectors:
            penalty_nodes.extend(self.parser.css_select(original_doc, selector))

        original_doc_tree = original_doc.getroottree()
        mapped_top_node = find_corresponding_node(top_node, cleaned_doc.getroottree(), original_doc_tree)
        if debug and mapped_top_node is not None:
             print("[DEBUG] INFO: Mapped top_node to original doc for location scoring.")

        for tag in potential_tags:
            tag_text = self.parser.getText(tag).strip()
            if not tag_text or len(tag_text) < 15 or len(tag_text) > 250: continue

            score = 0
            debug_info = []

            # Tag Type Score
            if tag.tag == 'h1': score += 100; debug_info.append("H1:+100")
            elif tag.tag == 'h2': score += 30; debug_info.append("H2:+30")
            
            # Attribute Score
            tag_class_id = ((self.parser.getAttribute(tag, 'class') or '') + ' ' + (self.parser.getAttribute(tag, 'id') or '')).lower()
            if any(s in tag_class_id for s in ['title', 'headline', 'heading']):
                score += 85; debug_info.append("Attr:+85")

            # Location Score (Proximity to main content)
            distance = calculate_dom_distance(tag, mapped_top_node, original_doc_tree)
            is_in_top_node = (mapped_top_node is not None and (tag == mapped_top_node or tag in mapped_top_node.iterdescendants()))

            if is_in_top_node:
                score += 50; debug_info.append("InTopNode:+50")
            # CRITICAL ADDITION: Sibling Proximity Bonus
            elif distance <= 4: # If it's a very close sibling/cousin
                score += 80; debug_info.append(f"SiblingProx:{distance}:+80")
            
            # Paragraph Penalty
            if tag.tag == 'p':
                 if any(p in tag_text for p in ['.', '?', '!', ':', '»']) or len(tag_text.split()) > 25:
                    score -= 50; debug_info.append("IsPara:-50")
            
            # Penalty Zone
            in_penalty_zone = False
            parent = tag
            while parent is not None:
                if parent in penalty_nodes: in_penalty_zone = True; break
                parent = self.parser.getParent(parent)
            if in_penalty_zone: score -= 100; debug_info.append("PenaltyZone:-100")
            
            candidates.append({'score': score, 'text': tag_text, 'debug': ", ".join(debug_info)})

        title_h_candidate = ""
        if candidates:
            candidates.sort(key=lambda x: x['score'], reverse=True)
            if debug:
                print(f"[DEBUG] INFO: Found {len(candidates)} title candidates. Top 5:")
                for cand in candidates[:5]: print(f"  - Score: {cand['score']:.1f}, Text: '{cand['text']}', ({cand['debug']})")
            # Use a quality threshold to ensure we don't pick a low-scoring candidate
            if candidates[0]['score'] > 70:
                title_h_candidate = candidates[0]['text']
        
        # 3. Final Comparison of all sources
        options = [
            {'text': title_h_candidate, 'score': 1.0, 'source': 'Heuristic'},
            {'text': title_og, 'score': 0.9, 'source': 'OG Meta'},
            {'text': title_text, 'score': 0.5, 'source': 'Title Tag'}
        ]

        best_option = None
        highest_score = -1

        for option in options:
            if not option['text']: continue
            score = option['score'] * len(option['text'])
            if score > highest_score:
                highest_score = score
                best_option = option

        if best_option:
            final_title = best_option['text']
            if debug: print(f"[DEBUG] INFO: Chose '{best_option['source']}' candidate before splitting: '{final_title}'")
        else:
            final_title = ""
            if debug: print("[DEBUG] WARNING: No valid title options found.")
        
        # 4. Cleanup and return
        if '|' in final_title:
            final_title = self.split_title(final_title, PIPE_SPLITTER, title_h_candidate or title_og)
        elif ' - ' in final_title:
            final_title = self.split_title(final_title, DASH_SPLITTER, title_h_candidate or title_og)
        
        final_title = MOTLEY_REPLACEMENT.replaceAll(final_title).strip()
        if debug: print(f"[DEBUG] SUCCESS: Final Title: '{final_title}'")
        return final_title

    
    def split_title(self, title, splitter, hint=None):
        """Split the title to best part possible
        """
        large_text_length = 0
        large_text_index = 0
        title_pieces = splitter.split(title)

        if hint:
            filter_regex = re.compile(r'[^a-zA-Z0-9\ ]')
            hint = filter_regex.sub('', hint).lower()

        # find the largest title piece
        for i, title_piece in enumerate(title_pieces):
            current = title_piece.strip()
            if hint and hint in filter_regex.sub('', current).lower():
                large_text_index = i
                break
            if len(current) > large_text_length:
                large_text_length = len(current)
                large_text_index = i

        # replace content
        title = title_pieces[large_text_index]
        return TITLE_REPLACEMENTS.replaceAll(title).strip()

    def get_feed_urls(self, source_url, categories):
        """Takes a source url and a list of category objects and returns
        a list of feed urls
        """
        total_feed_urls = []
        for category in categories:
            kwargs = {'attr': 'type', 'value': r'application\/rss\+xml'}
            feed_elements = self.parser.getElementsByTag(
                category.doc, **kwargs)
            feed_urls = [e.get('href') for e in feed_elements if e.get('href')]
            total_feed_urls.extend(feed_urls)

        total_feed_urls = total_feed_urls[:50]
        total_feed_urls = [urls.prepare_url(f, source_url)
                           for f in total_feed_urls]
        total_feed_urls = list(set(total_feed_urls))
        return total_feed_urls

    def get_favicon(self, doc):
        """Extract the favicon from a website http://en.wikipedia.org/wiki/Favicon
        <link rel="shortcut icon" type="image/png" href="favicon.png" />
        <link rel="icon" type="image/png" href="favicon.png" />
        """
        kwargs = {'tag': 'link', 'attr': 'rel', 'value': 'icon'}
        meta = self.parser.getElementsByTag(doc, **kwargs)
        if meta:
            favicon = self.parser.getAttribute(meta[0], 'href')
            return favicon
        return ''

    def get_meta_lang(self, doc):
        """Extract content language from meta
        """
        # we have a lang attribute in html
        attr = self.parser.getAttribute(doc, attr='lang')
        if attr is None:
            # look up for a Content-Language in meta
            items = [
                {'tag': 'meta', 'attr': 'http-equiv',
                 'value': 'content-language'},
                {'tag': 'meta', 'attr': 'name', 'value': 'lang'}
            ]
            for item in items:
                meta = self.parser.getElementsByTag(doc, **item)
                if meta:
                    attr = self.parser.getAttribute(
                        meta[0], attr='content')
                    break
        if attr:
            value = attr[:2]
            if re.search(RE_LANG, value):
                return value.lower()

        return None

    def get_meta_content(self, doc, metaname):
        """Extract a given meta content form document.
        Example metaNames:
            "meta[name=description]"
            "meta[name=keywords]"
            "meta[property=og:type]"
        """
        meta = self.parser.css_select(doc, metaname)
        content = None
        if meta is not None and len(meta) > 0:
            content = self.parser.getAttribute(meta[0], 'content')
        if content:
            return content.strip()
        return ''

    def get_meta_img_url(self, article_url, doc):
        """Returns the 'top img' as specified by the website
        """
        top_meta_image, try_one, try_two, try_three, try_four = [None] * 5
        try_one = self.get_meta_content(doc, 'meta[property="og:image"]')
        if not try_one:
            link_img_src_kwargs = \
                {'tag': 'link', 'attr': 'rel', 'value': 'img_src|image_src'}
            elems = self.parser.getElementsByTag(doc, use_regex=True, **link_img_src_kwargs)
            try_two = elems[0].get('href') if elems else None

            if not try_two:
                try_three = self.get_meta_content(doc, 'meta[name="og:image"]')

                if not try_three:
                    link_icon_kwargs = {'tag': 'link', 'attr': 'rel', 'value': 'icon'}
                    elems = self.parser.getElementsByTag(doc, **link_icon_kwargs)
                    try_four = elems[0].get('href') if elems else None

        top_meta_image = try_one or try_two or try_three or try_four

        if top_meta_image:
            return urljoin(article_url, top_meta_image)
        return ''

    def get_meta_type(self, doc):
        """Returns meta type of article, open graph protocol
        """
        return self.get_meta_content(doc, 'meta[property="og:type"]')

    def get_meta_site_name(self, doc):
        """Returns site name of article, open graph protocol
        """
        return self.get_meta_content(doc, 'meta[property="og:site_name"]')

    def get_meta_description(self, doc):
        """If the article has meta description set in the source, use that
        """
        return self.get_meta_content(doc, "meta[name=description]")

    def get_meta_keywords(self, doc):
        """If the article has meta keywords set in the source, use that
        """
        return self.get_meta_content(doc, "meta[name=keywords]")

    def get_meta_data(self, doc):
        data = defaultdict(dict)
        properties = self.parser.css_select(doc, 'meta')
        for prop in properties:
            key = prop.attrib.get('property') or prop.attrib.get('name')
            value = prop.attrib.get('content') or prop.attrib.get('value')

            if not key or not value:
                continue

            key, value = key.strip(), value.strip()
            if value.isdigit():
                value = int(value)

            if ':' not in key:
                data[key] = value
                continue

            key = key.split(':')
            key_head = key.pop(0)
            ref = data[key_head]

            if isinstance(ref, str) or isinstance(ref, int):
                data[key_head] = {key_head: ref}
                ref = data[key_head]

            for idx, part in enumerate(key):
                if idx == len(key) - 1:
                    ref[part] = value
                    break
                if not ref.get(part):
                    ref[part] = dict()
                elif isinstance(ref.get(part), str) or isinstance(ref.get(part), int):
                    # Not clear what to do in this scenario,
                    # it's not always a URL, but an ID of some sort
                    ref[part] = {'identifier': ref[part]}
                ref = ref[part]
        return data

    def get_canonical_link(self, article_url, doc):
        """
        Return the article's canonical URL

        Gets the first available value of:
        1. The rel=canonical tag
        2. The og:url tag
        """
        links = self.parser.getElementsByTag(doc, tag='link', attr='rel',
                                             value='canonical')

        canonical = self.parser.getAttribute(links[0], 'href') if links else ''
        og_url = self.get_meta_content(doc, 'meta[property="og:url"]')
        meta_url = canonical or og_url or ''
        if meta_url:
            meta_url = meta_url.strip()
            parsed_meta_url = urlparse(meta_url)
            if not parsed_meta_url.hostname:
                # MIGHT not have a hostname in meta_url
                # parsed_url.path might be 'example.com/article.html' where
                # clearly example.com is the hostname
                parsed_article_url = urlparse(article_url)
                strip_hostname_in_meta_path = re. \
                    match(".*{}(?=/)/(.*)".
                          format(parsed_article_url.hostname),
                          parsed_meta_url.path)
                try:
                    true_path = strip_hostname_in_meta_path.group(1)
                except AttributeError:
                    true_path = parsed_meta_url.path

                # true_path may contain querystrings and fragments
                meta_url = urlunparse((parsed_article_url.scheme,
                                       parsed_article_url.hostname, true_path,
                                       '', '', ''))

        return meta_url

    def get_img_urls(self, article_url, doc):
        """Return all of the images on an html page, lxml root
        """
        img_kwargs = {'tag': 'img'}
        img_tags = self.parser.getElementsByTag(doc, **img_kwargs)
        urls = [img_tag.get('src')
                for img_tag in img_tags if img_tag.get('src')]
        img_links = set([urljoin(article_url, url)
                         for url in urls])
        return img_links

    def get_first_img_url(self, article_url, top_node):
        """Retrieves the first image in the 'top_node'
        The top node is essentially the HTML markdown where the main
        article lies and the first image in that area is probably signifigcant.
        """
        node_images = self.get_img_urls(article_url, top_node)
        node_images = list(node_images)
        if node_images:
            return urljoin(article_url, node_images[0])
        return ''

    def _get_urls(self, doc, titles):
        """Return a list of urls or a list of (url, title_text) tuples
        if specified.
        """
        if doc is None:
            return []

        a_kwargs = {'tag': 'a'}
        a_tags = self.parser.getElementsByTag(doc, **a_kwargs)

        # TODO: this should be refactored! We should have a separate
        # method which siphones the titles our of a list of <a> tags.
        if titles:
            return [(a.get('href'), a.text) for a in a_tags if a.get('href')]
        return [a.get('href') for a in a_tags if a.get('href')]

    def get_urls(self, doc_or_html, titles=False, regex=False):
        """`doc_or_html`s html page or doc and returns list of urls, the regex
        flag indicates we don't parse via lxml and just search the html.
        """
        if doc_or_html is None:
            log.critical('Must extract urls from either html, text or doc!')
            return []
        # If we are extracting from raw text
        if regex:
            doc_or_html = re.sub('<[^<]+?>', ' ', str(doc_or_html))
            doc_or_html = re.findall(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|'
            r'(?:%[0-9a-fA-F][0-9a-fA-F]))+', doc_or_html)
            doc_or_html = [i.strip() for i in doc_or_html]
            return doc_or_html or []
        # If the doc_or_html is html, parse it into a root
        if isinstance(doc_or_html, str):
            doc = self.parser.fromstring(doc_or_html)
        else:
            doc = doc_or_html
        return self._get_urls(doc, titles)

    def get_category_urls(self, source_url, doc):
        """Inputs source lxml root and source url, extracts domain and
        finds all of the top level urls, we are assuming that these are
        the category urls.
        cnn.com --> [cnn.com/latest, world.cnn.com, cnn.com/asia]
        """
        page_urls = self.get_urls(doc)
        valid_categories = []
        for p_url in page_urls:
            scheme = urls.get_scheme(p_url, allow_fragments=False)
            domain = urls.get_domain(p_url, allow_fragments=False)
            path = urls.get_path(p_url, allow_fragments=False)

            if not domain and not path:
                if self.config.verbose:
                    print('elim category url %s for no domain and path'
                          % p_url)
                continue
            if path and path.startswith('#'):
                if self.config.verbose:
                    print('elim category url %s path starts with #' % p_url)
                continue
            if scheme and (scheme != 'http' and scheme != 'https'):
                if self.config.verbose:
                    print(('elim category url %s for bad scheme, '
                           'not http nor https' % p_url))
                continue

            if domain:
                child_tld = tldextract.extract(p_url)
                domain_tld = tldextract.extract(source_url)
                child_subdomain_parts = child_tld.subdomain.split('.')
                subdomain_contains = False
                for part in child_subdomain_parts:
                    if part == domain_tld.domain:
                        if self.config.verbose:
                            print(('subdomain contains at %s and %s' %
                                   (str(part), str(domain_tld.domain))))
                        subdomain_contains = True
                        break

                # Ex. microsoft.com is definitely not related to
                # espn.com, but espn.go.com is probably related to espn.com
                if not subdomain_contains and \
                        (child_tld.domain != domain_tld.domain):
                    if self.config.verbose:
                        print(('elim category url %s for domain '
                               'mismatch' % p_url))
                        continue
                elif child_tld.subdomain in ['m', 'i']:
                    if self.config.verbose:
                        print(('elim category url %s for mobile '
                               'subdomain' % p_url))
                    continue
                else:
                    valid_categories.append(scheme + '://' + domain)
                    # TODO account for case where category is in form
                    # http://subdomain.domain.tld/category/ <-- still legal!
            else:
                # we want a path with just one subdir
                # cnn.com/world and cnn.com/world/ are both valid_categories
                path_chunks = [x for x in path.split('/') if len(x) > 0]
                if 'index.html' in path_chunks:
                    path_chunks.remove('index.html')

                if len(path_chunks) == 1 and len(path_chunks[0]) < 14:
                    valid_categories.append(domain + path)
                else:
                    if self.config.verbose:
                        print(('elim category url %s for >1 path chunks '
                               'or size path chunks' % p_url))
        stopwords = [
            'about', 'help', 'privacy', 'legal', 'feedback', 'sitemap',
            'profile', 'account', 'mobile', 'sitemap', 'facebook', 'myspace',
            'twitter', 'linkedin', 'bebo', 'friendster', 'stumbleupon',
            'youtube', 'vimeo', 'store', 'mail', 'preferences', 'maps',
            'password', 'imgur', 'flickr', 'search', 'subscription', 'itunes',
            'siteindex', 'events', 'stop', 'jobs', 'careers', 'newsletter',
            'subscribe', 'academy', 'shopping', 'purchase', 'site-map',
            'shop', 'donate', 'newsletter', 'product', 'advert', 'info',
            'tickets', 'coupons', 'forum', 'board', 'archive', 'browse',
            'howto', 'how to', 'faq', 'terms', 'charts', 'services',
            'contact', 'plus', 'admin', 'login', 'signup', 'register',
            'developer', 'proxy']

        _valid_categories = []

        # TODO Stop spamming urlparse and tldextract calls...

        for p_url in valid_categories:
            path = urls.get_path(p_url)
            subdomain = tldextract.extract(p_url).subdomain
            conjunction = path + ' ' + subdomain
            bad = False
            for badword in stopwords:
                if badword.lower() in conjunction.lower():
                    if self.config.verbose:
                        print(('elim category url %s for subdomain '
                               'contain stopword!' % p_url))
                    bad = True
                    break
            if not bad:
                _valid_categories.append(p_url)

        _valid_categories.append('/')  # add the root

        for i, p_url in enumerate(_valid_categories):
            if p_url.startswith('://'):
                p_url = 'http' + p_url
                _valid_categories[i] = p_url

            elif p_url.startswith('//'):
                p_url = 'http:' + p_url
                _valid_categories[i] = p_url

            if p_url.endswith('/'):
                p_url = p_url[:-1]
                _valid_categories[i] = p_url

        _valid_categories = list(set(_valid_categories))

        category_urls = [urls.prepare_url(p_url, source_url)
                         for p_url in _valid_categories]
        category_urls = [c for c in category_urls if c is not None]
        return category_urls

    def extract_tags(self, doc):
        if len(list(doc)) == 0:
            return NO_STRINGS
        elements = self.parser.css_select(
            doc, A_REL_TAG_SELECTOR)
        if not elements:
            elements = self.parser.css_select(
                doc, A_HREF_TAG_SELECTOR)
            if not elements:
                return NO_STRINGS

        tags = []
        for el in elements:
            tag = self.parser.getText(el)
            if tag:
                tags.append(tag)
        return set(tags)

    def calculate_best_node(self, doc):
        top_node = None
        nodes_to_check = self.nodes_to_check(doc)
        starting_boost = float(1.0)
        cnt = 0
        i = 0
        parent_nodes = []
        nodes_with_text = []

        for node in nodes_to_check:
            text_node = self.parser.getText(node)
            word_stats = self.stopwords_class(language=self.language). \
                get_stopword_count(text_node)
            high_link_density = self.is_highlink_density(node)
            if word_stats.get_stopword_count() > 2 and not high_link_density:
                nodes_with_text.append(node)

        nodes_number = len(nodes_with_text)
        negative_scoring = 0
        bottom_negativescore_nodes = float(nodes_number) * 0.25

        for node in nodes_with_text:
            boost_score = float(0)
            # boost
            if self.is_boostable(node):
                if cnt >= 0:
                    boost_score = float((1.0 / starting_boost) * 50)
                    starting_boost += 1
            # nodes_number
            if nodes_number > 15:
                if (nodes_number - i) <= bottom_negativescore_nodes:
                    booster = float(
                        bottom_negativescore_nodes - (nodes_number - i))
                    boost_score = float(-pow(booster, float(2)))
                    negscore = abs(boost_score) + negative_scoring
                    if negscore > 40:
                        boost_score = float(5)

            text_node = self.parser.getText(node)
            word_stats = self.stopwords_class(language=self.language). \
                get_stopword_count(text_node)
            upscore = int(word_stats.get_stopword_count() + boost_score)

            parent_node = self.parser.getParent(node)
            self.update_score(parent_node, upscore)
            self.update_node_count(parent_node, 1)

            if parent_node not in parent_nodes:
                parent_nodes.append(parent_node)

            # Parent of parent node
            parent_parent_node = self.parser.getParent(parent_node)
            if parent_parent_node is not None:
                self.update_node_count(parent_parent_node, 1)
                self.update_score(parent_parent_node, upscore / 2)
                if parent_parent_node not in parent_nodes:
                    parent_nodes.append(parent_parent_node)
            cnt += 1
            i += 1

        top_node_score = 0
        for e in parent_nodes:
            score = self.get_score(e)

            if score > top_node_score:
                top_node = e
                top_node_score = score

            if top_node is None:
                top_node = e
        return top_node

    def is_boostable(self, node):
        """A lot of times the first paragraph might be the caption under an image
        so we'll want to make sure if we're going to boost a parent node that
        it should be connected to other paragraphs, at least for the first n
        paragraphs so we'll want to make sure that the next sibling is a
        paragraph and has at least some substantial weight to it.
        """
        para = "p"
        steps_away = 0
        minimum_stopword_count = 5
        max_stepsaway_from_node = 3

        nodes = self.walk_siblings(node)
        for current_node in nodes:
            # <p>
            current_node_tag = self.parser.getTag(current_node)
            if current_node_tag == para:
                if steps_away >= max_stepsaway_from_node:
                    return False
                paragraph_text = self.parser.getText(current_node)
                word_stats = self.stopwords_class(language=self.language). \
                    get_stopword_count(paragraph_text)
                if word_stats.get_stopword_count() > minimum_stopword_count:
                    return True
                steps_away += 1
        return False

    def walk_siblings(self, node):
        return self.parser.previousSiblings(node)

    def add_siblings(self, top_node):
        baseline_score_siblings_para = self.get_siblings_score(top_node)
        results = self.walk_siblings(top_node)
        for current_node in results:
            ps = self.get_siblings_content(
                current_node, baseline_score_siblings_para)
            for p in ps:
                top_node.insert(0, p)
        return top_node

    def get_siblings_content(
            self, current_sibling, baseline_score_siblings_para):
        """Adds any siblings that may have a decent score to this node
        """
        if current_sibling.tag == 'p' and \
                        len(self.parser.getText(current_sibling)) > 0:
            e0 = current_sibling
            if e0.tail:
                e0 = copy.deepcopy(e0)
                e0.tail = ''
            return [e0]
        else:
            potential_paragraphs = self.parser.getElementsByTag(
                current_sibling, tag='p')
            if potential_paragraphs is None:
                return None
            else:
                ps = []
                for first_paragraph in potential_paragraphs:
                    text = self.parser.getText(first_paragraph)
                    if len(text) > 0:
                        word_stats = self.stopwords_class(
                            language=self.language). \
                            get_stopword_count(text)
                        paragraph_score = word_stats.get_stopword_count()
                        sibling_baseline_score = float(.30)
                        high_link_density = self.is_highlink_density(
                            first_paragraph)
                        score = float(baseline_score_siblings_para *
                                      sibling_baseline_score)
                        if score < paragraph_score and not high_link_density:
                            p = self.parser.createElement(
                                tag='p', text=text, tail=None)
                            ps.append(p)
                return ps

    def get_siblings_score(self, top_node):
        """We could have long articles that have tons of paragraphs
        so if we tried to calculate the base score against
        the total text score of those paragraphs it would be unfair.
        So we need to normalize the score based on the average scoring
        of the paragraphs within the top node.
        For example if our total score of 10 paragraphs was 1000
        but each had an average value of 100 then 100 should be our base.
        """
        base = 100000
        paragraphs_number = 0
        paragraphs_score = 0
        nodes_to_check = self.parser.getElementsByTag(top_node, tag='p')

        for node in nodes_to_check:
            text_node = self.parser.getText(node)
            word_stats = self.stopwords_class(language=self.language). \
                get_stopword_count(text_node)
            high_link_density = self.is_highlink_density(node)
            if word_stats.get_stopword_count() > 2 and not high_link_density:
                paragraphs_number += 1
                paragraphs_score += word_stats.get_stopword_count()

        if paragraphs_number > 0:
            base = paragraphs_score / paragraphs_number

        return base

    def update_score(self, node, add_to_score):
        """Adds a score to the gravityScore Attribute we put on divs
        we'll get the current score then add the score we're passing
        in to the current.
        """
        current_score = 0
        score_string = self.parser.getAttribute(node, 'gravityScore')
        if score_string:
            current_score = float(score_string)

        new_score = current_score + add_to_score
        self.parser.setAttribute(node, "gravityScore", str(new_score))

    def update_node_count(self, node, add_to_count):
        """Stores how many decent nodes are under a parent node
        """
        current_score = 0
        count_string = self.parser.getAttribute(node, 'gravityNodes')
        if count_string:
            current_score = int(count_string)

        new_score = current_score + add_to_count
        self.parser.setAttribute(node, "gravityNodes", str(new_score))

    def is_highlink_density(self, e):
        """Checks the density of links within a node, if there is a high
        link to text ratio, then the text is less likely to be relevant
        """
        links = self.parser.getElementsByTag(e, tag='a')
        if not links:
            return False

        text = self.parser.getText(e)
        words = [word for word in text.split() if word.isalnum()]
        if not words:
            return True
        words_number = float(len(words))
        sb = []
        for link in links:
            sb.append(self.parser.getText(link))

        link_text = ''.join(sb)
        link_words = link_text.split()
        num_link_words = float(len(link_words))
        num_links = float(len(links))
        link_divisor = float(num_link_words / words_number)
        score = float(link_divisor * num_links)
        if score >= 1.0:
            return True
        return False
        # return True if score > 1.0 else False

    def get_score(self, node):
        """Returns the gravityScore as an integer from this node
        """
        return self.get_node_gravity_score(node) or 0

    def get_node_gravity_score(self, node):
        gravity_score = self.parser.getAttribute(node, 'gravityScore')
        if not gravity_score:
            return None
        return float(gravity_score)

    def nodes_to_check(self, doc):
        """Returns a list of nodes we want to search
        on like paragraphs and tables
        """
        nodes_to_check = []
        for tag in ['p', 'pre', 'td']:
            items = self.parser.getElementsByTag(doc, tag=tag)
            nodes_to_check += items
        return nodes_to_check

    def is_table_and_no_para_exist(self, e):
        sub_paragraphs = self.parser.getElementsByTag(e, tag='p')
        for p in sub_paragraphs:
            txt = self.parser.getText(p)
            if len(txt) < 25:
                self.parser.remove(p)

        sub_paragraphs_2 = self.parser.getElementsByTag(e, tag='p')
        if len(sub_paragraphs_2) == 0 and e.tag != "td":
            return True
        return False

    def is_nodescore_threshold_met(self, node, e):
        top_node_score = self.get_score(node)
        current_node_score = self.get_score(e)
        threshold = float(top_node_score * .08)

        if (current_node_score < threshold) and e.tag != 'td':
            return False
        return True

    def post_cleanup(self, top_node):
        """Remove any divs that looks like non-content, clusters of links,
        or paras with no gusto; add adjacent nodes which look contenty
        """
        node = self.add_siblings(top_node)
        for e in self.parser.getChildren(node):
            e_tag = self.parser.getTag(e)
            if e_tag != 'p':
                if self.is_highlink_density(e):
                    self.parser.remove(e)
        return node
