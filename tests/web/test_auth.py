import pytest
from zalosniper.web.auth import AuthManager

def test_hash_and_verify_password():
    mgr = AuthManager()
    hashed = mgr.hash_password("mysecretpassword")
    assert mgr.verify_password("mysecretpassword", hashed) is True
    assert mgr.verify_password("wrongpassword", hashed) is False

def test_create_and_validate_session():
    mgr = AuthManager()
    token = mgr.create_session()
    assert len(token) == 64
    assert mgr.validate_session(token) is True

def test_session_not_found():
    mgr = AuthManager()
    assert mgr.validate_session("nonexistent-token") is False

def test_invalidate_session():
    mgr = AuthManager()
    token = mgr.create_session()
    mgr.invalidate_session(token)
    assert mgr.validate_session(token) is False
