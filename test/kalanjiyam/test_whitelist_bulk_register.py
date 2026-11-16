"""Tests for Whitelist-based bulk CSV account creation and first-login password change prompt."""

import io

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
    user.set_password("AdminPass123")
    user.must_change_password = False
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


def test_bulk_create_users_from_csv_query(flask_app):
    """Test the bulk_create_users_from_csv helper with various formats and roles."""
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "csv-bulk-org", "CSV Bulk Org")

        csv_text = (
            "email,role,username\n"
            "p1_user@test.org,p1,custom_p1_user\n"
            "p2_user@test.org,p2,\n"  # Auto username from email
            "mod_user@test.org,moderator,custom_mod_user\n"
            "org_admin_user@test.org,org_admin,\n"
        )

        result = q.bulk_create_users_from_csv(
            org_id=org.id,
            csv_content=csv_text,
            default_role=SiteRole.P1.value,
        )

        assert len(result["created"]) == 4
        assert len(result["skipped"]) == 0
        assert len(result["errors"]) == 0

        # Verify created users
        p1_u = session.query(db.User).filter_by(email="p1_user@test.org").first()
        assert p1_u is not None
        assert p1_u.username == "custom_p1_user"
        assert p1_u.check_password("User@1234") is True
        assert p1_u.must_change_password is True
        assert p1_u.is_verified is True
        assert p1_u.organization_id == org.id
        assert any(r.name == SiteRole.P1.value for r in p1_u.roles)

        # Verify auto-username for p2_user
        p2_u = session.query(db.User).filter_by(email="p2_user@test.org").first()
        assert p2_u is not None
        assert p2_u.username.startswith("p2_user")
        assert p2_u.check_password("User@1234") is True
        assert p2_u.must_change_password is True
        assert any(r.name == SiteRole.P2.value for r in p2_u.roles)

        # Verify org admin
        oa_u = session.query(db.User).filter_by(email="org_admin_user@test.org").first()
        assert oa_u is not None
        assert any(r.name == SiteRole.ORG_ADMIN.value for r in oa_u.roles)

        # Verify master_user cannot be provisioned by org admin
        mu_res = q.bulk_create_users_from_csv(
            org_id=org.id,
            csv_content="master_u@test.org,master_user,custom_master_user\n",
        )
        assert len(mu_res["created"]) == 0
        assert any("Invalid role 'master_user'" in err for err in mu_res["errors"])


def test_bulk_create_users_duplicate_and_invalid_handling(flask_app):
    """Test handling of existing emails and invalid rows in CSV."""
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "csv-errors-org", "CSV Errors Org")

        # Create one existing user
        existing = db.User(username="already_registered", email="existing@test.org", organization_id=org.id)
        existing.set_password("pass123")
        session.add(existing)
        session.commit()

        csv_text = (
            "email,role,username\n"
            "existing@test.org,p1,existing_new\n"  # should be skipped
            "invalid-email-no-domain,p1,user_inv\n"  # error
            "valid_new@test.org,invalid_role_xyz,user_valid\n"  # error
            "valid_new@test.org,p1,user_valid\n"  # should succeed
            "valid_new@test.org,p1,user_dup\n"  # in-batch duplicate should be skipped
        )

        result = q.bulk_create_users_from_csv(
            org_id=org.id,
            csv_content=csv_text,
            default_role=SiteRole.P1.value,
        )

        assert len(result["created"]) == 1
        assert result["created"][0]["email"] == "valid_new@test.org"
        assert len(result["skipped"]) == 2
        assert len(result["errors"]) == 2


def test_org_admin_view_bulk_csv_upload(flask_app):
    """Test Org Admin invite links view with bulk CSV upload and sample CSV download."""
    with flask_app.app_context():
        session = q.get_session()
        org = _make_org(session, "view-bulk-org", "View Bulk Org")
        admin = _make_org_admin(session, "view_bulk_admin", org)

    client = flask_app.test_client(user=admin)

    # 1. Download sample CSV
    resp_sample = client.get("/admin/org/invite-links/sample-csv")
    assert resp_sample.status_code == 200
    assert resp_sample.mimetype == "text/csv"
    assert b"email,role,username" in resp_sample.data

    # 2. Upload CSV via file upload
    csv_file_data = (
        b"email,role,username\n"
        b"csv_proofer1@example.com,p1,csv_proofer_one\n"
        b"csv_proofer2@example.com,p2,csv_proofer_two\n"
    )
    resp_upload = client.post(
        "/admin/org/invite-links",
        data={
            "action": "bulk_csv_create",
            "default_role": "p1",
            "csv_file": (io.BytesIO(csv_file_data), "users.csv"),
        },
        content_type="multipart/form-data",
    )
    assert resp_upload.status_code == 200
    assert b"Successfully created 2 user account(s) with default password User@1234" in resp_upload.data
    assert b"csv_proofer_one" in resp_upload.data
    assert b"csv_proofer_two" in resp_upload.data

    # 3. Upload CSV via text paste
    resp_paste = client.post(
        "/admin/org/invite-links",
        data={
            "action": "bulk_csv_create",
            "default_role": "moderator",
            "csv_text": "csv_mod1@example.com\ncsv_mod2@example.com",
        },
    )
    assert resp_paste.status_code == 200
    assert b"Successfully created 2 user account(s) with default password User@1234" in resp_paste.data

    with flask_app.app_context():
        session = q.get_session()
        mod1 = session.query(db.User).filter_by(email="csv_mod1@example.com").first()
        assert mod1 is not None
        assert mod1.must_change_password is True
        assert any(r.name == SiteRole.MODERATOR.value for r in mod1.roles)


