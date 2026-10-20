import io
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from app.config import settings


def config():
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return cfg


def test_migration_preserves_existing_tables(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    monkeypatch.setattr(settings, "database_url", url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE shops (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO shops VALUES (1, 'Existing merchant')"))
    command.upgrade(config(), "head")
    command.upgrade(config(), "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM shops WHERE id=1")) == "Existing merchant"
        assert "commerce_balances" in inspect(connection).get_table_names()
    command.downgrade(config(), "base")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM shops WHERE id=1")) == "Existing merchant"
        assert "commerce_balances" not in inspect(connection).get_table_names()
    engine.dispose()


def test_migration_compiles_for_postgresql(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://unused/unused")
    cfg = config()
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    sql = cfg.output_buffer.getvalue()
    assert "CREATE TABLE commerce_balances" in sql
    assert "FOREIGN KEY(variant_id, merchant_id)" in sql
    assert "CREATE TABLE shops" not in sql

def test_sprint_one_upgrade_preserves_existing_account(tmp_path,monkeypatch):
    url="sqlite:///"+(tmp_path/"existing.db").as_posix()
    monkeypatch.setattr(settings,"database_url",url)
    command.upgrade(config(),"0001_commerce")
    engine=create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO commerce_users (id,name,email,password_hash) VALUES (1,'Existing','existing@example.com','preserved-hash')"))
    command.upgrade(config(),"head")
    with engine.connect() as connection:
        row=connection.execute(text("SELECT password_hash,email_verified FROM commerce_users WHERE id=1")).one()
        assert row[0]=="preserved-hash" and not row[1]
    engine.dispose()
