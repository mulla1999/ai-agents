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
        has_paid_income_tax=False,
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


# --- corrections from the November 2026 verification against official sources -------------------


def _status(scheme_id: str, **facts) -> Status:
    schemes = {s.id: s for s in load_schemes(Settings().schemes_dir)}
    [match] = evaluate_all([schemes[scheme_id]], UserProfile(**facts))
    return match.status


def test_spouse_of_a_taxpayer_can_join_apy():
    # PFRDA: only the applicant's own income-tax status counts.
    facts = {"age": 30, "has_bank_account": True, "is_income_tax_payer": True, "has_paid_income_tax": False}
    assert _status("atal-pension-yojana", **facts) is Status.ELIGIBLE


def test_ujjwala_is_open_to_any_poor_household_by_declaration():
    # An OBC woman without an AAY/PHH card or BPL listing qualifies through the deprivation declaration.
    facts = {"age": 30, "gender": "female", "social_category": "obc", "has_lpg_connection": False}
    assert _status("pm-ujjwala", **facts) is Status.ELIGIBLE


def test_disability_pension_has_no_upper_age_limit():
    assert _status("igndps", age=85, disability_percent=90, is_bpl=True) is Status.ELIGIBLE


def test_pmsby_cover_ends_at_70():
    assert _status("pmsby", age=70, has_bank_account=True) is Status.NOT_ELIGIBLE


def test_kanya_sumangala_follows_the_stage_age_bands():
    base = {"state": "uttar_pradesh", "gender": "female", "annual_family_income": 200_000}
    assert _status("kanya-sumangala", age=1, **base) is Status.ELIGIBLE
    assert _status("kanya-sumangala", age=3, **base) is Status.NOT_ELIGIBLE  # between stages
    assert _status("kanya-sumangala", age=6, **base) is Status.ELIGIBLE
    assert _status("kanya-sumangala", age=18, is_studying_post_matric=False, **base) is Status.NOT_ELIGIBLE
    assert _status("kanya-sumangala", age=18, is_studying_post_matric=True, **base) is Status.ELIGIBLE
    assert _status("kanya-sumangala", age=21, is_studying_post_matric=True, **base) is Status.NOT_ELIGIBLE


def test_pmmvy_mother_age_limits():
    base = {"gender": "female", "is_pregnant_or_lactating": True, "is_government_employee": False, "is_bpl": True}
    assert _status("pmmvy", age=25, **base) is Status.ELIGIBLE
    assert _status("pmmvy", age=56, **base) is Status.NOT_ELIGIBLE


def test_only_unconfirmed_schemes_remain_drafts():
    drafts = {s.id for s in load_schemes(Settings().schemes_dir) if s.verified_on is None}
    assert drafts == {"pm-vishwakarma", "up-widow-pension"}
