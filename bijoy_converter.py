"""Unicode/Avro Bengali -> Bijoy (ANSI) conversion.

The editor stores Bengali as Unicode (Avro keyboard output). Before image
rendering we convert that Unicode text to legacy Bijoy encoding so a matching
Bijoy/SutonnyMJ-compatible font can draw the glyphs without Bengali shaping.
"""
import re

PRE_KAR = {"ি", "ৈ", "ে"}
CONSONANTS = set("কখগঘঙচছজঝঞটঠডঢণতথদধনপফবভমশষসহযরলয়ংঃঁৎ")

# Ordered longest-first. These are the standard SutonnyMJ/Bijoy legacy glyph
# sequences used by the common Unicode -> Bijoy conversion implementations.
MAP = {
    "।": "|", "‘": "Ô", "’": "Õ", "“": "Ò", "”": "Ó",
    "্র্য": "ª¨", "র‌্য": "i¨", "ক্ক": "°", "ক্ট": "±", "ক্ত": "³", "ক্ব": "K¡",
    "স্ক্র": "¯Œ", "ক্র": "µ", "ক্ল": "K¬", "ক্ষ্ণ": "¶è", "ক্ষ্ম": "²", "ক্ষ": "¶", "ক্স": "·",
    "ক্ম": "´", "গু": "¸", "গ্ধ": "»", "গ্ন": "Mœ", "গ্ম": "M¥", "গ্রূ": "MÖƒ", "গ্ল": "Mø",
    "ঙ্ক্ষ": "•¶", "ঙ্ক": "¼", "ঙ্খ": "•L", "ঙ্গ": "½", "ঙ্ঘ": "•N", "ক্স": "•",
    "চ্চ": "”P", "চ্ছ্ব": "”Q¡", "চ্ছ": "”Q", "চ্ঞ": "”T",
    "জ্জ্ব": "¾¡", "জ্জ": "¾", "জ্ঝ": "À", "জ্ঞ": "Á", "জ্ব": "R¡",
    "ঞ্চ": "Â", "ঞ্ছ": "Ã", "ঞ্জ": "Ä", "ঞ্ঝ": "Å", "ট্ট": "Æ", "ট্ব": "U¡", "ট্ম": "U¥",
    "ড্ড": "Ç", "ণ্ট": "È", "ণ্ঠ": "É", "ণ্ড": "Ê", "ন্স": "Ý", "ণ্ব": "Y^",
    "ন্তু": "š‘", "ন্ত্ব": "š—¡", "ন্ত": "š—", "ত্ত্ব": "Ë¡", "ত্ত": "Ë", "ত্থ": "Ì", "ত্ন": "Zœ", "ত্ম": "Z¥", "ত্ব": "Z¡",
    "দ্গ": "˜M", "দ্ঘ": "˜N", "দ্দ": "Ï", "দ্ধ": "×", "দ্ব": "Ø", "দ্ভ": "™¢", "দ্ম": "Ù", "দ্রু": "`ª“",
    "ধ্ব": "aŸ", "ধ্ম": "a¥", "ন্ট": "›U", "ন্ঠ": "Ú", "ন্ড": "Û", "ন্ত্র": "š¿", "ন্থ": "š’", "ন্দ্ব": "›Ø", "ন্দ": "›`", "ন্ধ": "Ü", "ন্ন": "bœ", "ন্ব": "š^", "ন্ম": "b¥",
    "প্ট": "Þ", "প্ত": "ß", "প্ন": "cœ", "প্প": "à", "প্ল": "c", "প্স": "á", "ফ্ল": "d¬",
    "ব্জ": "â", "ব্দ": "ã", "ব্ধ": "ä", "ব্ব": "eŸ", "ব্ল": "e", "ভ্র": "å",
    "ম্ন": "gœ", "ম্প": "¤ú", "ম্ফ": "ç", "ম্ব": "¤^", "ম্ভ্র": "¤£", "ম্ভ": "¤¢", "ম্ম": "¤§", "ম্ল": "¤",
    "রু": "i“", "রূ": "iƒ", "ল্ক": "é", "ল্গ": "ê", "ল্ট": "ë", "ল্ড": "ì", "ল্প": "í", "ল্ফ": "î", "ল্ব": "j¦", "ল্ম": "j¥", "ল্ল": "jø",
    "শু": "ï", "শ্চ": "ð", "শ্ন": "kœ", "শ্ব": "k¦", "শ্ম": "k¥", "শ্ল": "kø",
    "ষ্ক্র": "®Œ", "ষ্ক": "®‹", "ষ্ট": "ó", "ষ্ঠ": "ô", "ষ্ণ": "ò", "ষ্প": "®ú", "ষ্ফ": "õ", "ষ্ম": "®§",
    "স্ক": "¯‹", "স্ট": "÷", "স্খ": "ö", "স্ত": "¯—", "স্তু": "¯‘", "স্থ": "¯’", "স্ন": "mœ", "স্প": "¯ú", "স্ফ": "ù", "স্ব": "¯^", "স্ম": "¯§", "স্ল": "¯",
    "হু": "û", "হ্ণ": "nè", "হ্ন": "ý", "হ্ম": "þ", "হ্ল": "n¬", "হৃ": "ü",
    "র্": "©", "্র": "«", "্য": "¨", "্": "&",
    "আ": "Av", "অ": "A", "ই": "B", "ঈ": "C", "উ": "D", "ঊ": "E", "ঋ": "F", "এ": "G", "ঐ": "H", "ও": "I", "ঔ": "J",
    "ক": "K", "খ": "L", "গ": "M", "ঘ": "N", "ঙ": "O", "চ": "P", "ছ": "Q", "জ": "R", "ঝ": "S", "ঞ": "T", "ট": "U", "ঠ": "V", "ড": "W", "ঢ": "X", "ণ": "Y", "ত": "Z", "থ": "_", "দ": "`", "ধ": "a", "ন": "b", "প": "c", "ফ": "d", "ব": "e", "ভ": "f", "ম": "g", "য": "h", "র": "i", "ল": "j", "শ": "k", "ষ": "l", "স": "m", "হ": "n", "ড়": "o", "ঢ়": "p", "য়": "q", "ৎ": "r",
    "০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4", "৫": "5", "৬": "6", "৭": "7", "৮": "8", "৯": "9",
    "া": "v", "ি": "w", "ী": "x", "ু": "y", "ূ": "~", "ৃ": "…", "ে": "‡", "ৈ": "‰", "ৗ": "Š", "ং": "s", "ঃ": "t", "ঁ": "u",
}

