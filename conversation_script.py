"""Readable writing-system rules, independent of inferred language labels."""
import unicodedata

def response_style(language,style,message=''):
    label=(language or '').casefold()
    if any(term in message.casefold() for term in ('chinese characters','汉字','漢字')):return 'standard'
    letters=[c for c in message if c.isalpha()]
    latin=bool(letters) and all('LATIN' in unicodedata.name(c,'') for c in letters)
    if ('hokkien' in label or 'teochew' in label) and (not letters or latin):return 'romanised'
    if latin and any(name in label for name in ('chinese','mandarin','tamil','cantonese')):return 'romanised'
    return style

def script_ok(text,language,style):
    if not isinstance(text,str) or '\ufffd' in text:return False
    label=(language or '').casefold()
    for char in text:
        number=ord(char);category=unicodedata.category(char)
        # Private-use, replacement and CJK extension-B+ glyphs are inappropriate for
        # generated interface text. Exact caregiver values are checked separately.
        if (category.startswith('C') and char not in '\n\r\t\u200c\u200d') or 0x20000<=number<=0x323AF:return False
        if style=='romanised' and 0x0300<=number<=0x036F:return False
        if not char.isalpha():continue
        name=unicodedata.name(char,'')
        if style=='romanised':
            if 'LATIN' not in name or not char.isascii():return False
        elif any(v in label for v in ('chinese','mandarin','cantonese','hokkien','teochew')):
            allowed=('LATIN' in name or 0x4E00<=number<=0x9FFF)
            if 'tamil' in label:allowed=allowed or 0x0B80<=number<=0x0BFF
            if not allowed:return False
        elif 'tamil' in label:
            if not ('LATIN' in name or 0x0B80<=number<=0x0BFF):return False
        elif all(v in {'english','malay'} for v in label.split(' and ')):
            if 'LATIN' not in name:return False
    return True

def writing_instructions(language,style):
    if style=='romanised':
        return ('Write the reply using Latin letters only; keep ordinary punctuation and emoji. '
                'No Chinese, Tamil, Japanese or invented characters. Use simple familiar spelling, '
                'without specialist tone marks. For Singapore Hokkien/Teochew, use readable informal '
                'romanisation rather than rare literary characters. If uncertain, ask a short clarification '
                'in plain English; do not fabricate dialect words.')
    return ('Match the selected writing system. For Chinese use common readable conversational '
            'characters and the selected Simplified/Traditional form. Do not introduce rare dialect '
            'glyphs, private-use characters or unrelated scripts. If unsure about a dialect, clarify '
            'instead of producing obscure characters.')
