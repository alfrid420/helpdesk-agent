"""Detection rules shared by the input guard (user text) and the tool guard (retrieved text).

Text is normalized first (Unicode folding, zero-width stripping, homoglyphs, leetspeak) and
encoded blobs (base64 / hex / percent-encoding / rot13) are decoded and re-scanned, so trivial
obfuscation does not slip past the patterns.
"""
from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass

# --- normalization ---------------------------------------------------------------------------

_CONFUSABLES = str.maketrans(
    {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "і": "i", "ѕ": "s", "ԁ": "d", "ν": "v"}
)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("Cf", "Mn"))
    t = t.translate(_CONFUSABLES)
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    return re.sub(r"\s+", " ", t).strip().lower()


def deleet(text: str) -> str:
    return text.translate(_LEET)


# --- rules -----------------------------------------------------------------------------------

_NOUN_OBJ = r"(?:instructions?|prompts?|rules|guidelines|directives|restrictions|guardrails|programming|constraints|safeguards|filters)"
_DATA_NOUN = r"(?:emails?|e-mails?|phones?|phone numbers?|salary|salaries|addresses|address|ssn|social security|profiles?|records|personal|contact|passwords?|balances?|details|information|data)"
_EMP_NOUN = r"(?:employees?|staff|people|users?|workers?|colleagues?|members?|everyone|everybody)"

