"""
F201: Natural Language Query SQL validation tests.

Covers string-literal false positives and real attack vectors.
"""

from backend.api.query import (
    _validate_nl_sql,
    _enforce_limit,
    _strip_string_literals,
    _extract_table_refs,
)


# ── String literal stripping ─────────────────────────────────

def test_strip_single_quoted():
    assert _strip_string_literals("where msg like '%drop%'") == "where msg like ''"


def test_strip_double_quoted():
    assert _strip_string_literals('where msg = "delete me"') == 'where msg = ""'


def test_strip_multiple_literals():
    sql = "where a = 'union' and b = 'insert'"
    assert _strip_string_literals(sql) == "where a = '' and b = ''"


def test_strip_preserves_keywords_outside_strings():
    sql = "select id from alerts where msg = 'safe' union select id from arrays"
    stripped = _strip_string_literals(sql)
    assert "union" in stripped  # real UNION still visible
    assert "'safe'" not in stripped


# ── False positive: keywords inside string literals ──────────

def test_like_drop_not_blocked():
    """WHERE message LIKE '%drop%' must NOT trigger DROP check."""
    sql = "SELECT id, message FROM alerts WHERE message LIKE '%drop%'"
    assert _validate_nl_sql(sql) is None


def test_like_delete_not_blocked():
    """WHERE message LIKE '%delete%' must NOT trigger DELETE check."""
    sql = "SELECT id, message FROM alerts WHERE message LIKE '%delete%'"
    assert _validate_nl_sql(sql) is None


def test_like_union_not_blocked():
    """WHERE message LIKE '%union%' must NOT trigger UNION check."""
    sql = "SELECT id, message FROM alerts WHERE message LIKE '%union%'"
    assert _validate_nl_sql(sql) is None


def test_like_password_not_blocked():
    """WHERE message LIKE '%password%' must NOT trigger column blacklist."""
    sql = "SELECT id, message FROM alerts WHERE message LIKE '%password%'"
    assert _validate_nl_sql(sql) is None


def test_string_literal_with_select():
    """String containing 'select' must NOT trigger subquery check."""
    sql = "SELECT id, message FROM alerts WHERE message = 'select all items'"
    assert _validate_nl_sql(sql) is None


# ── Real attacks still blocked ───────────────────────────────

def test_real_drop_blocked():
    sql = "SELECT id FROM alerts; DROP TABLE alerts"
    err = _validate_nl_sql(sql)
    assert err is not None
    assert "DROP" in err


def test_real_delete_blocked():
    sql = "DELETE FROM alerts WHERE id = 1"
    err = _validate_nl_sql(sql)
    assert err is not None


def test_real_union_blocked():
    sql = "SELECT id FROM alerts UNION SELECT id FROM arrays"
    err = _validate_nl_sql(sql)
    assert err is not None  # caught by subquery or UNION check


def test_real_subquery_blocked():
    sql = "SELECT id FROM alerts WHERE id IN (SELECT id FROM arrays)"
    err = _validate_nl_sql(sql)
    assert err is not None


def test_real_insert_blocked():
    sql = "INSERT INTO alerts (id) VALUES (1)"
    err = _validate_nl_sql(sql)
    assert err is not None


def test_select_star_blocked():
    sql = "SELECT * FROM alerts"
    err = _validate_nl_sql(sql)
    assert err is not None
    assert "SELECT *" in err or "*" in err


def test_table_star_blocked():
    sql = "SELECT alerts.* FROM alerts"
    err = _validate_nl_sql(sql)
    assert err is not None


def test_disallowed_table_blocked():
    sql = "SELECT id FROM users"
    err = _validate_nl_sql(sql)
    assert err is not None
    assert "users" in err


def test_comma_join_disallowed_table_blocked():
    sql = "SELECT a.id FROM alerts a, users u WHERE a.id = u.id"
    err = _validate_nl_sql(sql)
    assert err is not None
    assert "users" in err


def test_column_blacklist_real():
    """Real column reference (not inside string) must be blocked."""
    sql = "SELECT id, saved_password FROM alerts"
    err = _validate_nl_sql(sql)
    assert err is not None
    assert "saved_password" in err


# ── LIMIT enforcement ────────────────────────────────────────

def test_enforce_limit_adds_when_missing():
    sql = "SELECT id FROM alerts"
    result = _enforce_limit(sql)
    assert "LIMIT 200" in result


def test_enforce_limit_caps_high_value():
    sql = "SELECT id FROM alerts LIMIT 9999"
    result = _enforce_limit(sql)
    assert "200" in result
    assert "9999" not in result


def test_enforce_limit_preserves_low_value():
    sql = "SELECT id FROM alerts LIMIT 50"
    result = _enforce_limit(sql)
    assert "50" in result


# ── Valid queries pass ───────────────────────────────────────

def test_valid_simple_query():
    sql = "SELECT id, message, level FROM alerts WHERE level = 'error'"
    assert _validate_nl_sql(sql) is None


def test_valid_join_query():
    sql = "SELECT a.id, arr.name FROM alerts a JOIN arrays arr ON a.array_id = arr.array_id"
    assert _validate_nl_sql(sql) is None


def test_valid_aggregation():
    sql = "SELECT observer_name, count(id) FROM alerts GROUP BY observer_name"
    assert _validate_nl_sql(sql) is None
