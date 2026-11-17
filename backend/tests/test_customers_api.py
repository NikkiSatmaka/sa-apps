import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.customer import Customer


class FakeSession:
    def __init__(self, *, customers=(), existing=None, customer=None, duplicate=None):
        self.customers = list(customers)
        self.added = []
        self.execute = AsyncMock()
        scalar_result = existing if existing is not None else duplicate
        self.scalar = AsyncMock(return_value=scalar_result)
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.get = AsyncMock(return_value=customer)
        self.flush = AsyncMock(side_effect=self._flush)

    def add(self, value):
        self.added.append(value)

    async def _flush(self):
        for value in self.added:
            if isinstance(value, Customer) and value.id is None:
                value.id = uuid.uuid4()


@contextmanager
def api_as(user, session):
    async def get_session():
        yield session

    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def user(role="Sales", *, is_admin=False):
    return MagicMock(role=role, is_admin=is_admin)


def test_list_customers_returns_sorted_customer_identity():
    customers = [
        Customer(id=uuid.uuid4(), name="Acme", normalized_name="acme"),
        Customer(id=uuid.uuid4(), name="Beta", normalized_name="beta"),
    ]
    session = FakeSession(customers=customers)
    result = MagicMock()
    result.scalars.return_value.all.return_value = customers
    session.execute.return_value = result
    expected = sorted(customers, key=lambda customer: customer.name)

    with api_as(user("Product"), session) as client:
        response = client.get("/api/v1/customers")

    assert response.status_code == 200
    assert response.json() == [{"id": str(c.id), "name": c.name} for c in expected]


def test_list_customers_rejects_unprivileged_role():
    with api_as(user("SA"), FakeSession()) as client:
        response = client.get("/api/v1/customers")

    assert response.status_code == 403


def test_create_customer_trims_and_persists_new_identity():
    session = FakeSession()
    with api_as(user("Lead_SA"), session) as client:
        response = client.post("/api/v1/customers", json={"name": "  PT Acme  "})

    assert response.status_code == 201
    assert response.json()["name"] == "PT Acme"
    assert len(session.added) == 1
    assert session.added[0].name == "PT Acme"
    assert session.added[0].normalized_name == "pt acme"
    assert response.json()["id"] == str(session.added[0].id)
    session.commit.assert_awaited_once()

def test_create_customer_reuses_existing_normalized_identity():
    customer = Customer(id=uuid.uuid4(), name="PT Acme", normalized_name="pt acme")
    session = FakeSession(existing=customer)
    with api_as(user("Lead_SA"), session) as client:
        response = client.post("/api/v1/customers", json={"name": "PT ACME"})
    assert response.status_code == 201
    assert response.json() == {"id": str(customer.id), "name": "PT Acme"}
    assert session.added == []


@pytest.mark.parametrize("role,is_admin", [("Sales", False), ("Product", False), ("SA", False), ("Admin", False)])
def test_create_customer_rejects_unprivileged_role(role, is_admin):
    with api_as(user(role, is_admin=is_admin), FakeSession()) as client:
        response = client.post("/api/v1/customers", json={"name": "Acme"})

    assert response.status_code == 403


def test_create_customer_rejects_name_that_normalizes_empty():
    with api_as(user("Lead_SA"), FakeSession()) as client:
        response = client.post("/api/v1/customers", json={"name": "   "})

    assert response.status_code == 422

def test_rename_customer_updates_customer_identity_and_returns_new_name():
    customer = Customer(id=uuid.uuid4(), name="Old Name", normalized_name="old name")
    session = FakeSession(customer=customer)
    with api_as(user("Lead_SA"), session) as client:
        response = client.patch(
            f"/api/v1/customers/{customer.id}", json={"name": "  New Name  "}
        )

    assert response.status_code == 200
    assert response.json() == {"id": str(customer.id), "name": "New Name"}
    assert (customer.name, customer.normalized_name) == ("New Name", "new name")
    session.commit.assert_awaited_once()


