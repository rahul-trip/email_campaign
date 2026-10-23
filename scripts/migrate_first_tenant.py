"""Turn the single-operator install into the first customer (Phase 6b.7).

Before Phase 6b one person signed in with a shared password to a workspace called ``default``.
This gives that workspace the company's name and address (slug) and creates the operator as a
person who signs in with an email: an admin of the workspace and the platform's superadmin.
The mailbox that was configured in ``.env`` (``IMAP_HOST``, ``EMAIL_ADDRESS``,
``EMAIL_PASSWORD``, ...) becomes the workspace's default mailbox, its password encrypted with
``SECRETS_KEYS``; afterwards those lines can be removed from ``.env`` and Doppler.

Nothing is written without ``--apply``: by default it prints what it would do. The password is
asked for, never taken from the command line. Running it twice is harmless: a workspace that
already has the name and slug is left alone, and an existing account is reused. 

    uv run python -m scripts.migrate_first_tenant --name "Quantra" --email sam@quantra.example
    uv run python -m scripts.migrate_first_tenant --name "Quantra" --email sam@quantra.example \
        --apply
"""

from __future__ import annotations

import argparse
import getpass
from collections.abc import Callable

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from outbound.bootstrap import Container, build_container
from outbound.config import Settings
from outbound.domain.enums import CredentialPurpose, MailboxGateway, MembershipRole, PlatformRole
from outbound.domain.slugs import slugify
from outbound.providers.adapters.transactional_email import LogEmail
from outbound.services.identity import IdentityService


class LegacyMailbox(BaseSettings):
    """The mailbox settings ``.env`` held before Phase 6c (the names of the legacy agent)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    imap_host: str = ""
    imap_port: int = 993
    email_address: str = ""
    email_password: SecretStr = SecretStr("")
    from_name: str = ""
    drafts_folder: str = ""
    sent_folder: str = ""

    @property
    def present(self) -> bool:
        return bool(
            self.imap_host and self.email_address and self.email_password.get_secret_value()
        )


def move_mailbox(
    container: Container, workspace_id: str, legacy: LegacyMailbox, owner_id: str | None
) -> str | None:
    """Make the ``.env`` mailbox the workspace's default; nothing if it is already there."""
    address = legacy.email_address.strip().lower()
    with container.uow(workspace_id) as uow:
        if uow.mailboxes.by_address(address) is not None:
            return None
        created = uow.mailboxes.create(
            address, address.rpartition("@")[2], gateway=MailboxGateway.IMAP,
            owner_user_id=owner_id, is_default=True,
            connection={
                "host": legacy.imap_host, "port": legacy.imap_port,
                "drafts_folder": legacy.drafts_folder or None,
                "sent_folder": legacy.sent_folder or None,
            },
            sender={"signature_name": legacy.from_name} if legacy.from_name else None,
        )  # fmt: skip
        name = f"mailbox:{created.id}"
        uow.credentials.put(
            name, CredentialPurpose.MAILBOX_PASSWORD, legacy.email_password.get_secret_value()
        )
        uow.mailboxes.update(created.id, credentials_ref=name)
        uow.commit()
    return created.id


def migrate(
    container: Container,
    *,
    workspace: str,
    name: str,
    email: str,
    slug: str | None = None,
    user_name: str = "",
    apply: bool = False,
    password: Callable[[], str] = lambda: "",
    say: Callable[[str], None] = print,
    legacy: LegacyMailbox | None = None,
) -> bool:
    """Print the plan and, with ``apply``, carry it out. False when there is nothing to move."""
    with container.platform() as platform:
        found = platform.workspaces.find(workspace)
    if found is None:
        say(f"no workspace {workspace!r}; nothing to do")
        return False
    new_slug = slug or slugify(name)
    ids = IdentityService(
        container.identity, container.platform, container.uow, LogEmail(),
        base_url=container.settings.app_base_url,
        terms_version=container.settings.terms_version,
    )  # fmt: skip
    say(f"workspace {found.name!r} ({found.slug}) -> {name!r} ({new_slug})")
    say(f"{email}: admin of {new_slug}, platform superadmin")
    if legacy is not None and legacy.present:
        say(f"mailbox {legacy.email_address} ({legacy.imap_host}): the default, password encrypted")
    if not apply:
        say("dry run: nothing changed (add --apply)")
        return True
    if (found.name, found.slug) != (name, new_slug):
        with container.platform() as platform:
            platform.workspaces.rename(found.id, name, new_slug)
            platform.commit()
    user = ids.add_user(
        email, password(), name=user_name, platform_role=PlatformRole.SUPERADMIN,
        workspace_id=found.id, role=MembershipRole.ADMIN,
    )  # fmt: skip
    if legacy is not None and legacy.present:
        moved = move_mailbox(container, found.id, legacy, user.id)
        say(
            "mailbox moved; remove IMAP_* and EMAIL_* from .env"
            if moved
            else "mailbox was already there"
        )
    say("done; sign in with the email and the password you chose")
    return True


def ask_password() -> str:
    first = getpass.getpass("Password (15 characters or more): ")
    if first != getpass.getpass("Again: "):
        raise SystemExit("the two passwords differ")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", default="default", help="slug or name of the workspace")
    parser.add_argument("--name", required=True, help="the company's name")
    parser.add_argument("--slug", help="its address in the app (default: from the name)")
    parser.add_argument("--email", required=True, help="the operator's sign-in address")
    parser.add_argument("--user-name", default="", help="the operator's own name")
    parser.add_argument("--apply", action="store_true", help="make the changes")
    args = parser.parse_args()
    migrate(
        build_container(Settings()),
        workspace=args.workspace, name=args.name, slug=args.slug, email=args.email,
        user_name=args.user_name, apply=args.apply, password=ask_password,
        legacy=LegacyMailbox(),
    )  # fmt: skip


if __name__ == "__main__":
    main()
