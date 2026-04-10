from Levenshtein import ratio as lev_ratio


class QueryManager:
    def __init__(self):
        self._pending: list = []
        self._used: set = set()
        self._cache: dict = {}

    def expand(self, topic: str) -> list:
        candidates = [
            topic,
            f"{topic} 2025",
            f"{topic} 2024",
            f"what is {topic}",
            f"how does {topic} work",
            f"{topic} explained",
            f"{topic} site:reddit.com",
            f"{topic} site:arxiv.org",
            f"{topic} site:reuters.com",
        ]
        added = []
        for q in candidates:
            if self._add(q):
                added.append(q)
        return added

    def add_from_gaps(self, gaps: list) -> list:
        added = []
        for q in gaps:
            if self._add(q):
                added.append(q)
        return added

    def _add(self, query: str) -> bool:
        if query in self._used or query in self._pending:
            return False
        if self.is_duplicate(query):
            return False
        self._pending.append(query)
        return True

    def next_batch(self, n: int = 5) -> list:
        batch = self._pending[:n]
        self._pending = self._pending[n:]
        for q in batch:
            self._used.add(q)
        return batch

    def is_duplicate(self, query: str) -> bool:
        q_lower = query.lower()
        for used in self._used:
            if lev_ratio(q_lower, used.lower()) >= 0.85:
                return True
        return False

    def cache_results(self, query: str, results: list) -> None:
        self._cache[query] = results

    def get_cached(self, query: str) -> "list | None":
        return self._cache.get(query)

    def mark_used(self, query: str) -> None:
        self._used.add(query)
        if query in self._pending:
            self._pending.remove(query)

    def pending_count(self) -> int:
        return len(self._pending)
