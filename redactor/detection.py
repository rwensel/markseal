"""Pattern definitions and TSV-to-box detection."""
from __future__ import annotations

import csv
import io
import ipaddress
import math
import re

from performance_log import timed


PATTERNS = {
    'Emails': r"[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    'URLs': (
        r"(?:https?://|www\.|jdbc:[a-z][a-z0-9_-]*:)\S+"
        r"|(?<![\w@.-])(?:[a-z0-9-]+\.)+(?:com|org|net|io|local|internal)\b"
        r"|\blocalhost(?::\d+)?(?:/\S*)?"
    ),
    'IP addresses': r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    'Ticket IDs': r"\b[A-Z][A-Z0-9]{1,9}-\d+\b",
    'Paths': r"(?:[a-z]:\\|/home/|/users/|\\\\)\S+",
    'Hashes': r"\b[0-9a-f]{7,64}\b",
    'Secrets': (
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:gh[pousr]_|github_pat_|glpat-|sk_(?:live|test)_)[\w-]{12,}"
        r"|\bBearer\s+[\w./+=-]{16,}|-----\s*BEGIN [A-Z0-9 ]*PRIVATE KEY\s*-----"
    ),
    'Infrastructure': (
        r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+\.(?:ya?ml|tf(?:vars)?|kubeconfig|crt|pem|key|p12|pfx)\b"
        r"|(?<![\w.-])/(?:etc|run/secrets|var/run/secrets|vault|secrets|opt)/[\w./-]+"
        r"|\b[a-z][a-z0-9]{1,11}[-_.](?:prod(?:uction)?|stage|staging|dev|test|uat|qa|sandbox)"
        r"[-_.][a-z0-9][a-z0-9_.-]*"
        r"|\b(?-i:[A-Z]{2,6})[_-][a-z][a-z0-9]*(?:[_-][a-z0-9]+){2,}\b"
        r"|\b(?:dc\d{1,4}[a-z]{2,6}(?:_[a-z0-9]+)*"
        r"|[a-z]{1,6}\d{1,4}[-_][a-z]{2,8}(?:prod|stage|staging|dev|qa|uat|test))\b"
        r"|\binternal-[a-z0-9-]{8,}(?:\.[a-z0-9-]+)*\b"
        r"|\bdata\.(?-i:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b"
        r"|\b[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*){3,}\.(?:cron|enabled|endpoint|url|host|schema|quorum)\b"
        r"|\bJAVA_TOOL_OPTIONS\b|(?<!\S)-XX:[^\s]+"
        r"|\b(?:VAULT|KUBE(?:RNETES)?|KAFKA|TLS|AWS|AZURE|GCP|DB|DATABASE|REDIS)"
        r"(?:\s*[_-]\s*[a-z0-9]+)+\b"
        r"|\b[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.(?:kafka|vault|kubernetes|tls|database)"
        r"(?:\.[a-z0-9_-]+)+\b"
        r"|\b(?:secret[_-]?name|secret[_-]?key[_-]?ref|config[_-]?map[_-]?ref|"
        r"cluster[_-]?name|namespace|service[_-]?account[_-]?name)\s*:\s*[\w.-]+"
        r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:svc(?:\.cluster\.local)?|corp|intranet)\b"
        r"|\barn:[a-z0-9-]+:[^\s,]+"
    ),
    'Long identifiers': r"\b[A-Za-z0-9_/-]{24,}\b",
}
PRESETS = {
    'Focused': {'Emails', 'URLs', 'IP addresses', 'Secrets', 'Infrastructure'},
    'Balanced': set(PATTERNS) - {'Long identifiers'},
    'Broad': set(PATTERNS),
}

CREDENTIAL_FIELD = re.compile(
    r"(?:password|passwd|passphrase|bearer\s+token|authorization|(?:api|access)[ _-]?key|"
    r"(?:access|auth|refresh)[ _-]?token|client[ _-]?secret|private[ _-]?key(?:\s+marker)?)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT = re.compile(
    r"(?<![\w.-])(?:[\w.-]*[_-])?(?:bearer\s+token|authorization|token|password|passwd|"
    r"passphrase|secret|api[_ -]?key|access[_ -]?key(?:[_-]?id)?|private[_ -]?key|"
    r"client[_ -]?secret|secret[_ -]?name)\s*[:=]\s*"
    r'(?P<value>"[^"]+"|\'[^\']+\'|Bearer\s+[^\s,}]+|[^\s,}]+)',
    re.IGNORECASE,
)


