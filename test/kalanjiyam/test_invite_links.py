"""Tests for organization admin registration invite links."""

from datetime import datetime, timedelta

import kalanjiyam.database as db
import kalanjiyam.queries as q
from kalanjiyam.enums import SiteRole


def _make_org(session, slug: str, name: str) -> db.Group:
    org = db.Group(name=name, slug=slug)
    session.add(org)
    session.flush()
    return org


def _make_org_admin(session, username: str, org: db.Group) -> db.User:
    user = db.User(username=username, email=f"{username}@test.local", organization_id=org.id)
    user.set_password("pass123")
    org_role = session.query(db.Role).filter_by(name=SiteRole.ORG_ADMIN.value).first()
    if not org_role:
        org_role = db.Role(name=SiteRole.ORG_ADMIN.value)
        session.add(org_role)
        session.flush()
    user.roles.append(org_role)
    session.add(user)
    session.flush()
    session.add(db.UserGroups(user_id=user.id, group_id=org.id))
    org.admin_user_id = user.id
    session.commit()
    return user


def test_invite_token_model_hashing_and_validity(flask_app):
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "invite-model-org", "Invite Model Org")
        admin = _make_org_admin(session, "invite_admin_model", org)

        token = db.InviteToken(
            org_id=org.id,
            created_by_user_id=admin.id,
            role=SiteRole.P1.value,
            label="Cohort 1",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        raw_secret = "super_secret_raw_token_value_123"
        token.set_token(raw_secret)
        session.add(token)
        session.commit()

        assert token.token_hash != raw_secret
        assert token.check_token(raw_secret) is True
        assert token.check_token("wrong_token") is False
        assert token.is_valid is True
        assert token.is_expired is False

        # Expired token
        token.expires_at = datetime.utcnow() - timedelta(minutes=5)
        assert token.is_expired is True
        assert token.is_valid is False

        # Inactive token
        token.expires_at = datetime.utcnow() + timedelta(days=7)
        token.is_active = False
        assert token.is_valid is False


def test_queries_create_and_get_invite_token(flask_app):
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "invite-query-org", "Invite Query Org")
        admin = _make_org_admin(session, "invite_admin_query", org)

        # Create token
        record, raw_token = q.create_invite_token(
            org_id=org.id,
            created_by_user_id=admin.id,
            role=SiteRole.P2.value,
            label="P2 Proofers",
            expires_at=datetime.utcnow() + timedelta(days=30),
        )

        assert record.id is not None
        assert record.role == SiteRole.P2.value
        assert record.uses_count == 0
        assert record.is_active is True

        # Look up by raw token
        found = q.get_invite_token_by_raw(raw_token)
        assert found is not None
        assert found.id == record.id
        assert found.role == SiteRole.P2.value

        # Lookup with wrong token
        assert q.get_invite_token_by_raw("invalid-raw-token") is None
        assert q.get_invite_token_by_raw("") is None

        # Org list
        tokens = q.get_invite_tokens_for_org(org.id)
        assert len(tokens) >= 1
        assert tokens[0].id == record.id

        # Revoke token
        revoked = q.revoke_invite_token(record.id, org_id=org.id)
        assert revoked is True
        assert q.get_invite_token_by_raw(raw_token) is None


def test_queries_create_user_via_invite(flask_app):
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "invite-reg-org", "Invite Reg Org")
        admin = _make_org_admin(session, "invite_admin_reg", org)

        record, raw_token = q.create_invite_token(
            org_id=org.id,
            created_by_user_id=admin.id,
            role=SiteRole.MODERATOR.value,
            label="Moderator link",
            expires_at=datetime.utcnow() + timedelta(days=14),
        )

        new_user = q.create_user_via_invite(
            username="invited_mod_user",
            email="invited_mod@test.local",
            raw_password="safe_password_123",
            invite_token=record,
        )

        assert new_user.id is not None
        assert new_user.username == "invited_mod_user"
        assert new_user.organization_id == org.id
        assert new_user.is_verified is True
        assert any(r.name == SiteRole.MODERATOR.value for r in new_user.roles)

        # Uses count incremented
        session.refresh(record)
        assert record.uses_count == 1


