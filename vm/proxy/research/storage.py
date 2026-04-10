import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from Levenshtein import ratio as lev_ratio

from proxy.research.validators import SecurityValidator

log = logging.getLogger("hermes.research.storage")


class ResearchStore:
    def __init__(self, data_path: str, security: SecurityValidator):
        self._path = Path(data_path)
        self._path.mkdir(parents=True, exist_ok=True)
        self._security = security
        self._index_path = self._path / "index.json"
        self._index: dict = self._load_index()

    def save(self, topic: str, report_text: str, sources: list,
             kb_snapshot: dict, metadata: dict) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        date_prefix = timestamp[:10]
        slug = self._security.sanitize_filename(topic)
        filename = f"{date_prefix}-{slug}.json"
        filepath = self._path / filename
        payload = {
            "title": topic,
            "timestamp": timestamp,
            "report_text": report_text,
            "sources": sources,
            "knowledge_base_snapshot": kb_snapshot,
            "metadata": metadata,
            "source_count": len(sources),
        }
        filepath.write_text(json.dumps(payload, indent=2))
        self._index[topic.lower()] = str(filepath)
        self._save_index()
        log.info("Saved research report: %s", filename)
        return str(filepath)

    def load_by_title(self, title: str) -> "dict | None":
        title_lower = title.lower()
        # Exact match first
        if title_lower in self._index:
            return self._load_file(self._index[title_lower])
        # Fuzzy match
        best_score = 0.0
        best_path = None
        for key, path in self._index.items():
            score = lev_ratio(title_lower, key)
            if score > best_score:
                best_score = score
                best_path = path
        if best_score >= 0.70 and best_path:
            return self._load_file(best_path)
        return None

    def list_reports(self) -> list:
        reports = []
        for title, path in self._index.items():
            try:
                data = json.loads(Path(path).read_text())
                reports.append({
                    "title": data.get("title", title),
                    "timestamp": data.get("timestamp", ""),
                    "source_count": data.get("source_count", 0),
                    "filepath": path,
                })
            except Exception:
                pass
        return reports

    def _load_file(self, path: str) -> "dict | None":
        try:
            return json.loads(Path(path).read_text())
        except Exception:
            return None

    def _load_index(self) -> dict:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except Exception:
                pass
        return {}

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2))