def credential_boxes(lines, size, min_confidence):
    """Match a credential label with the nearest distinct value on the same visual row."""
    groups = []
    for words in lines:
        parts = []
        for word in words:
            if not parts:
                parts.append([word])
                continue
            previous = parts[-1][-1]
            max_gap = max(12, min(word[4]-word[2], previous[4]-previous[2]))
            if word[1] - previous[3] > max_gap:
                parts.append([word])
            else:
                parts[-1].append(word)
        for part in parts:
            box = (min(w[1] for w in part), min(w[2] for w in part),
                   max(w[3] for w in part), max(w[4] for w in part))
            groups.append((' '.join(w[0] for w in part), box, max(w[5] for w in part)))

    result = []
    for text, (_, top, right, bottom), confidence in groups:
        label = text.removesuffix(':').strip()
        if confidence < min_confidence or CREDENTIAL_FIELD.fullmatch(label) is None:
            continue
        height = bottom - top
        candidates = []
        for value, bounds, score in groups:
            x1, y1, x2, y2 = bounds
            vertical_overlap = min(bottom, y2) - max(top, y1)
            if (score >= min_confidence and 0 <= x1-right <= 14*height
                    and vertical_overlap >= .55*min(height, y2-y1)):
                candidates.append((value, bounds))
        if not candidates:
            continue
        value, (x1, y1, x2, y2) = min(candidates, key=lambda item: item[1][0])
        if CREDENTIAL_FIELD.fullmatch(value.removesuffix(':').strip()):
            continue
        if label.lower().startswith('private'):
            marker = re.fullmatch(r"(-{0,5})(?:BEGIN|END) (?:[A-Z0-9]+ )*PRIVATE KEY(-{0,5})",
                                  value, re.IGNORECASE)
            if marker is None:
                continue
            # A photographed PEM marker may lose leading/trailing dashes in OCR.
            # Estimate only those expected characters and stay clear of the label.
            char_width = math.ceil((x2-x1) / len(value))
            x1 = max(right+5, x1-(5-len(marker[1]))*char_width)
            x2 += (5-len(marker[2]))*char_width
        result.append((max(0,x1-4), max(0,y1-4), min(size[0],x2+4), min(size[1],y2+4)))
    return result


def learned_pattern_rules(learned_patterns):
    for item in learned_patterns:
        if isinstance(item, str):
            if item:
                yield 'Blocked pattern', item
            continue
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        label, pattern = item
        if isinstance(pattern, str) and pattern:
            yield str(label or 'Blocked pattern'), pattern


_learned_pattern_rules = learned_pattern_rules


@timed('match_patterns')
def detect_regions(tsv, size, all_text=False, categories=None, min_confidence=0, custom_pattern='',
                   learned_patterns=(), rules=None):
    categories = set(PATTERNS) if categories is None else categories
    expressions = [(name, re.compile(PATTERNS[name], re.IGNORECASE))
                   for name in PATTERNS if name in categories]
    if custom_pattern:
        expressions.append(('Custom pattern', re.compile(custom_pattern, re.IGNORECASE)))
    expressions.extend((label, re.compile(pattern, re.IGNORECASE))
                       for label, pattern in learned_pattern_rules(learned_patterns))
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        word = row.get('text', '').strip()
        if not word: continue
        try:
            confidence = float(row['conf'])
            left, top, width, height = (int(row[k]) for k in ('left','top','width','height'))
            key = tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
        except (ValueError, KeyError): continue
        if width <= 0 or height <= 0: continue
        lines.setdefault(key, []).append((word, left, top, left+width, top+height, confidence))
    boxes = []
    box_rules = {}
    assignments = []
    for words in lines.values():
        text = ' '.join(word[0] for word in words)
        spans = []
        if all_text:
            spans = [(0, len(text), 'All text')]
        else:
            for label, expression in expressions:
                spans.extend((m.start(), m.end(), label)
                             for m in expression.finditer(text) if m.end() > m.start())
        fields = [(match.span('value'), []) for match in SECRET_ASSIGNMENT.finditer(text)] if (
            not all_text and 'Secrets' in categories) else []
        offset = 0
        for word, x1, y1, x2, y2, confidence in words:
            start, end = offset, offset + len(word)
            for (left, right), field_words in fields:
                if start < right and end > left:
                    field_words.append((x1, y1, x2, y2, confidence))
            matched = []
            if confidence >= min_confidence:
                for left, right, label in spans:
                    if start < right and end > left and label not in matched:
                        matched.append(label)
            if matched:
                box = (max(0,x1-4), max(0,y1-4), min(size[0],x2+4), min(size[1],y2+4))
                if box not in box_rules:
                    box_rules[box] = []
                    boxes.append(box)
                for label in matched:
                    if label not in box_rules[box]:
                        box_rules[box].append(label)
            offset = end + 1
        for _, field_words in fields:
            if field_words and max(word[4] for word in field_words) >= min_confidence:
                x1, y1, x2, y2 = zip(*(word[:4] for word in field_words))
                assignments.append((max(0, min(x1)-4), max(0, min(y1)-4),
                                    min(size[0], max(x2)+4), min(size[1], max(y2)+4)))
    if not all_text and 'Secrets' in categories:
        credentials = credential_boxes(lines.values(), size, min_confidence)
        for source in (assignments, credentials):
            for left, top, right, bottom in source:
                covered = [box for box in boxes if
                           (left <= box[0] and top <= box[1] and box[2] <= right and box[3] <= bottom)]
                for box in covered:
                    boxes.remove(box)
                    box_rules.pop(box, None)
                box = (left, top, right, bottom)
                boxes.append(box)
                box_rules[box] = ['Secrets']
    if rules is not None:
        rules.clear()
        rules.update({box: tuple(labels) for box, labels in box_rules.items()})
    return boxes


