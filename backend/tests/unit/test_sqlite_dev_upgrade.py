"""An existing dev SQLite file from an older version gets newer columns added on start-up."""

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import _upgrade_sqlite_dev_schema


def test_old_sqlite_file_gets_new_columns(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:  # simulate a file created before run leases existed
        conn.execute(text("ALTER TABLE workflow_runs DROP COLUMN lease_owner"))
        conn.execute(text("ALTER TABLE workflow_runs DROP COLUMN lease_until"))
    assert "lease_owner" not in {c["name"] for c in inspect(engine).get_columns("workflow_runs")}

    _upgrade_sqlite_dev_schema(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("workflow_runs")}
    assert {"lease_owner", "lease_until"} <= cols
    _upgrade_sqlite_dev_schema(engine)  # idempotent
    engine.dispose()
