"""
MinHash LSH deduplication for social media posts.
Prevents bot-amplified mass-retweets from inflating corroboration scores.
"""
from datasketch import MinHash, MinHashLSH
import re
import structlog

logger = structlog.get_logger()

# Global LSH index — shared across the process lifetime
_lsh: MinHashLSH | None = None
_minhashes: dict[str, MinHash] = {}

SIMILARITY_THRESHOLD = 0.85  # posts with jaccard similarity ≥ this are considered duplicates
NUM_PERM = 128


def _get_lsh() -> MinHashLSH:
    global _lsh
    if _lsh is None:
        _lsh = MinHashLSH(threshold=SIMILARITY_THRESHOLD, num_perm=NUM_PERM)
    return _lsh


def _tokenise(text: str) -> set[str]:
    """Produce a word-level token set; strips URLs, mentions, hashtags."""
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#(\w+)", r"\1", text)
    tokens = re.findall(r"\b\w{3,}\b", text.lower())
    return set(tokens)


def _make_minhash(text: str) -> MinHash:
    m = MinHash(num_perm=NUM_PERM)
    for token in _tokenise(text):
        m.update(token.encode("utf-8"))
    return m


def is_duplicate(text: str, post_id: str) -> bool:
    """
    Returns True if `text` is a near-duplicate of a previously seen post.
    Also registers the post in the index (side-effect).
    """
    lsh = _get_lsh()
    m = _make_minhash(text)

    try:
        matches = lsh.query(m)
    except Exception:
        matches = []

    if matches:
        logger.debug("Duplicate social post detected", post_id=post_id, matches=matches[:3])
        return True

    # Register in index
    try:
        lsh.insert(post_id, m)
        _minhashes[post_id] = m
    except ValueError:
        pass  # already inserted

    return False


def similarity_score(text_a: str, text_b: str) -> float:
    """Compute jaccard similarity between two texts (for scoring, not gating)."""
    m_a = _make_minhash(text_a)
    m_b = _make_minhash(text_b)
    return m_a.jaccard(m_b)


def reset_index() -> None:
    """Clear the LSH index — used between demo runs."""
    global _lsh, _minhashes
    _lsh = None
    _minhashes = {}