def test_rename_customer_rejects_missing_identity():
    with api_as(user("Lead_SA"), FakeSession(customer=None)) as client:
        response = client.patch(f"/api/v1/customers/{uuid.uuid4()}", json={"name": "Acme"})

    assert response.status_code == 404


def test_rename_customer_rejects_name_that_normalizes_empty():
    customer = Customer(id=uuid.uuid4(), name="Acme", normalized_name="acme")
    with api_as(user("Lead_SA"), FakeSession(customer=customer)) as client:
        response = client.patch(f"/api/v1/customers/{customer.id}", json={"name": " "})

    assert response.status_code == 422


def test_rename_customer_rejects_duplicate_identity():
    customer = Customer(id=uuid.uuid4(), name="Acme", normalized_name="acme")
    duplicate = Customer(id=uuid.uuid4(), name="Beta", normalized_name="beta")
    session = FakeSession(customer=customer, duplicate=duplicate)
    with api_as(user("Lead_SA"), session) as client:
        response = client.patch(f"/api/v1/customers/{customer.id}", json={"name": "Beta"})

    assert response.status_code == 409
    assert customer.name == "Acme"


@pytest.mark.parametrize("role,is_admin", [("Sales", False), ("Admin", False)])
def test_rename_customer_requires_lead_sa_or_admin(role, is_admin):
    customer = Customer(id=uuid.uuid4(), name="Acme", normalized_name="acme")
    with api_as(user(role, is_admin=is_admin), FakeSession(customer=customer)) as client:
        response = client.patch(f"/api/v1/customers/{customer.id}", json={"name": "Beta"})
    assert response.status_code == 403


def test_admin_can_list_and_create_customer():
    customer = Customer(id=uuid.uuid4(), name="Acme", normalized_name="acme")
    session = FakeSession(customers=[customer])
    result = MagicMock()
    result.scalars.return_value.all.return_value = [customer]
    session.execute.return_value = result

    with api_as(user("SA", is_admin=True), session) as client:
        listed = client.get("/api/v1/customers")
        created = client.post("/api/v1/customers", json={"name": "Beta"})

    assert listed.status_code == 200
    assert created.status_code == 201
    assert created.json()["name"] == "Beta"


def test_admin_can_rename_customer():
    customer = Customer(id=uuid.uuid4(), name="Acme", normalized_name="acme")
    session = FakeSession(customer=customer)
    with api_as(user("Admin", is_admin=True), session) as client:
        response = client.patch(
            f"/api/v1/customers/{customer.id}", json={"name": "Beta"}
        )

    assert response.status_code == 200
    assert (customer.name, customer.normalized_name) == ("Beta", "beta")

def test_project_customer_repair_updates_identity_and_audits_without_changing_drive():
    from app.models.audit_log import AuditLog
    from app.models.project import Project

    old_id, new_id = uuid.uuid4(), uuid.uuid4()
    project = Project(
        id_project="P-1",
        project_name="Migration",
        customer_name="Old Corp",
        customer_id=old_id,
        gdrive_folder_id="master-1",
        gdrive_solutions_folder_id="solutions-1",
        gdrive_folder_number=17,
        folder_provisioning_status="provisioned",
    )
    customer = Customer(id=new_id, name="New Corp", normalized_name="new corp")
    session = FakeSession(customer=customer)
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = project
    session.execute.return_value = lookup
    actor = user("Lead_SA")
    actor.id = uuid.uuid4()

    with api_as(actor, session) as client:
        response = client.post(
            "/api/v1/projects/P-1/customer-repair",
            json={"customer_id": str(new_id), "reason": "Legacy project was linked incorrectly"},
        )

    assert response.status_code == 200
    assert (project.customer_id, project.customer_name) == (new_id, "New Corp")
    assert (
        project.gdrive_folder_id,
        project.gdrive_solutions_folder_id,
        project.gdrive_folder_number,
        project.folder_provisioning_status,
    ) == ("master-1", "solutions-1", 17, "provisioned")
    assert session.commit.await_count == 1
    audit = next(entry for entry in session.added if isinstance(entry, AuditLog))
    assert audit.entity_type == "project"
    assert audit.entity_id == "P-1"
    assert audit.action == "customer_link_repaired"
    assert audit.performed_by == actor.id
    assert audit.old_value["customer"] == {"id": str(old_id), "name": "Old Corp"}
    assert audit.new_value["customer"] == {"id": str(new_id), "name": "New Corp"}
    assert audit.new_value["reason"] == "Legacy project was linked incorrectly"
    assert audit.created_at is not None
    assert audit.new_value["drive_state_unchanged"] == {
        "gdrive_folder_id": "master-1",
        "gdrive_solutions_folder_id": "solutions-1",
        "gdrive_folder_number": 17,
        "folder_provisioning_status": "provisioned",
    }


