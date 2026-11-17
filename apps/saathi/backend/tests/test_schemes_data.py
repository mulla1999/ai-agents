from saathi.config import Settings
from saathi.profile import UserProfile
from saathi.schemes import Status, evaluate_all, load_schemes


def test_bundled_scheme_data_is_valid():
    schemes = load_schemes(Settings().schemes_dir)
    assert len(schemes) >= 9
    for scheme in schemes:
        assert scheme.source_url.startswith("https://"), scheme.id
        assert scheme.documents, scheme.id
        assert "nsap.nic.in" not in scheme.source_url, "nsap.nic.in no longer resolves"


def test_young_farmer_matches_expected_schemes():
    schemes = load_schemes(Settings().schemes_dir)
    profile = UserProfile(
        age=32,
        occupation="farmer",
        gender="male",
        has_bank_account=True,
        owns_cultivable_land=True,
        is_income_tax_payer=False,
        is_government_employee=False,
        plans_new_business=False,
        is_studying_post_matric=False,
        is_bpl=False,
    )
    eligible = {m.scheme.id for m in evaluate_all(schemes, profile) if m.status is Status.ELIGIBLE}
    assert eligible == {"pm-kisan", "atal-pension-yojana", "pmjjby", "pmsby"}


def test_widow_pension_has_no_upper_age_limit():
    schemes = {s.id: s for s in load_schemes(Settings().schemes_dir)}
    profile = UserProfile(age=85, gender="female", is_widow=True, is_bpl=True)
    [match] = evaluate_all([schemes["ignwps"]], profile)
    assert match.status is Status.ELIGIBLE


def test_ended_schemes_are_not_seeded():
    ids = {s.id for s in load_schemes(Settings().schemes_dir)}
    assert "stand-up-india" not in ids
