import pytest
import transaction

from flask import Flask
from flask_zodb import ZODB
from ZODB.MappingStorage import MappingStorage


STORAGES = [
    "memory://",
    (MappingStorage, {}),
    MappingStorage,
]


db = ZODB()


def pytest_generate_tests(metafunc):
    if "app" in metafunc.fixturenames:
        apps = []
        for storage in STORAGES:
            app = Flask(__name__)
            db.init_app(app)
            app.config["ZODB_STORAGE"] = storage
            apps.append(app)
        metafunc.parametrize("app", apps)


def test_single_app_shortcut():
    app = Flask(__name__)
    zodb = ZODB(app)
    assert app.extensions["zodb"].zodb is zodb


def test_connection(app):
    with app.app_context():
        assert db.is_connected
        db["answer"] = 42
        assert db["answer"] == 42


def test_commit_transaction(app):
    with app.test_request_context():
        db["answer"] = 42

    with app.test_request_context():
        assert db["answer"] == 42


def test_abort_transaction_on_failure(app):
    with pytest.raises(ZeroDivisionError):
        with app.test_request_context():
            db["answer"] = 42
            assert db["answer"] == 42
            1/0

    with app.test_request_context():
        assert "answer" not in db


def test_abort_transaction_if_doomed(app):
    with app.test_request_context():
        db["answer"] = 42
        transaction.doom()

    with app.test_request_context():
        assert "answer" not in db

def test_transfer_count(app):
    with app.app_context():
        db['answer'] = 42
        transaction.commit()
        assert db.transfers