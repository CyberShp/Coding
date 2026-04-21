"""
Multi-strategy extraction engine (Phase 3).

6 strategies:
  pipe   — Shell-like pipeline: grep → split → index
  kv     — Key-value pair parsing (key=value or "key: value")
  json   — JSONPath extraction
  table  — Column header-based extraction
  lines  — Line-by-line pattern match + count
  diff   — Compare with previous value, detect change
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from jsonpath_ng import parse as _jsonpath_parse
    HAS_JSONPATH = True
except ImportError:
    HAS_JSONPATH = False


@dataclass
class ExtractionResult:
    success: bool
    value: Any                        # extracted value — str, float, int, list, dict, or None
    raw_output: str                   # original command output (may be truncated for storage)
    error: Optional[str] = None       # extraction error message
    metadata: Dict[str, Any] = field(default_factory=dict)  # strategy-specific context


class ExtractionEngine:
    """
    Stateful extraction engine.  Each instance should be held by one observer
    so that 'diff' strategy can store previous values across check cycles.
    """

    def __init__(self):
        self._prev_values: Dict[str, Any] = {}   # keyed by (observer_name, key)

    # ── Public entry point ─────────────────────────────────────────────────

    def extract(
        self,
        strategy: str,
        raw_output: str,
        config: Dict[str, Any],
        state_key: str = "",
    ) -> ExtractionResult:
        """
        Run the named strategy against raw_output.

        :param strategy:    One of: pipe | kv | json | table | lines | diff
        :param raw_output:  The command's stdout (already captured as a string)
        :param config:      Strategy-specific configuration dict
        :param state_key:   Unique key for stateful strategies (e.g. observer name)
        """
        fn = {
            "pipe": self._pipe,
            "kv": self._kv,
            "json": self._json,
            "table": self._table,
            "lines": self._lines,
            "diff": self._diff,
        }.get(strategy)

        if fn is None:
            return ExtractionResult(
                success=False, value=None, raw_output=raw_output[:500],
                error=f"Unknown strategy: {strategy!r}",
            )

        try:
            return fn(raw_output, config, state_key)
        except Exception as exc:
            logger.debug("Extraction error (%s): %s", strategy, exc)
            return ExtractionResult(
                success=False, value=None, raw_output=raw_output[:500],
                error=str(exc),
            )

    # ── pipe ───────────────────────────────────────────────────────────────

    def _pipe(self, output: str, cfg: Dict, _key: str) -> ExtractionResult:
        """
        Apply a chain of text transforms.

        cfg:
          steps: list of step dicts, applied in order.

        Each step is one of:
          {"grep": "pattern"}           — keep lines matching pattern (regex)
          {"split": " "}               — split the first surviving line by sep
          {"index": N}                 — take element N from list (may be negative)
          {"strip": true}              — strip whitespace from current value
          {"regex": "(\d+)"}           — extract first capture group
        """
        steps: List[Dict] = cfg.get("steps", [])
        current: Any = output

        for step in steps:
            if "grep" in step:
                pattern = step["grep"]
                if isinstance(current, str):
                    lines = [l for l in current.splitlines() if re.search(pattern, l)]
                    current = "\n".join(lines)
            elif "split" in step:
                sep = step["split"] or None  # None → any whitespace
                if isinstance(current, str):
                    first_line = current.strip().splitlines()[0] if current.strip() else ""
                    current = first_line.split(sep) if sep else first_line.split()
            elif "index" in step:
                idx = int(step["index"])
                if isinstance(current, list):
                    current = current[idx] if -len(current) <= idx < len(current) else None
            elif step.get("strip"):
                if isinstance(current, str):
                    current = current.strip()
            elif "regex" in step:
                pattern = step["regex"]
                src = current if isinstance(current, str) else str(current)
                m = re.search(pattern, src)
                current = m.group(1) if m and m.lastindex else (m.group(0) if m else None)

        return ExtractionResult(success=current is not None, value=current, raw_output=output[:500])

    # ── kv ────────────────────────────────────────────────────────────────

    def _kv(self, output: str, cfg: Dict, _key: str) -> ExtractionResult:
        """
        Parse key-value pairs and return the value for the requested key.

        cfg:
          key:       the key to look up (required)
          sep:       separator string, default auto-detect (= or :)
          numeric:   if true, cast value to float
        """
        target_key: str = cfg.get("key", "")
        sep: Optional[str] = cfg.get("sep")
        numeric: bool = cfg.get("numeric", False)

        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Try explicit separator, then auto-detect = then :
            separators = [sep] if sep else ["=", ":"]
            for s in separators:
                if s in line:
                    k, _, v = line.partition(s)
                    k = k.strip()
                    v = v.strip()
                    if k.lower() == target_key.lower():
                        if numeric:
                            try:
                                v = float(v)
                            except ValueError:
                                pass
                        return ExtractionResult(
                            success=True, value=v, raw_output=output[:500],
                            metadata={"key": k, "raw_value": v},
                        )
                    break

        return ExtractionResult(
            success=False, value=None, raw_output=output[:500],
            error=f"Key {target_key!r} not found",
        )

    # ── json ───────────────────────────────────────────────────────────────

    def _json(self, output: str, cfg: Dict, _key: str) -> ExtractionResult:
        """
        Extract a value using a JSONPath expression.

        cfg:
          path:  JSONPath expression (e.g. "$.status" or "$.items[0].value")
          first: if true (default), return only the first match
        """
        path: str = cfg.get("path", "$")
        first: bool = cfg.get("first", True)

        try:
            data = json.loads(output.strip())
        except json.JSONDecodeError as e:
            return ExtractionResult(
                success=False, value=None, raw_output=output[:500], error=f"JSON parse error: {e}"
            )

        if not HAS_JSONPATH:
            # Fallback: simple dot-path for "$.key.subkey" patterns
            parts = [p for p in path.replace("$", "").split(".") if p]
            current = data
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    current = None
                    break
            return ExtractionResult(success=current is not None, value=current, raw_output=output[:500])

        expr = _jsonpath_parse(path)
        matches = [m.value for m in expr.find(data)]
        if not matches:
            return ExtractionResult(success=False, value=None, raw_output=output[:500], error="No matches")
        value = matches[0] if first else matches
        return ExtractionResult(success=True, value=value, raw_output=output[:500])

    # ── table ──────────────────────────────────────────────────────────────

    def _table(self, output: str, cfg: Dict, _key: str) -> ExtractionResult:
        """
        Extract a column value from tabular output.

        cfg:
          column:    header name to find (case-insensitive partial match)
          row:       which data row to use, 0-indexed (default 0)
          delimiter: column delimiter (default: any whitespace)
        """
        col_name: str = cfg.get("column", "")
        row_idx: int = cfg.get("row", 0)
        delimiter: Optional[str] = cfg.get("delimiter")

        lines = [l for l in output.splitlines() if l.strip()]
        if len(lines) < 2:
            return ExtractionResult(
                success=False, value=None, raw_output=output[:500],
                error="Table has fewer than 2 lines (header + data)",
            )

        # Find header line (first line that contains col_name)
        header_line = lines[0]
        if delimiter:
            headers = [h.strip() for h in header_line.split(delimiter)]
        else:
            headers = header_line.split()

        col_idx = None
        for i, h in enumerate(headers):
            if col_name.lower() in h.lower():
                col_idx = i
                break
        if col_idx is None:
            return ExtractionResult(
                success=False, value=None, raw_output=output[:500],
                error=f"Column {col_name!r} not found in header: {headers}",
            )

        data_lines = lines[1:]
        if row_idx >= len(data_lines):
            return ExtractionResult(
                success=False, value=None, raw_output=output[:500],
                error=f"Row index {row_idx} out of range (only {len(data_lines)} data rows)",
            )

        if delimiter:
            cols = [c.strip() for c in data_lines[row_idx].split(delimiter)]
        else:
            cols = data_lines[row_idx].split()

        value = cols[col_idx] if col_idx < len(cols) else None
        return ExtractionResult(
            success=value is not None, value=value, raw_output=output[:500],
            metadata={"column": col_name, "col_idx": col_idx},
        )

    # ── lines ──────────────────────────────────────────────────────────────

    def _lines(self, output: str, cfg: Dict, _key: str) -> ExtractionResult:
        """
        Count lines matching a pattern, or return the Nth matching line.

        cfg:
          pattern:  regex pattern to match against each line
          mode:     "count" (default) | "first" | "all"
          group:    capture group index to extract (only for "first"/"all")
        """
        pattern: str = cfg.get("pattern", "")
        mode: str = cfg.get("mode", "count")
        group: Optional[int] = cfg.get("group")

        if not pattern:
            return ExtractionResult(
                success=False, value=None, raw_output=output[:500], error="pattern required"
            )

        matched = []
        for line in output.splitlines():
            m = re.search(pattern, line)
            if m:
                if group is not None:
                    try:
                        matched.append(m.group(group))
                    except IndexError:
                        matched.append(m.group(0))
                else:
                    matched.append(line.strip())

        if mode == "count":
            return ExtractionResult(
                success=True, value=len(matched), raw_output=output[:500],
                metadata={"pattern": pattern, "matched_count": len(matched)},
            )
        if mode == "first":
            value = matched[0] if matched else None
            return ExtractionResult(success=value is not None, value=value, raw_output=output[:500])
        if mode == "all":
            return ExtractionResult(success=bool(matched), value=matched, raw_output=output[:500])

        return ExtractionResult(success=False, value=None, raw_output=output[:500],
                                error=f"Unknown mode: {mode!r}")

    # ── diff ───────────────────────────────────────────────────────────────

    def _diff(self, output: str, cfg: Dict, state_key: str) -> ExtractionResult:
        """
        Detect if the output value changed from the previous cycle.

        cfg:
          alert_on:  "value_changed" (default) | "value_increased" | "value_decreased"
          normalize: if true, strip whitespace before comparison
        """
        alert_on: str = cfg.get("alert_on", "value_changed")
        normalize: bool = cfg.get("normalize", True)

        current = output.strip() if normalize else output

        prev = self._prev_values.get(state_key)
        self._prev_values[state_key] = current

        changed = (prev is not None) and (prev != current)

        if alert_on == "value_changed":
            triggered = changed
        elif alert_on == "value_increased":
            try:
                triggered = changed and float(current) > float(prev)
            except (ValueError, TypeError):
                triggered = changed
        elif alert_on == "value_decreased":
            try:
                triggered = changed and float(current) < float(prev)
            except (ValueError, TypeError):
                triggered = changed
        else:
            triggered = changed

        return ExtractionResult(
            success=True,
            value=current,
            raw_output=output[:500],
            metadata={
                "triggered": triggered,
                "previous": prev,
                "current": current,
                "alert_on": alert_on,
            },
        )