_RULES: list[tuple[str, str, str]] = [
    # --- instruction override
    ("instruction_override", "ignore_previous",
     rf"\b(?:ignore|disregard|forget|override|bypass|discard|neglect)\b(?:\W+\w+){{0,5}}?\W+{_NOUN_OBJ}\b"),
    ("instruction_override", "ignore_above",
     r"\b(?:ignore|disregard|forget)\b (?:the |all |everything )?(?:above|previous|prior|preceding|earlier)\b"),
    ("instruction_override", "forget_everything",
     r"\b(?:forget|disregard|ignore)\b[^.?!]{0,20}\b(?:everything|anything)\b[^.?!]{0,30}\b(?:told|said|instructed|before|above|earlier|previously)\b"),
    ("instruction_override", "new_instructions",
     r"\b(?:new|updated|real|actual|secret) (?:instructions?|rules|directives?)\b(?: (?:are|is))?\s*[:\-]"),
    ("instruction_override", "from_now_on",
     r"\bfrom (?:now|this point) on\b[^.]{0,60}\b(?:you|your|ignore|act|respond|answer|always|never)\b"),
    ("instruction_override", "jailbreak_terms",
     r"\b(?:jailbreak(?:ed)?|dan mode|do anything now|developer mode|god mode|sudo mode|unrestricted mode)\b"),
    ("instruction_override", "disable_guards",
     r"\b(?:disable|turn off|deactivate|remove|switch off|lift)\b(?:\W+\w+){0,3}?\W+(?:guardrails?|safety|filters?|restrictions?|moderation|content polic(?:y|ies)|protections?)\b"),
    # --- role-play / persona override
    ("role_play_override", "you_are_now", r"\byou are (?:now|no longer)\b"),
    ("role_play_override", "act_as_privileged",
     r"\bact(?:ing)? as (?:if )?(?:an? |the )?(?:unrestricted|unfiltered|uncensored|jailbroken|evil|admin|administrator|root|superuser|system|developer|debug)\w*"),
    ("role_play_override", "pretend_no_rules",
     r"\b(?:pretend|imagine|suppose|roleplay|role-play|simulate)\b[^.]{0,80}\b(?:no (?:restrictions|rules|limits|guidelines|filters)|without (?:any )?(?:restrictions|rules|limits|filters)|unrestricted|unfiltered|uncensored|jailbroken|evil|debugbot|dan)\b"),
    ("role_play_override", "no_restrictions",
     r"\bwith(?:out)? no (?:restrictions|rules|limits|filters|guardrails)\b|\bwithout (?:any )?(?:restrictions|rules|limits|filters|guardrails)\b"),
    ("authority_claim", "claims_admin",
     r"\b(?:i am|i'm|this is|speaking as)\s+(?:the |an? |your )?(?:system |site |database |it )?(?:admin|administrator|developer|root|superuser|owner|operator|creator|anthropic|openai)\b"),
    # --- system prompt extraction
    ("prompt_extraction", "reveal_prompt",
     r"\b(?:reveal|show|print|repeat|display|output|tell|give|leak|dump|share|recite|paste|copy|disclose|expose|what(?:'s| is| are| were))\b[^.?!]{0,50}?\b(?:system|hidden|initial|original|developer|internal|secret) (?:prompt|message|instructions?|configuration|rules)\b"),
    ("prompt_extraction", "your_prompt", r"\b(?:your|the) (?:system|hidden|initial|original|internal|secret) (?:prompt|instructions?)\b"),
    ("prompt_extraction", "repeat_above",
     r"\brepeat (?:everything|all|the (?:text|words|content)) (?:above|before|prior)\b"),
    ("prompt_extraction", "what_were_you_told",
     r"\bwhat (?:were|are) you (?:told|instructed|programmed)\b|\bbeginning of (?:your|the) (?:prompt|conversation)\b"),
    # --- tool / SQL / code abuse
    ("tool_abuse", "sql_destructive", r"\b(?:drop|truncate|alter|delete)\s+(?:table|database|schema|from)\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b"),
    ("tool_abuse", "sql_injection", r"\bselect\s+\*\s+from\b|\bunion\s+(?:all\s+)?select\b|;\s*--|'\s*or\s*'?1'?\s*=\s*'?1"),
    ("tool_abuse", "run_sql_or_code",
     r"\b(?:execute|run|exec|perform|issue)\b(?:\W+\w+){0,3}?\W+(?:sql|queries|query|shell|bash|command|commands|script|code|statement)\b"),
    ("tool_abuse", "shell_code", r"\brm\s+-rf\b|\bsudo\s|\bchmod\s|os\.system|\bsubprocess\b|__import__|\beval\(|\bexec\("),
    ("tool_abuse", "call_destructive_tool",
     r"\b(?:call|invoke|trigger|execute|run|use)\b[^.?!]{0,30}\b(?:delete|drop|remove|wipe|erase|update|modify|insert|write|reset|exec|shell|admin)[\w-]*\s+(?:tool|function|endpoint|api|command)\b"),
    ("tool_abuse", "destructive_tool_name",
     r"\b(?:delete|drop|remove|update|modify|insert|write|reset|exec|execute|admin)_[a-z_]+\b"),
    ("tool_abuse", "bulk_destroy",
     r"\b(?:delete|remove|wipe|erase|purge)\b[^.?!]{0,30}\b(?:all|every|entire)\b[^.?!]{0,30}\b(?:employees?|records?|database|table|data|users?)\b"),
    ("tool_abuse", "spoof_identity",
     r"\b(?:set|change|switch|override|spoof|fake|forge)\b(?:\W+\w+){0,3}?\W+(?:requester|requester_id|authenticated (?:user|identity)|access level|authorization)\b"),
    ("tool_abuse", "impersonation",
     r"\bimpersonat\w+|\b(?:pretend to be|log ?in as|sign in as|acting as|act as|speaking as)\s+(?:employee\s+)?e\d{3}\b"),
    ("tool_abuse", "bypass_auth",
     r"\bbypass\w*\b[^.?!]{0,30}\b(?:auth\w*|access control|permission\w*|security|guard\w*)\b"),
    # --- bulk data exfiltration
    ("data_exfiltration", "bulk_personal_data",
     rf"\b(?:show|list|give|send|tell|print|dump|export|display|reveal|share|provide|get|fetch|retrieve|pull|email|read|compile|enumerate|output)\b[^.?!]{{0,30}}?\b(?:every|all|each)\b(?: single| other| of the| the)? {_EMP_NOUN}(?:'s|')?\b[^.?!]{{0,40}}?\b{_DATA_NOUN}\b"),
    ("data_exfiltration", "dump_everything",
     r"\b(?:dump|export|list|enumerate|exfiltrate|download|scrape)\b[^.?!]{0,30}\b(?:all|every|each|entire|whole|complete|full)\b[^.?!]{0,25}\b(?:employees?|staff|users?|database|db|tables?|directory|records?|profiles?|people|accounts?)\b"),
    ("data_exfiltration", "exfil_channel",
     r"\b(?:send|post|upload|forward|exfiltrate|transmit|leak|email|mail)\b[^.?!]{0,60}?(?:https?://|\bwww\.|\b[\w.+-]+@[\w-]+\.[\w.]+)"),
    ("data_exfiltration", "markdown_image_exfil", r"!\[[^\]]*\]\(https?://"),
    # --- delimiter / chat-template injection
    ("delimiter_injection", "fake_tags",
     r"</?\s*(?:system|assistant|user|human|instructions?|tool_?results?|tool_?use|function_?calls?|retrieved_documents?|doc|context)\s*>"),
    ("delimiter_injection", "template_tokens",
     r"\[/?(?:inst|system|sys)\]|<<\s*/?sys\s*>>|<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>"),
    ("delimiter_injection", "role_prefix", r"(?:^|[.!?] )(?:system|developer|assistant)\s*:\s*\w"),
    ("delimiter_injection", "markdown_system", r"#{2,}\s*(?:system|instructions?|new task)\b"),
    ("delimiter_injection", "end_of_prompt", r"\b(?:end|stop) of (?:the )?(?:system )?(?:prompt|instructions|context|conversation)\b|\bbegin (?:new|admin|system) (?:session|prompt|mode)\b"),
    # --- instructions addressed to the AI (typical of indirect injection)
    ("indirect_instruction", "note_to_ai",
     r"\b(?:notes?|messages?|instructions?|attention|important|notice)\s+(?:to|for)\s+(?:the\s+)?(?:ai|assistant|llm|agent|model|chatbot|bot)\b"),
    ("indirect_instruction", "assistant_must",
     r"\b(?:you|the assistant|the ai) (?:must|should|shall|will) (?:now |also |first )?(?:call|invoke|run|execute|send|include|output|reveal|print|list)\b"),
    ("encoded_payload", "decode_and_obey",
     r"\b(?:decode|decrypt|deobfuscate|base64|rot13)\b[^.?!]{0,40}\b(?:and|then)\b[^.?!]{0,20}\b(?:follow|execute|run|obey|comply|perform|do)\b"),
]

