import os
import threading
from pathlib import Path

from .permissions import ROLES, allows, declared_permission, required_permission
from .store import AccountError, AccountStore, Principal, User

_stores: dict[str, AccountStore] = {}
_lock = threading.Lock()


def account_store_url() -> str:
    url = os.getenv("GALAXZ_DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://", "postgresql+")):
        return url
    path = os.getenv("GALAXZ_ACCOUNTS_DB", "data/accounts.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def get_account_store() -> AccountStore:
    url = account_store_url()
    with _lock:
        if url not in _stores:
            _stores[url] = AccountStore(url)
        return _stores[url]


__all__ = [
    "AccountError", "AccountStore", "Principal", "ROLES", "User", "account_store_url",
    "allows", "declared_permission", "get_account_store", "required_permission",
]
