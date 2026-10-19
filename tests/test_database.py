import os, csv
import pytest
from gateway.database import Database
from conftest import T0


def r(pid="P001", ts=T0, **kw):
    d = dict(pid=pid, ts=ts, hr=70, spo2=97, temp=36.6, fall=0, flags=0, synthetic=True, source="t", seq=None, uptime=None)
    d.update(kw); return d


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "d.sqlite3"); d.init(); return d


def test_init_idempotent_and_keeps_data(db):
    db.insert_reading(r(), T0); db.init()
    assert len(db.history("P001", 0)) == 1


def test_insert_latest_history_multi_patient(db):
    for i in range(3): db.insert_reading(r(ts=T0 + i, hr=60 + i), T0)
    db.insert_reading(r(pid="P002", ts=T0), T0)
    assert db.latest("P001")["hr"] == 62 and db.latest("P002")["hr"] == 70 and db.latest("P003") is None
    assert [x["hr"] for x in db.history("P001", T0 + 1)] == [61, 62]
    assert [p["pid"] for p in db.list_patients()] == ["P001", "P002"]
    assert [x["hr"] for x in db.last_n("P001", 2)] == [61, 62]


def test_duplicate_seq_uptime_rejected(db):
    assert db.insert_reading(r(seq=1, uptime=60), T0) is not None
    assert db.insert_reading(r(seq=1, uptime=60), T0) is None
    assert db.insert_reading(r(seq=1, uptime=120), T0) is not None   # node reboot / seq reuse is not a duplicate


def test_sql_injection_attempt_is_inert(db):
    db.insert_reading(r(), T0)
    assert db.latest("P001'; DROP TABLE readings;--") is None and db.latest("P001") is not None


def test_alert_dedup_and_ack(db):
    db.insert_reading(r(), T0)
    a = db.create_alert("P001", "FALL", "critical", "x", T0)
    assert a and db.create_alert("P001", "FALL", "critical", "x", T0) is None
    assert db.ack_alert(a, T0 + 5) == (True, False) and db.ack_alert(a, T0 + 9) == (True, True) and db.ack_alert(999, 1) == (False, False)
    assert db.create_alert("P001", "FALL", "critical", "again", T0 + 10)   # allowed after ack
    assert len(db.list_alerts("active")) == 1 and len(db.list_alerts("acknowledged")) == 1 and len(db.list_alerts("all")) == 2


def test_retention_exports_then_deletes(db, tmp_path):
    now = T0 + 40 * 86400
    db.insert_reading(r(ts=T0), T0); db.insert_reading(r(ts=T0 + 10), T0)      # 40 days old
    db.insert_reading(r(ts=now - 100), T0)                                      # recent
    n, path = db.export_and_prune(str(tmp_path / "exp"), now, 30)
    assert n == 2 and os.path.isfile(path)
    rows = list(csv.DictReader(open(path)))
    assert len(rows) == 2 and rows[0]["pid"] == "P001"
    assert len(db.history("P001", 0)) == 1
    assert db.export_and_prune(str(tmp_path / "exp"), now, 30) == (0, None)


def test_no_deletion_when_export_fails(db, tmp_path):
    blocker = tmp_path / "notadir"; blocker.write_text("x")
    db.insert_reading(r(ts=T0), T0)
    with pytest.raises(OSError): db.export_and_prune(str(blocker), T0 + 90 * 86400, 30)
    assert len(db.history("P001", 0)) == 1
