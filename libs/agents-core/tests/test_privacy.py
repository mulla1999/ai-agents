from agents_core.privacy import redact_pii


def test_redacts_identity_numbers_but_keeps_amounts():
    text = "aadhaar 2345-6789-0123, pan ABCDE1234F, phone 9876543210, acct 123456789012345, income 250000"
    redacted = redact_pii(text)
    for secret in ("2345-6789-0123", "ABCDE1234F", "9876543210", "123456789012345"):
        assert secret not in redacted
    assert "250000" in redacted
