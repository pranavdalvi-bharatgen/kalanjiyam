"""Manages the emails we send to our users."""

from flask import render_template, url_for
from flask_mail import Mail, Message

mailer = Mail()


def send_reset_password_link(username: str, email: str, raw_token: str):
    """Send a password recovery link to the given user.

    `raw_token` appears only in the email we send to the user. We keep no
    record of it otherwise.
    """
    msg = Message("[Kalanjiyam] Please reset your password", recipients=[email])
    # FIXME: implementation without username?
    link = url_for(
        "auth.reset_password_from_token", username=username, raw_token=raw_token
    )
    msg.body = render_template(
        "email/reset-password-link.txt", username=username, link=link
    )
    mailer.send(msg)


def send_confirm_reset_password(username: str, email: str):
    """Send an email notifying the user that their password was reset.

    A confirmation email is considered a best practice here.
    """
    msg = Message("[Kalanjiyam] Your password was reset", recipients=[email])
    msg.body = render_template("email/confirm-reset-password.txt", username=username)
    mailer.send(msg)


def send_invite_welcome(username: str, email: str, org_name: str, role: str):
    """Notify user that their account was created via org invite.

    TODO: Activate once mail provider is configured.
    """
    # msg = Message(f"[{org_name}] Welcome to your organization", recipients=[email])
    # msg.body = render_template(
    #     "email/invite-welcome.txt",
    #     username=username, org_name=org_name, role=role,
    # )
    # mailer.send(msg)
    pass


def send_invite_join_notification(admin_email: str, org_name: str, new_username: str, role: str):
    """Notify org admin that a new user joined via invite link.

    TODO: Activate once mail provider is configured.
    """
    # msg = Message(f"[Kalanjiyam] New member joined {org_name}", recipients=[admin_email])
    # msg.body = render_template(
    #     "email/invite-join-notification.txt",
    #     org_name=org_name, new_username=new_username, role=role,
    # )
    # mailer.send(msg)
    pass