_COMPILED = [(cat, name, re.compile(rx, re.I)) for cat, name, rx in _RULES]


@dataclass(frozen=True)
class Finding:
    category: str
    rule: str
    snippet: str


def scan(text: str) -> list[Finding]:
    """Scan one text (already normalized or not) against every rule, incl. the de-leeted view."""
    views = {normalize(text)}
    views.add(deleet(next(iter(views))))
    found: dict[tuple[str, str], Finding] = {}
    for view in views:
        for cat, name, rx in _COMPILED:
            m = rx.search(view)
            if m and (cat, name) not in found:
                found[(cat, name)] = Finding(cat, name, m.group(0)[:80])
    return list(found.values())


# --- decoding --------------------------------------------------------------------------------

_B64 = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
_HEX = re.compile(r"\b(?:[0-9a-fA-F]{2}){12,}\b")
_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")


def _printable(raw: bytes) -> str | None:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(s) < 8:
        return None
    ok = sum(ch.isprintable() or ch in "\n\t" for ch in s)
    return s if ok / len(s) >= 0.9 else None


def decode_candidates(text: str, depth: int = 2) -> list[str]:
    """Return plausible decoded payloads hidden inside `text` (recursively, to `depth`)."""
    out: list[str] = []

    def add(s: str | None) -> None:
        if s and s not in out:
            out.append(s)

    for tok in _B64.findall(text):
        padded = tok + "=" * (-len(tok) % 4)
        for fn in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                add(_printable(fn(padded)))
                break
            except (binascii.Error, ValueError):
                continue
    for tok in _HEX.findall(text):
        try:
            add(_printable(bytes.fromhex(tok)))
        except ValueError:
            pass
    if len(_PERCENT.findall(text)) >= 3:
        add(urllib.parse.unquote(text))
    if "\\u" in text or "\\x" in text:
        try:
            add(text.encode("utf-8").decode("unicode_escape"))
        except (UnicodeDecodeError, ValueError):
            pass
    if "rot13" in text.lower() or "rot-13" in text.lower():
        add(codecs.decode(text, "rot13"))
    if depth > 1:
        for s in list(out):
            for inner in decode_candidates(s, depth - 1):
                add(inner)
    return out