def pattern_from_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    patterns = []
    for line in lines:
        words = line.split()
        body = r'\s+'.join(re.escape(word) for word in words)
        if re.match(r'\w', words[0]):
            body = r'\b' + body
        if re.search(r'\w$', words[-1]):
            body += r'\b'
        patterns.append(body)
    patterns.sort(key=len, reverse=True)
    return patterns[0] if len(patterns) == 1 else '(?:' + '|'.join(patterns) + ')'


_IPV4_OCTET = r'(?:25[0-5]|2[0-4]\d|1?\d?\d)'
_IPV4_ADDRESS = rf'(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}'
_IPV6_ADDRESS = (
    r'(?:'
    r'(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,7}:|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}|'
    r'[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}|'
    r':(?::[0-9A-Fa-f]{1,4}){1,7}|'
    r'::|'
    rf'::(?:ffff(?::0{{1,4}})?:)?{_IPV4_ADDRESS}'
    r')'
)
PATTERN_TYPE_LABELS = {
    'ipv4': 'Any IPv4 address',
    'ipv4_cidr': 'Any IPv4 CIDR range',
    'ipv6': 'Any IPv6 address',
    'ipv6_cidr': 'Any IPv6 CIDR range',
    'integer': 'Any integer',
    'uuid': 'Any UUID',
    'email': 'Any email address',
    'url': 'Any URL',
    'hex': 'Any long hex token',
    'mac': 'Any MAC address',
    'date': 'Any ISO date',
}
PATTERN_TYPE_EXPRESSIONS = {
    'ipv4': rf'(?<![\w.]){_IPV4_ADDRESS}(?![\w.])',
    'ipv4_cidr': rf'(?<![\w.]){_IPV4_ADDRESS}/(?:3[0-2]|[12]?\d)(?![\w.])',
    'ipv6': rf'(?<![0-9A-Za-z:]){_IPV6_ADDRESS}(?![0-9A-Za-z:])',
    'ipv6_cidr': rf'(?<![0-9A-Za-z:]){_IPV6_ADDRESS}/(?:12[0-8]|1[01]\d|[1-9]?\d)(?![0-9A-Za-z:])',
    'integer': r'(?<![\w.])[-+]?\d+(?![\w.])',
    'uuid': r'\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b',
    'email': r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',
    'url': r'(?<![\w])https?://[^\s"\'<>]+',
    'hex': r'\b[0-9A-Fa-f]{8,64}\b',
    'mac': r'\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b',
    'date': r'\b\d{4}-\d{2}-\d{2}\b',
}


def value_pattern_types(text):
    value = text.strip()
    if not value:
        return []
    kinds = []
    try:
        if '/' in value:
            network = ipaddress.ip_network(value, strict=False)
            kinds.append('ipv4_cidr' if network.version == 4 else 'ipv6_cidr')
        else:
            address = ipaddress.ip_address(value)
            kinds.append('ipv4' if address.version == 4 else 'ipv6')
    except ValueError:
        pass
    for kind, expression in PATTERN_TYPE_EXPRESSIONS.items():
        if kind in ('ipv4', 'ipv4_cidr', 'ipv6', 'ipv6_cidr'):
            continue
        if re.fullmatch(expression, value):
            kinds.append(kind)
    return kinds


def value_pattern_expression(text, kind):
    if kind == 'fixed':
        return pattern_from_text(text)
    return PATTERN_TYPE_EXPRESSIONS.get(kind, pattern_from_text(text))
