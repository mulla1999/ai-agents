"""Text helpers: HTML to plain text, normalisation, canonical URLs and similarity."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "header"}
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._hidden = 0
        self.hidden_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style or dict(attrs).get("hidden") is not None:
            self._hidden += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._hidden:
            # Hidden text is a classic carrier for instructions aimed at an AI; keep it aside so the
            # safety scan can see it, but never show or use it as job content.
            self.hidden_text.append(data)
            return
        self.parts.append(data)


def looks_like_html(text: str) -> bool:
    return bool(re.search(r"<(p|div|br|li|ul|span|strong|h\d)\b", text, re.IGNORECASE)) or "&lt;" in text


def html_to_text(raw: str) -> tuple[str, str]:
    """Return (visible text, hidden text). Input may be HTML-escaped HTML (Greenhouse does this)."""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    if not looks_like_html(raw):
        return clean_whitespace(raw), ""
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    return clean_whitespace("".join(parser.parts)), clean_whitespace(" ".join(parser.hidden_text))


def clean_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r", "")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", value)).strip()


_COMPANY_SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|inc|llc|llp|corp|corporation|co|technologies|technology|solutions|software|labs|india)\b"
)


def normalize_company(value: str) -> str:
    return re.sub(r"\s+", " ", _COMPANY_SUFFIXES.sub(" ", normalize(value))).strip() or normalize(value)


_TITLE_NOISE = re.compile(r"\b(m f d|f m d|all genders|immediate joiner|urgent|hiring|remote|hybrid|onsite)\b")


def normalize_title(value: str) -> str:
    value = re.sub(r"\(.*?\)", " ", value)
    return re.sub(r"\s+", " ", _TITLE_NOISE.sub(" ", normalize(value))).strip()


_TRACKING_PARAMS = re.compile(r"^(utm_.*|ref|refid|trk|trackingid|src|source|gh_src|lever-source.*|fbclid|gclid|mc_.*)$", re.I)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _TRACKING_PARAMS.match(k)]
    path = re.sub(r"/+$", "", parts.path) or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(sorted(query)), ""))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shingles(text: str, size: int = 5) -> set[str]:
    words = normalize(text).split()
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or our the their this to we will with you your "
    "who what when where which while work working team teams role using use used build building strong experience "
    "ability skills knowledge good great excellent across within including etc years year plus new".split()
)


def keywords(text: str) -> set[str]:
    return {w for w in normalize(text).split() if len(w) > 2 and w not in _STOPWORDS and not w.isdigit()}


def slug(value: str, max_len: int = 60) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-") or "unknown")[:max_len]


def resume_filename(name: str | None, suffix: str = ".pdf") -> str:
    """The standard ATS file name: First_Last_Resume.pdf (letters only, words joined by _)."""
    words = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)?", unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode())
    if words and all(w.isupper() for w in words):  # "PRIYA ANIL SHARMA" → "Priya_Anil_Sharma"
        words = [w.capitalize() for w in words]
    stem = "_".join(words[:4]) or "Candidate"
    return f"{stem}_Resume{suffix if suffix.startswith('.') else '.' + suffix}"


def format_phone(phone: str | None) -> str | None:
    """Indian mobile numbers as +91 98765 43210; anything else as written."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91 {digits[:5]} {digits[5:]}"
    return phone.strip()


def full_url(link: str | None) -> str | None:
    """linkedin.com/in/x → https://linkedin.com/in/x"""
    if not link:
        return None
    link = link.strip()
    return link if re.match(r"https?://", link) else "https://" + link.lstrip("/")
