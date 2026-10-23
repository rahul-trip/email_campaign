"""Encrypted credentials (Phase 6c): sealed per row, opened only where they belong, swapped
safely when a token rotates, and re-sealed when the key changes."""

from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import text

from outbound.db.crypto import Keyring, Sealed, SecretUnreadable, associated_data, new_key
from outbound.db.session import make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CredentialPurpose
from outbound.domain.errors import ConfigurationError

TOKENS = json.dumps({"access_token": "at-1", "refresh_token": "rt-1"})


def keyring(*versions: int) -> Keyring:
    return Keyring({v: bytes([v]) * 32 for v in versions})


# ------------------------------------------------------------------ the keyring alone


def test_a_secret_opens_only_with_the_same_associated_data() -> None:
    keys = keyring(1)
    sealed = keys.seal("hunter2-app-password", b"ws-1|cred-1")
    assert keys.open(sealed, b"ws-1|cred-1") == "hunter2-app-password"
    assert b"hunter2" not in sealed.ciphertext
    with pytest.raises(SecretUnreadable):
        keys.open(sealed, b"ws-2|cred-1")  # copied into another workspace
    with pytest.raises(SecretUnreadable):
        keys.open(sealed, b"ws-1|cred-2")  # copied into another row


def test_a_tampered_ciphertext_is_refused() -> None:
    keys = keyring(1)
    sealed = keys.seal("secret", b"aad")
    flipped = bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]
    with pytest.raises(SecretUnreadable):
        keys.open(Sealed(sealed.key_version, sealed.nonce, flipped), b"aad")


def test_every_seal_uses_a_new_nonce() -> None:
    keys = keyring(1)
    assert keys.seal("same", b"aad").nonce != keys.seal("same", b"aad").nonce


def test_the_newest_key_seals_and_older_keys_still_open() -> None:
    old = keyring(1).seal("secret", b"aad")
    both = keyring(1, 2)
    assert both.seal("secret", b"aad").key_version == 2
    assert both.open(old, b"aad") == "secret"
    with pytest.raises(SecretUnreadable):
        keyring(2).open(old, b"aad")  # the old key was removed


def test_the_setting_is_parsed_and_mistakes_are_explained() -> None:
    key = new_key()
    assert len(base64.b64decode(key)) == 32
    assert Keyring.from_setting(json.dumps({"3": key})).newest == 3
    for bad in ("not json", '{"1": "short"}', '["a"]'):
        with pytest.raises(ConfigurationError):
            Keyring.from_setting(bad)
    with pytest.raises(ConfigurationError, match="SECRETS_KEYS is not set"):
        Keyring.from_setting("").seal("x", b"aad")


# ------------------------------------------------------------------ the repository


def test_put_reveal_and_replace(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        first = uow.credentials.put(
            "mailbox:sam", CredentialPurpose.MAILBOX_OAUTH, TOKENS, details={"scopes": ["a"]}
        )
        uow.commit()
    with factory(ws) as uow:
        found, secret = uow.credentials.reveal("mailbox:sam")
        assert json.loads(secret)["refresh_token"] == "rt-1"
        assert found.version == first.version == 1 and found.details == {"scopes": ["a"]}
        again = uow.credentials.put("mailbox:sam", CredentialPurpose.MAILBOX_OAUTH, "new")
        uow.commit()
    assert again.id == first.id and again.version == 2


def test_the_database_holds_only_ciphertext(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.credentials.put("imap:sam", CredentialPurpose.MAILBOX_PASSWORD, "app-password-xyz")
        uow.commit()
        stored = uow.session.execute(text("SELECT ciphertext FROM credentials")).scalar_one()
    assert b"app-password-xyz" not in bytes(stored)


def test_another_workspace_neither_sees_nor_opens_it(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(ws) as uow:
        uow.credentials.put("shared-name", CredentialPurpose.MAILBOX_PASSWORD, "mine")
        uow.commit()
    with factory(other_ws) as uow:
        assert uow.credentials.get("shared-name") is None


def test_a_ciphertext_moved_to_another_row_does_not_open(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.credentials.put("a", CredentialPurpose.MAILBOX_PASSWORD, "secret-a")
        uow.credentials.put("b", CredentialPurpose.MAILBOX_PASSWORD, "secret-b")
        uow.commit()
        uow.session.execute(
            text(
                "UPDATE credentials SET ciphertext = (SELECT ciphertext FROM credentials "
                "WHERE name = 'a'), nonce = (SELECT nonce FROM credentials WHERE name = 'a') "
                "WHERE name = 'b'"
            )
        )
        uow.commit()
    with factory(ws) as uow, pytest.raises(SecretUnreadable):
        uow.credentials.reveal("b")


def test_two_refreshes_race_and_one_wins_without_losing_a_token(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        start = uow.credentials.put("graph:sam", CredentialPurpose.MAILBOX_OAUTH, TOKENS)
        uow.commit()
    # both read version 1, refreshed at the provider, and now write back
    with factory(ws) as first:
        assert first.credentials.swap("graph:sam", start.version, "tokens-from-first")
        first.commit()
    with factory(ws) as second:
        assert not second.credentials.swap("graph:sam", start.version, "tokens-from-second")
        second.commit()
    with factory(ws) as uow:
        found, secret = uow.credentials.reveal("graph:sam")
    assert (found.version, secret) == (2, "tokens-from-first")


def test_rotating_reseals_under_the_newest_key(engine: object, ws: str) -> None:
    sessions = make_session_factory(engine)  # type: ignore[arg-type]
    old = UnitOfWorkFactory(sessions, keyring=keyring(1))
    with old(ws) as uow:
        uow.credentials.put("imap:sam", CredentialPurpose.MAILBOX_PASSWORD, "pw")
        uow.commit()
    new = UnitOfWorkFactory(sessions, keyring=keyring(1, 2))
    with new(ws) as uow:
        assert uow.credentials.reseal_all() == 1
        uow.commit()
    only_new = UnitOfWorkFactory(sessions, keyring=keyring(2))
    with only_new(ws) as uow:
        assert uow.credentials.reveal("imap:sam")[1] == "pw"
        assert uow.credentials.reseal_all() == 0


def test_associated_data_names_the_workspace_and_the_row() -> None:
    assert associated_data("ws", "cred") == b"ws|cred"