def test_first_login_prompt_and_do_it_later_and_change_password(flask_app):
    """Test the full first-login password change prompt workflow:
    1. User created with default password User@1234 and must_change_password=True.
    2. Logs in -> prompted to change password.
    3. Clicks 'Do it later' -> proceeds to site, but must_change_password remains True.
    4. Logs out and logs in again -> prompted again!
    5. Submits new password -> password updated, must_change_password becomes False.
    6. Logs out and logs in again -> no prompt, goes straight to target!
    """
    with flask_app.app_context():
        session = q.get_session()
        session.query(db.UsageLog).filter_by(action="sign_in").delete()
        session.commit()
        org = _make_org(session, "prompt-flow-org", "Prompt Flow Org")

        # Create user via bulk CSV query
        res = q.bulk_create_users_from_csv(
            org_id=org.id,
            csv_content="whitelist_user@test.org,p1,whitelist_tester\n",
        )
        assert len(res["created"]) == 1

    client = flask_app.test_client()

    # Step 1: Login with initial credentials User@1234
    resp_login1 = client.post(
        "/sign-in",
        data={"username": "whitelist_tester", "password": "User@1234"},
        follow_redirects=False,
    )
    assert resp_login1.status_code == 302
    # Must redirect to prompt-change-password!
    assert "/prompt-change-password" in resp_login1.headers["Location"]

    # Follow to prompt page
    resp_prompt1 = client.get(resp_login1.headers["Location"])
    assert resp_prompt1.status_code == 200
    assert b"Set Your New Password" in resp_prompt1.data
    assert b"Do it later" in resp_prompt1.data

    # Step 2: Click 'Do it later'
    resp_skip = client.post(
        "/prompt-change-password",
        data={"do_it_later": "1", "next": "/proofing/"},
        follow_redirects=True,
    )
    assert resp_skip.status_code == 200

    # Verify DB flag is STILL True
    with flask_app.app_context():
        session = q.get_session()
        u = session.query(db.User).filter_by(username="whitelist_tester").first()
        assert u.must_change_password is True

    # Step 3: Sign out and sign in again -> MUST prompt again!
    client.get("/sign-out")
    resp_login2 = client.post(
        "/sign-in",
        data={"username": "whitelist_tester", "password": "User@1234"},
        follow_redirects=False,
    )
    assert resp_login2.status_code == 302
    assert "/prompt-change-password" in resp_login2.headers["Location"]

    # Step 4: Try mismatching passwords on prompt form
    resp_mismatch = client.post(
        resp_login2.headers["Location"],
        data={
            "new_password": "NewSafePassword@999",
            "confirm_password": "DifferentPassword@111",
        },
    )
    assert resp_mismatch.status_code == 200
    assert b"Passwords must match" in resp_mismatch.data

    # Step 5: Submit valid matching new password
    resp_change = client.post(
        resp_login2.headers["Location"],
        data={
            "new_password": "BrandNewSecretPassword@123",
            "confirm_password": "BrandNewSecretPassword@123",
            "next": "/proofing/",
        },
        follow_redirects=True,
    )
    assert resp_change.status_code == 200
    assert b"Password updated successfully" in resp_change.data

    # Verify DB flag is now FALSE and password is changed
    with flask_app.app_context():
        session = q.get_session()
        u = session.query(db.User).filter_by(username="whitelist_tester").first()
        assert u.must_change_password is False
        assert u.check_password("BrandNewSecretPassword@123") is True
        assert u.check_password("User@1234") is False

    # Step 6: Sign out and sign in again with the NEW password -> NO prompt!
    client.get("/sign-out")
    resp_login3 = client.post(
        "/sign-in",
        data={"username": "whitelist_tester", "password": "BrandNewSecretPassword@123"},
        follow_redirects=False,
    )
    assert resp_login3.status_code == 302
    # Should redirect directly to target (proofing), NOT prompt-change-password
    assert "/prompt-change-password" not in resp_login3.headers["Location"]


def test_first_login_prompt_for_different_roles(flask_app):
    """Verify first-login prompt works for org_admin, moderator, p1, p2, and master_user."""
    roles = [
        ("role_oa_user", "org_admin"),
        ("role_mod_user", "moderator"),
        ("role_p1_user", "p1"),
        ("role_p2_user", "p2"),
        ("role_mu_user", "master_user"),
    ]

    with flask_app.app_context():
        session = q.get_session()
        session.query(db.UsageLog).filter_by(action="sign_in").delete()
        session.commit()
        org = _make_org(session, "roles-prompt-org", "Roles Prompt Org")

        for un, role in roles:
            u = db.User(username=un, email=f"{un}@roles.test", organization_id=org.id)
            u.set_password("User@1234")
            u.must_change_password = True
            r_record = session.query(db.Role).filter_by(name=role).first()
            if not r_record:
                r_record = db.Role(name=role)
                session.add(r_record)
                session.flush()
            u.roles.append(r_record)
            session.add(u)
        session.commit()

    client = flask_app.test_client()

    for un, role in roles:
        # Clear rate limit between logins
        with flask_app.app_context():
            session = q.get_session()
            session.query(db.UsageLog).filter_by(action="sign_in").delete()
            session.commit()

        resp = client.post(
            "/sign-in",
            data={"username": un, "password": "User@1234"},
            follow_redirects=False,
        )
        assert resp.status_code == 302, f"Login failed for role {role}"
        assert "/prompt-change-password" in resp.headers["Location"], f"Prompt not triggered for role {role}"

        # Test skip via do_it_later
        resp_skip = client.post(
            "/prompt-change-password",
            data={"do_it_later": "1", "next": "/"},
            follow_redirects=False,
        )
        assert resp_skip.status_code == 302

        client.get("/sign-out")
