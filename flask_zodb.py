import sys
import time

from flask import _app_ctx_stack, current_app
import transaction
import zodburi

from collections import UserDict

from ZODB.ActivityMonitor import ActivityMonitor
from ZODB.Connection import Connection
from ZODB.DB import DB
from werkzeug.utils import cached_property
from flask.signals import Namespace

__all__ = ["ZODB"]


_signals = Namespace()
connection_opened = _signals.signal("zodb-connectioned-opened")
connection_will_close = _signals.signal("zodb-connectioned-willclose")
connection_closed = _signals.signal("zodb-connectioned-closed")


class ZODB(UserDict):
    """Extension object.  Behaves as the root object of the storage during
    requests, i.e. a `~persistent.mapping.PersistentMapping`.

    ::

        db = ZODB()

        app = Flask(__name__)
        db.init_app(app)

    As a shortcut if you initiate ZODB after Flask you can do this::

        app = Flask(__name__)
        db = ZODB(app)

    """

    def __init__(self, app=None):
        # Don't call super here as the ZODB root to be connected is what will be
        # used as .data
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Configure a Flask application to use this ZODB extension."""
        assert "zodb" not in app.extensions, "app already initiated for zodb"
        app.extensions["zodb"] = _ZODBState(self, app)
        app.teardown_request(self.close_db)

    def close_db(self, exception):
        """Added as a `~flask.Flask.teardown_request` to applications to
        commit the transaction and disconnect ZODB if it was used during
        the request."""
        if self.is_connected:
            connection_will_close.send()
            if exception is None and not transaction.isDoomed():
                transaction.commit()
            else:
                transaction.abort()
            _app_ctx_stack.top.zodb_transfers = self.connection.getTransferCounts(
                clear=True
            )
            self.connection.close()
            connection_closed.send()

    def create_db(self, app) -> DB:
        """Create a ZODB connection pool from the *app* configuration."""
        assert "ZODB_STORAGE" in app.config, "ZODB_STORAGE not configured"
        storage = app.config["ZODB_STORAGE"]
        if isinstance(storage, str):
            factory, dbargs = zodburi.resolve_uri(storage)
        elif isinstance(storage, tuple):
            factory, dbargs = storage
        else:
            factory, dbargs = storage, {}
        return DB(factory(), **dbargs)

    @property
    def is_connected(self) -> bool:
        """True ZODB was connected."""
        return hasattr(_app_ctx_stack.top, "zodb_connection")

    @property
    def connection(self) -> Connection:
        """
        App context database connection
        """

        if not self.is_connected:
            state = current_app.extensions["zodb"]
            connection = _app_ctx_stack.top.zodb_connection = state.db.open()
            _app_ctx_stack.top.zodb_transfers = connection.getTransferCounts()
            connection_opened.send()
            transaction.begin()
        return _app_ctx_stack.top.zodb_connection

    @property
    def data(self):
        return self.connection.root()

    @property
    def transfers(self):
        """
        Return the current transfer counts for the current connection
        """
        return _app_ctx_stack.top.zodb_connection.getTransferCounts()


class _ZODBState:
    """Adds a ZODB connection pool to a Flask application."""

    def __init__(self, zodb, app):
        self.zodb = zodb
        self.app = app

    @cached_property
    def db(self) -> DB:
        """Connection pool."""
        db: DB = self.zodb.create_db(self.app)
        db.setActivityMonitor(ActivityMonitor())
        return db
