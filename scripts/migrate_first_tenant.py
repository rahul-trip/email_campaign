"""Turn the single-operator install into the first customer (Phase 6b.7).

Before Phase 6b one person signed in with a shared password to a workspace called ``default``.
This gives that workspace the company's name and address (slug) and creates the operator as a
person who signs in with an email: an admin of the workspace and the platform's superadmin.

Nothing is written without ``--apply``: by default it prints what it would do. The password is
asked for, never taken from the command line. Running it twice is harmless: a workspace that
already has the name and slug is left alone, and an existing account is reused. The mailbox
moves out of the environment in Phase 6c.

    uv run python -m scripts.migrate_first_tenant --name "Quantra" --email sam@quantra.example
    uv run python -m scripts.migrate_first_tenant --name "Quantra" --email sam@quantra.example \
        --apply
"""

from __future__ import annotations

import argparse
import getpass
from collections.abc import Callable

from outbound.bootstrap import Container, build_container
from outbound.config import Settings
from outbound.domain.enums import MembershipRole, PlatformRole
from outbound.domain.slugs import slugify
from outbound.providers.adapters.transactional_email import LogEmail
from outbound.services.identity import IdentityService


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
    if not apply:
        say("dry run: nothing changed (add --apply)")
        return True
    if (found.name, found.slug) != (name, new_slug):
        with container.platform() as platform:
            platform.workspaces.rename(found.id, name, new_slug)
            platform.commit()
    ids.add_user(
        email, password(), name=user_name, platform_role=PlatformRole.SUPERADMIN,
        workspace_id=found.id, role=MembershipRole.ADMIN,
    )  # fmt: skip
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
    )  # fmt: skip


if __name__ == "__main__":
    main()
