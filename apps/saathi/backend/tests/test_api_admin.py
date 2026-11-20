import pytest

from saathi.db import Role


@pytest.fixture
async def admin(make_client, login):
    client = make_client()
    await login(client, "9876500009", Role.ADMIN)
    return client


async def test_admin_routes_need_admin_role(citizen_client, make_client, login):
    helper = make_client()
    await login(helper, "9876500003", Role.HELPER)
    for client in (citizen_client, helper):
        assert (await client.get("/api/admin/schemes")).status_code == 403
        assert (await client.get("/api/admin/users")).status_code == 403
    assert (await make_client().get("/api/admin/stats")).status_code == 401


async def test_editing_a_scheme_versions_it_and_requires_reverification(admin, citizen_client):
    scheme = (await admin.get("/api/admin/schemes/pmsby")).json()
    verified = (await admin.post("/api/admin/schemes/pmsby/verify")).json()
    assert verified["status"] == "verified" and verified["verified_on"]

    body = {k: scheme[k] for k in (
        "id", "name", "level", "state", "ministry", "tags", "summary", "benefits",
        "eligibility", "documents", "notes", "how_to_apply", "apply_url", "source_url",
    )}  # fmt: skip
    body["benefits"] = "Updated benefits text"
    edited = (await admin.put("/api/admin/schemes/pmsby", json=body)).json()
    assert edited["status"] == "draft" and edited["verified_on"] is None and edited["version"] == 2

    revisions = (await admin.get("/api/admin/schemes/pmsby/revisions")).json()
    assert [r["version"] for r in revisions] == [2, 1]

    public = (await citizen_client.get("/api/schemes/pmsby")).json()
    assert public["benefits"] == "Updated benefits text"


async def test_invalid_rules_are_rejected(admin):
    scheme = (await admin.get("/api/admin/schemes/pmsby")).json()
    body = {k: v for k, v in scheme.items() if k not in ("status", "verified_on", "version", "updated_at")}
    body["eligibility"] = [{"field": "caste", "op": "eq", "value": "x", "reason": "r"}]
    assert (await admin.put("/api/admin/schemes/pmsby", json=body)).status_code == 422
    body["id"] = "renamed"
    body["eligibility"] = scheme["eligibility"]
    assert (await admin.put("/api/admin/schemes/pmsby", json=body)).status_code == 400


async def test_archived_schemes_leave_the_catalogue_and_eligibility(admin, citizen_client):
    await admin.post("/api/admin/schemes/pmsby/archive")
    assert (await citizen_client.get("/api/schemes/pmsby")).status_code == 404
    me = (await citizen_client.get("/api/me/citizen")).json()
    results = (await citizen_client.get(f"/api/citizens/{me['id']}/eligibility")).json()
    assert "pmsby" not in {r["scheme_id"] for r in results}


async def test_role_management(admin, citizen_client):
    me = (await citizen_client.get("/api/auth/me")).json()
    promoted = await admin.patch(f"/api/admin/users/{me['id']}", json={"role": "helper"})
    assert promoted.json()["role"] == "helper"
    assert (await citizen_client.get("/api/citizens")).status_code == 200

    admin_me = (await admin.get("/api/auth/me")).json()
    assert (await admin.patch(f"/api/admin/users/{admin_me['id']}", json={"role": "citizen"})).status_code == 400


async def test_stats(admin, citizen_client):
    stats = (await admin.get("/api/admin/stats")).json()
    assert stats["users_by_role"] == {"admin": 1, "citizen": 1}
    assert stats["schemes_by_status"]["draft"] == 2


async def test_applies_to_is_kept_when_an_edit_leaves_it_out(admin):
    scheme = (await admin.get("/api/admin/schemes/pm-kisan")).json()
    assert scheme["applies_to"] == "household"
    body = {k: v for k, v in scheme.items() if k not in ("applies_to", "status", "verified_on", "version", "updated_at")}
    assert (await admin.put("/api/admin/schemes/pm-kisan", json=body)).json()["applies_to"] == "household"

    body["applies_to"] = "person"
    assert (await admin.put("/api/admin/schemes/pm-kisan", json=body)).json()["applies_to"] == "person"


async def test_sync_schemes_dry_run_then_apply(sessionmaker, settings, admin):
    from saathi.db import SchemeRecord, SchemeRevision, SchemeStatus
    from saathi.services.schemes import sync_schemes
    from sqlalchemy import func, select

    async with sessionmaker() as db:  # an old, wrong copy in the database, and an archived scheme
        old = await db.get(SchemeRecord, "pmsby")
        old.benefits, old.status = "outdated text", SchemeStatus.DRAFT
        (await db.get(SchemeRecord, "pmjjby")).status = SchemeStatus.ARCHIVED
        (await db.get(SchemeRecord, "pmjjby")).benefits = "outdated text"
        await db.commit()

    async with sessionmaker() as db:
        planned = dict(await sync_schemes(db, settings.schemes_dir, apply=False))
        assert planned["pmsby"] == "update" and planned["pmjjby"] == "skip (archived)"
        assert (await db.get(SchemeRecord, "pmsby")).benefits == "outdated text"  # dry run changed nothing

        await sync_schemes(db, settings.schemes_dir, apply=True)
        record = await db.get(SchemeRecord, "pmsby")
        assert record.benefits.startswith("Rs 2 lakh") and record.status is SchemeStatus.VERIFIED
        assert record.version == 2
        revisions = await db.scalar(select(func.count()).select_from(SchemeRevision).where(SchemeRevision.scheme_id == "pmsby"))
        assert revisions == 2
        assert (await db.get(SchemeRecord, "pmjjby")).status is SchemeStatus.ARCHIVED

        assert await sync_schemes(db, settings.schemes_dir, apply=False) == [("pmjjby", "skip (archived)")]
