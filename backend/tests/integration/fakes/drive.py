"""
Fake Drive: pengganti API publik `folder_provisioner` (tanpa jaringan, tanpa sleep retry).

Yang diganti adalah method publik pada instance singleton `folder_provisioner`; semua pemanggil
(`assignment`, `documents`, `sla_timer`, `handover_service`) memakai objek yang sama sehingga
terpasang tanpa mengubah kode produksi. Kegagalan mengangkat `FolderProvisioningError`, persis
kontrak produksi setelah retry habis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Any

import pytest

from app.services.folder_provisioner import (
    FolderProvisioningError,
    ProvisionedFolders,
    folder_provisioner,
)

OPERASI = (
    "ensure_customer_folder",
    "list_folder_children",
    "provision_project_folder",
    "create_master_folder",
    "create_inventory_subfolder",
    "create_diagram_subfolder",
    "create_solutions_subfolder",
    "lock_solutions_folder",
    "unlock_solutions_folder",
    "provision_handover",
    "reassign_sa_access",
)

BOUNDARY_METHODS = (
    "ensure_customer_folder",
    "list_folder_children",
    "provision_project_folder",
    "lock_solutions_folder",
    "unlock_solutions_folder",
    "provision_handover",
    "reassign_sa_access",
)

@dataclass
class PanggilanDrive:
    operasi: str
    argumen: dict[str, Any]
    berhasil: bool


@dataclass
class FakeDrive:
    """Pengendali fake Drive. Gunakan lewat fixture `fake_drive`."""

    panggilan: list[PanggilanDrive] = field(default_factory=list)
    folder: dict[str, dict[str, Any]] = field(default_factory=dict)  # id -> {name, parent}
    izin: dict[str, dict[str, str]] = field(default_factory=dict)  # id folder -> {email: role}
    _gagal: list[tuple[str | None, int | None, str]] = field(default_factory=list)
    parent_id: str = "fake-shared-drive-parent"
    _hitung: Any = field(default_factory=lambda: count(1))

    # ------------------------------------------------------------------ pemrograman
    def fail_next(
        self, operasi: str | None = None, *, times: int = 1, pesan: str = "fake Drive gagal"
    ) -> None:
        """Panggilan berikutnya (pada `operasi`, atau apa pun bila None) gagal `times` kali."""
        assert operasi is None or operasi in OPERASI, f"operasi tidak dikenal: {operasi!r}"
        self._gagal.append((operasi, times, pesan))

    def fail_always(self, operasi: str | None = None, *, pesan: str = "fake Drive gagal") -> None:
        """Semua panggilan berikutnya (pada `operasi`, atau semua) gagal sampai fixture di-reset."""
        assert operasi is None or operasi in OPERASI, f"operasi tidak dikenal: {operasi!r}"
        self._gagal.append((operasi, None, pesan))

    # ------------------------------------------------------------------ perekaman
    def panggilan_operasi(self, operasi: str) -> list[PanggilanDrive]:
        return [p for p in self.panggilan if p.operasi == operasi]

    def peran(self, folder_id: str, email: str) -> str | None:
        """Peran (`writer`/`reader`) `email` pada folder, atau None bila tidak punya akses."""
        return self.izin.get(folder_id, {}).get(email)

    # ------------------------------------------------------------------ internal
    def _mulai(self, operasi: str, **argumen: Any) -> None:
        for i, (target, sisa, pesan) in enumerate(self._gagal):
            if target not in (None, operasi):
                continue
            if sisa is not None:
                if sisa <= 1:
                    del self._gagal[i]
                else:
                    self._gagal[i] = (target, sisa - 1, pesan)
            self.panggilan.append(PanggilanDrive(operasi, argumen, berhasil=False))
            raise FolderProvisioningError(pesan)
        self.panggilan.append(PanggilanDrive(operasi, argumen, berhasil=True))

    def _buat_folder(self, nama: str, induk: str | None = None) -> str:
        folder_id = f"fake-folder-{next(self._hitung)}"
        self.folder[folder_id] = {"name": nama, "parent": induk}
        self.izin[folder_id] = {}
        return folder_id

    def seed_folder(self, name: str, parent: str | None = None) -> str:
        """Create a Drive fixture folder without recording a provisioning call."""
        return self._buat_folder(name, parent)

    async def ensure_customer_folder(
        self, customer_name: str, existing_folder_id: str | None = None
    ) -> str:
        self._mulai(
            "ensure_customer_folder",
            customer_name=customer_name,
            existing_folder_id=existing_folder_id,
        )
        if existing_folder_id:
            return existing_folder_id

        name = folder_provisioner.sanitize_folder_name(customer_name.strip())
        matches = [
            folder_id
            for folder_id, folder in self.folder.items()
            if folder["parent"] == self.parent_id
            and folder["name"].strip().casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise FolderProvisioningError(
                f"Multiple Customer folders named '{name}' exist under the configured parent."
            )
        if matches:
            return matches[0]
        return self._buat_folder(name, self.parent_id)

    async def list_folder_children(self, parent_folder_id: str) -> list[dict[str, str]]:
        self._mulai("list_folder_children", parent_folder_id=parent_folder_id)
        return [
            {"id": folder_id, "name": folder["name"]}
            for folder_id, folder in self.folder.items()
            if folder["parent"] == parent_folder_id
        ]

    def _ensure_child_folder(self, name: str, parent_id: str, operation: str) -> str:
        matches = [
            folder_id
            for folder_id, folder in self.folder.items()
            if folder["parent"] == parent_id and folder["name"].casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise FolderProvisioningError(
                f"Multiple '{name}' folders exist under Drive folder '{parent_id}'."
            )
        if matches:
            return matches[0]
        self._mulai(operation, parent_folder_id=parent_id, name=name)
        return self._buat_folder(name, parent_id)


    # ------------------------------------------------------------------ pengganti API publik
    async def provision_project_folder(
        self,
        project: Any,
        sa_email: str,
        lead_sa_email: str,
        sales_email: str,
        *,
        sa_team_emails: tuple[str, ...] = (),
        product_email: str | None = None,
        dq_number: str | None = None,
        persist_master_folder_id=None,
    ) -> ProvisionedFolders:
        self._mulai(
            "provision_project_folder",
            id_project=getattr(project, "id_project", None),
            sa_email=sa_email,
            lead_sa_email=lead_sa_email,
            sales_email=sales_email,
        )
        customer = getattr(project, "customer", None)
        customer_folder_id = getattr(customer, "gdrive_folder_id", None)
        if not customer_folder_id:
            raise FolderProvisioningError("Customer Drive folder ID is missing.")

        master = project.gdrive_folder_id
        if master is None:
            project_number = getattr(project, "gdrive_folder_number", None)
            if project_number is None:
                raise FolderProvisioningError("Project folder number is not reserved.")
            name = (
                f"{project_number:02d}-"
                f"{folder_provisioner.sanitize_folder_name(project.project_name)}"
            )
            matches = [
                folder_id
                for folder_id, folder in self.folder.items()
                if folder["parent"] == customer_folder_id
                and folder["name"].strip().casefold() == name.casefold()
            ]
            if matches:
                raise FolderProvisioningError(
                    f"Project folder '{name}' already exists and is not associated with this project."
                )
            self._mulai(
                "create_master_folder",
                parent_folder_id=customer_folder_id,
                name=name,
            )
            master = self._buat_folder(name, customer_folder_id)
            if persist_master_folder_id is not None:
                await persist_master_folder_id(master)

        inventory = self._ensure_child_folder(
            "Inventory", master, "create_inventory_subfolder"
        )
        diagram = self._ensure_child_folder("Diagram", master, "create_diagram_subfolder")
        solutions = self._ensure_child_folder(
            "Solutions", master, "create_solutions_subfolder"
        )
        sa_emails = dict.fromkeys((*sa_team_emails, sa_email, lead_sa_email))
        for email in sa_emails:
            self.izin[master][email] = "writer"
        for email in (sales_email, product_email):
            if email:
                self.izin[inventory][email] = "reader"
        if dq_number:
            for email in (sales_email, product_email):
                if email:
                    self.izin[solutions][email] = "reader"
        return ProvisionedFolders(
            master=master,
            inventory=inventory,
            diagram=diagram,
            solutions=solutions,
        )

    async def lock_solutions_folder(self, solutions_folder_id: str, sales_email: str) -> None:
        self._mulai(
            "lock_solutions_folder",
            solutions_folder_id=solutions_folder_id,
            sales_email=sales_email,
        )
        self.izin.get(solutions_folder_id, {}).pop(sales_email, None)

    async def unlock_solutions_folder(self, solutions_folder_id: str, sales_email: str) -> None:
        self._mulai(
            "unlock_solutions_folder",
            solutions_folder_id=solutions_folder_id,
            sales_email=sales_email,
        )
        self.izin.setdefault(solutions_folder_id, {})[sales_email] = "reader"

    async def provision_handover(
        self, solutions_folder_id: str, pmo_email: str, delivery_email: str
    ) -> str:
        self._mulai(
            "provision_handover",
            solutions_folder_id=solutions_folder_id,
            pmo_email=pmo_email,
            delivery_email=delivery_email,
        )
        deliverables = self._buat_folder("Final_Deliverables", solutions_folder_id)
        self.izin[deliverables][pmo_email] = "reader"
        self.izin[deliverables][delivery_email] = "reader"
        return deliverables

    async def reassign_sa_access(
        self, master_folder_id: str, old_sa_email: str | None, new_sa_email: str
    ) -> None:
        self._mulai(
            "reassign_sa_access",
            master_folder_id=master_folder_id,
            old_sa_email=old_sa_email,
            new_sa_email=new_sa_email,
        )
        izin = self.izin.setdefault(master_folder_id, {})
        izin[new_sa_email] = "writer"
        if old_sa_email and old_sa_email != new_sa_email:
            izin.pop(old_sa_email, None)

    def pasang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for operasi in BOUNDARY_METHODS:
            monkeypatch.setattr(folder_provisioner, operasi, getattr(self, operasi))
