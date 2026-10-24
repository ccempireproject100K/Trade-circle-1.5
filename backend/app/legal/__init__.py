"""The public legal pages: /privacy and /terms.

The texts live beside this module (privacy.md, terms.md), carried over verbatim
from the drafts prepared for the site. Only the document body is published —
everything above the document's own "# Privacy Policy" / "# Terms of Service"
heading is drafting notes, not policy. The bracketed blanks in the drafts are
resolved here from the app settings, never rendered as-is:

- [EFFECTIVE DATE] -> UPDATED below.
- [OWNER NAME / BUSINESS ENTITY] -> settings.legal_entity (TC_LEGAL_ENTITY).
- [SUPPORT EMAIL] / [MAILING ADDRESS] -> settings.legal_email /
  settings.legal_address (TC_LEGAL_EMAIL / TC_LEGAL_ADDRESS). While either is
  unset, its contact line is left out entirely rather than shown blank, and
  the one mid-sentence use ("Tell us promptly at ...") drops the phrase.
- [GOVERNING STATE ...] -> GOVERNING_STATE; [OWNER: county/state courts ...]
  -> VENUE.
- [OWNER/ATTORNEY: ...] drafting flags are removed; the sentences around them
  keep the drafts' existing conservative wording unchanged.

If any bracketed token survives resolution, rendering raises instead of
publishing a placeholder (tests assert both documents resolve cleanly).
"""
import html
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
UPDATED = "October 23, 2026"
GOVERNING_STATE = "Texas"
VENUE = "Tarrant County, Texas"

_DOCS = {"privacy": ("privacy.md", "# Privacy Policy"), "terms": ("terms.md", "# Terms of Service")}
_sources: dict[str, str] = {}


def _source(name: str) -> str:
    if name not in _sources:
        filename, heading = _DOCS[name]
        text = (_HERE / filename).read_text(encoding="utf-8")
        start = text.index(heading)
        _sources[name] = text[start:]
    return _sources[name]


def _resolve(name: str, settings) -> str:
    text = _source(name)
    email = (settings.legal_email or "").strip()
    address = (settings.legal_address or "").strip()
    if email:
        text = text.replace("[SUPPORT EMAIL]", email)
    else:
        # No public inbox yet: drop the contact line and the one mid-sentence
        # phrase ("Tell us promptly at **[SUPPORT EMAIL]** if ...") cleanly.
        text = re.sub(r"^Email: \*\*\[SUPPORT EMAIL\]\*\*\n", "", text, flags=re.M)
        text = text.replace(" at **[SUPPORT EMAIL]**", "")
    if address:
        text = text.replace("[MAILING ADDRESS]", address)
    else:
        text = re.sub(r"^Mailing address: \*\*\[MAILING ADDRESS\]\*\*\n", "", text, flags=re.M)
    text = text.replace("[OWNER NAME / BUSINESS ENTITY]", settings.legal_entity)
    text = text.replace("[EFFECTIVE DATE]", UPDATED)
    text = text.replace("[GOVERNING STATE — expected: Texas]", GOVERNING_STATE)
    text = text.replace("[OWNER: county/state courts — e.g., Tarrant County, Texas]", VENUE)
    # Drafting flags for the owner/attorney, not policy text. The liability
    # flag follows an em dash ("... the law allows — **[flag]**)"); removing
    # the dash with it keeps the sentence (and its conservative cap wording).
    text = re.sub(r"\s+—\s+\*\*\[(?:OWNER/ATTORNEY|OWNER)[^\]]*\]\*\*", "", text)
    text = re.sub(r"\s*\*\*\[(?:OWNER/ATTORNEY|OWNER)[^\]]*\]\*\*", "", text)
    leftovers = re.findall(r"\[[^\]\n]+\](?!\()", text)
    if leftovers:
        raise ValueError(f"{name}: unresolved placeholders {leftovers}")
    return text


def _inline(text: str) -> str:
    """Escape, then the two inline forms the drafts use: links and bold."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def render(name: str, settings) -> str:
    """One legal document as an HTML fragment: headings, lists, paragraphs."""
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal items
        if items is not None:
            blocks.append("<ul>\n" + "\n".join(f"<li>{_inline(i)}</li>" for i in items) + "\n</ul>")
            items = None

    for raw in _resolve(name, settings).splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if line == "---":
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
            continue
        bullet = re.match(r"^-\s+(.*)$", line)
        if bullet:
            flush_paragraph()
            if items is None:
                items = []
            items.append(bullet.group(1))
            continue
        # A wrapped continuation line belongs to the block it follows.
        if items is not None:
            items[-1] += " " + line
        else:
            paragraph.append(line)
    flush_paragraph()
    flush_list()
    return "\n".join(blocks)
