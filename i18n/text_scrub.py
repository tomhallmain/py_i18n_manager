import re


_CURLY_BRACE_SEGMENT = re.compile(r"\{[^{}]*\}")
_MARKUP_TAG_SEGMENT = re.compile(r"</?[A-Za-z][^>]*>")
_RUBY_PLACEHOLDER_SEGMENT = re.compile(r"%\{[^{}]+\}")
_PRINTF_PLACEHOLDER_SEGMENT = re.compile(
    r"%(?:\([^)]+\))?(?:\d+\$)?[#0\- +']*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrs]"
)


def scrub_dynamic_segments(text: str) -> str:
    """Remove placeholder/markup segments that should not count as language script content."""
    scrubbed = text or ""

    # Peel nested braces iteratively.
    prev = None
    while scrubbed != prev:
        prev = scrubbed
        scrubbed = _CURLY_BRACE_SEGMENT.sub("", scrubbed)

    scrubbed = _MARKUP_TAG_SEGMENT.sub("", scrubbed)
    scrubbed = _RUBY_PLACEHOLDER_SEGMENT.sub("", scrubbed)
    scrubbed = _PRINTF_PLACEHOLDER_SEGMENT.sub("", scrubbed)
    return scrubbed