@pytest.mark.parametrize(
    "role,is_admin,status",
    [("Sales", False, 403), ("SA", False, 403), ("Admin", False, 403), ("SA", True, 200)],
)
def test_project_customer_repair_authorizes_only_lead_sa_or_admin(role, is_admin, status):
    customer = Customer(id=uuid.uuid4(), name="Verified", normalized_name="verified")
    session = FakeSession(customer=customer)
    if is_admin:
        project = MagicMock(customer_id=None, customer_name="Legacy", id_project="P-1")
        result = MagicMock()
        result.scalar_one_or_none.return_value = project
        session.execute.return_value = result
    actor = user(role, is_admin=is_admin)
    with api_as(actor, session) as client:
        response = client.post(
            "/api/v1/projects/P-1/customer-repair",
            json={"customer_id": str(customer.id), "reason": "Verified source record"},
        )
    assert response.status_code == status
    if status == 403:
        session.execute.assert_not_awaited()
        session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"customer_id": str(uuid.uuid4()), "reason": "   "},
        {"customer_id": str(uuid.uuid4()), "reason": ""},
        {"customer_id": str(uuid.uuid4())},
    ],
)
def test_project_customer_repair_rejects_empty_reason_without_mutation(body):
    project = MagicMock(customer_id=None, customer_name="Legacy", id_project="P-1")
    session = FakeSession()
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session.execute.return_value = result
    with api_as(user("Lead_SA"), session) as client:
        response = client.post("/api/v1/projects/P-1/customer-repair", json=body)
    assert response.status_code == 422
    assert project.customer_name == "Legacy"
    assert session.added == []
    session.commit.assert_not_awaited()


def test_project_customer_repair_rejects_missing_customer_without_mutation():
    project = MagicMock(customer_id=None, customer_name="Legacy", id_project="P-1")
    session = FakeSession()
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session.execute.return_value = result
    with api_as(user("Lead_SA"), session) as client:
        response = client.post(
            "/api/v1/projects/P-1/customer-repair",
            json={"customer_id": str(uuid.uuid4()), "reason": "Checked the source document"},
        )
    assert response.status_code == 404
    assert project.customer_name == "Legacy"
    assert session.added == []
    session.commit.assert_not_awaited()


def test_project_customer_repair_attaches_customer_to_unlinked_project():
    from app.models.audit_log import AuditLog

    project = MagicMock(customer_id=None, customer_name="Legacy Organization", id_project="P-2")
    customer = Customer(id=uuid.uuid4(), name="Verified Organization", normalized_name="verified organization")
    session = FakeSession(customer=customer)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session.execute.return_value = result

    with api_as(user("Lead_SA"), session) as client:
        response = client.post(
            "/api/v1/projects/P-2/customer-repair",
            json={"customer_id": str(customer.id), "reason": "Reviewed company registration"},
        )

    assert response.status_code == 200
    assert (project.customer_id, project.customer_name) == (customer.id, customer.name)
    audit = next(entry for entry in session.added if isinstance(entry, AuditLog))
    assert audit.old_value["customer"] == {"id": None, "name": "Legacy Organization"}