def test_auth_view_register_via_invite(flask_app, client):
    with flask_app.app_context():
        session = q.get_session()
        session.query(db.UsageLog).filter_by(action="register").delete()
        session.commit()
        org = _make_org(session, "auth-invite-org", "Auth Invite Org")
        admin = _make_org_admin(session, "auth_invite_admin", org)

        record, raw_token = q.create_invite_token(
            org_id=org.id,
            created_by_user_id=admin.id,
            role=SiteRole.P1.value,
            label="Batch 2026",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

    # 1. Invalid token redirect
    resp_bad = client.get("/register/invite/non_existent_token_12345", follow_redirects=True)
    assert resp_bad.status_code == 200
    assert b"This invite link is invalid or has expired" in resp_bad.data

    # 2. Valid token shows registration page
    resp_get = client.get(f"/register/invite/{raw_token}")
    assert resp_get.status_code == 200
    assert b"Join Auth Invite Org" in resp_get.data
    assert b"P1" in resp_get.data

    # 3. Successful registration
    with client:
        resp_post = client.post(
            f"/register/invite/{raw_token}",
            data={
                "username": "self_proofer_1",
                "email": "proofer1@example.com",
                "password": "valid_password_123",
            },
        )
        assert resp_post.status_code == 302
        from flask_login import current_user
        assert current_user.is_authenticated
        assert current_user.username == "self_proofer_1"

    with flask_app.app_context():
        session = q.get_session()
        created_user = session.query(db.User).filter_by(username="self_proofer_1").first()
        assert created_user is not None
        assert created_user.organization_id == org.id
        assert created_user.is_verified is True
        assert any(r.name == SiteRole.P1.value for r in created_user.roles)

        token_record = session.query(db.InviteToken).filter_by(id=record.id).first()
        assert token_record.uses_count == 1

    # 4. Multi-use: another user can register using the same link
    client.get("/sign-out")  # logout first
    with client:
        resp_post2 = client.post(
            f"/register/invite/{raw_token}",
            data={
                "username": "self_proofer_2",
                "email": "proofer2@example.com",
                "password": "valid_password_123",
            },
        )
        assert resp_post2.status_code == 302
        assert current_user.is_authenticated
        assert current_user.username == "self_proofer_2"

    with flask_app.app_context():
        session = q.get_session()
        token_record = session.query(db.InviteToken).filter_by(id=record.id).first()
        assert token_record.uses_count == 2


def test_org_admin_invite_links_view(flask_app):
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "admin-invite-view-org", "Admin Invite View Org")
        admin = _make_org_admin(session, "admin_invite_view_user", org)
        regular_user = db.User(username="regular_member_no_admin", email="reg@test.local")
        regular_user.set_password("pass123")
        session.add(regular_user)
        session.commit()

    # 1. Unauthenticated or non-admin cannot access
    anon_client = flask_app.test_client()
    resp_anon = anon_client.get("/admin/org/invite-links")
    assert resp_anon.status_code == 404

    reg_client = flask_app.test_client(user=regular_user)
    resp_reg = reg_client.get("/admin/org/invite-links")
    assert resp_reg.status_code == 404

    # 2. Org admin can view the invite links page
    admin_client = flask_app.test_client(user=admin)
    resp_admin = admin_client.get("/admin/org/invite-links")
    assert resp_admin.status_code == 200
    assert b"Registration Invite Links" in resp_admin.data
    assert b"Create Invite Link" in resp_admin.data

    # 3. Create an invite link via form POST
    resp_create = admin_client.post(
        "/admin/org/invite-links",
        data={
            "action": "create_invite",
            "role": SiteRole.P2.value,
            "label": "Spring Proofreading Cohort",
            "expires_days": "30",
        },
    )
    assert resp_create.status_code == 200
    assert b"Invite link created successfully" in resp_create.data
    assert b"/register/invite/" in resp_create.data
    assert b"Spring Proofreading Cohort" in resp_create.data

    with flask_app.app_context():
        tokens = q.get_invite_tokens_for_org(org.id)
        assert len(tokens) == 1
        created_token = tokens[0]
        assert created_token.label == "Spring Proofreading Cohort"
        assert created_token.role == SiteRole.P2.value
        assert created_token.is_active is True
        token_id = created_token.id

    # 4. Revoke the invite link
    resp_revoke = admin_client.post(
        "/admin/org/invite-links",
        data={
            "action": "revoke_invite",
            "token_id": str(token_id),
        },
        follow_redirects=True,
    )
    assert resp_revoke.status_code == 200
    assert b"Invite link revoked" in resp_revoke.data

    with flask_app.app_context():
        session = q.get_session()
        revoked_token = session.query(db.InviteToken).filter_by(id=token_id).first()
        assert revoked_token.is_active is False
        assert revoked_token.is_valid is False