ORDERED_MAP = sorted(MAP.items(), key=lambda kv: len(kv[0]), reverse=True)


def _is_pre_kar(ch):
    return ch in PRE_KAR


def _is_consonant(ch):
    return ch in CONSONANTS


def rearrange_unicode(text):
    """Put Bengali pre-kar and র-ফলা sequences in Bijoy input order."""
    text = text.replace("ো", "ো").replace("ৌ", "ৌ")
    barrier = 0
    i = 0
    while i < len(text):
        if _is_pre_kar(text[i]):
            j = 1
            while i - j >= 0 and _is_consonant(text[i - j]) and i - j > barrier:
                if i - j - 1 >= 0 and text[i - j - 1] == "্":
                    j += 2
                else:
                    break
            text = text[:i-j] + text[i] + text[i-j:i] + text[i+1:]
            barrier = i + 1
            i += 1
            continue
        if i < len(text)-1 and text[i] == "্" and i > 0 and text[i-1] == "র" and (i < 2 or text[i-2] != "্"):
            j = 1
            found_pre = 0
            while i + j < len(text):
                if i+j+1 < len(text) and _is_consonant(text[i+j]) and text[i+j+1] == "্":
                    j += 2
                elif i+j+1 < len(text) and _is_consonant(text[i+j]) and _is_pre_kar(text[i+j+1]):
                    found_pre = 1
                    break
                else:
                    break
            if i+j < len(text):
                text = (text[:i-1] + text[i+j+1:i+j+1+found_pre] + text[i+1:i+j+1] + text[i-1:i+1] + text[i+j+1+found_pre:])
                i += j + found_pre
                barrier = i + 1
        i += 1
    return text


def unicode_to_bijoy(text):
    if not text:
        return ""
    # Normalize common Unicode spellings used by Avro/modern Bengali input.
    text = text.replace("ব়", "র").replace("ড়", "ড়").replace("ঢ়", "ঢ়").replace("য়", "য়")
    text = rearrange_unicode(text)
    for src, dst in ORDERED_MAP:
        text = text.replace(src, dst)
    return text
