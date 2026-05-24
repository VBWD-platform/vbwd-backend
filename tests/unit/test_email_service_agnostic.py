"""Sprint 05 — core email service is subscription-agnostic.

The subscription/payment email methods + templates were removed from core;
plugins own their own email templates and send them through the generic
`send_template` primitive, contributing their template dir via
`register_template_path` (ChoiceLoader).
"""
import os
import tempfile

from vbwd.services.email_service import EmailService


def _service(template_dir):
    return EmailService(
        smtp_host="localhost",
        smtp_port=25,
        smtp_user="u",
        smtp_password="p",
        from_email="from@example.com",
        template_dir=template_dir,
    )


def test_core_email_service_has_no_subscription_methods():
    for name in (
        "send_subscription_activated",
        "send_subscription_cancelled",
        "send_payment_receipt",
        "send_payment_failed",
        "send_renewal_reminder",
    ):
        assert not hasattr(EmailService, name), f"core EmailService still has {name}"


def test_core_email_service_keeps_generic_and_core_methods():
    for name in (
        "send_template",
        "send_email",
        "render_template",
        "send_welcome_email",
    ):
        assert hasattr(EmailService, name)


def test_register_template_path_resolves_plugin_templates():
    """A plugin-registered dir is searched by render_template (ChoiceLoader)."""
    with tempfile.TemporaryDirectory() as core_dir, tempfile.TemporaryDirectory() as plugin_dir:
        # core has nothing; plugin ships sub_demo.{txt,html}
        with open(os.path.join(plugin_dir, "sub_demo.txt"), "w") as f:
            f.write("Hi {{ name }}")
        with open(os.path.join(plugin_dir, "sub_demo.html"), "w") as f:
            f.write("<p>Hi {{ name }}</p>")

        service = _service(core_dir)
        service.register_template_path(plugin_dir)

        text_body, html_body = service.render_template("sub_demo", {"name": "Ada"})
        assert text_body == "Hi Ada"
        assert "Hi Ada" in html_body
