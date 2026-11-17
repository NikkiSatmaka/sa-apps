"""
Folder Provisioner — provisioning Customer dan folder proyek bernomor di Google Drive.

Membuat atau memakai ulang folder Customer, menyediakan proyek baru sebagai
`NN-<Project>` di dalamnya, mengelola permission, serta mendukung lock/unlock
folder Solutions berdasarkan SLA.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from functools import partial
from typing import Any, Awaitable, Callable, Optional, Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Karakter tidak valid untuk nama folder Google Drive
INVALID_FOLDER_CHARS = re.compile(r'[/\\*?"]')

# Retry configuration
MAX_RETRIES = 3
RETRY_INTERVAL_SECONDS = 5


class FolderProvisioningError(Exception):
    """Exception saat provisioning folder gagal setelah semua retry."""

    pass


class FolderConflictError(FolderProvisioningError):
    """A named Drive folder exists but cannot be safely associated with this operation."""


@dataclass
class ProvisionedFolders:
    """Kontrak id folder hasil provisioning (ADR 0005).

    master: ID folder master proyek
    inventory: ID subfolder Inventory
    diagram: ID subfolder Diagram
    solutions: ID subfolder Solutions
    """

    master: str
    inventory: str
    diagram: str
    solutions: str


class FolderProvisioner:
    """
    Mengelola auto-provisioning folder Google Drive untuk proyek.

    Struktur folder yang dibuat:
        Customer/
        └── NN-Project/
            ├── Inventory/    (Viewer: Sales)
            ├── Diagram/      (Editor: SA + Lead_SA, No Access: Sales)
            └── Solutions/    (Editor: SA + Lead_SA, No Access: Sales → Viewer setelah DQ)
                └── Final_Deliverables/  (dibuat saat handover)
    """

    def __init__(self) -> None:
        """Inisialisasi Google Drive service menggunakan service account credentials."""
        self._drive_service = None

    def _get_drive_service(self):
        """
        Lazy initialization Google Drive service.
        Menggunakan service account key dari settings.
        """
        if self._drive_service is not None:
            return self._drive_service

        if not settings.GDRIVE_SERVICE_ACCOUNT_KEY:
            logger.warning("GDRIVE_SERVICE_ACCOUNT_KEY belum dikonfigurasi")
            raise FolderProvisioningError(
                "Google Drive service account key belum dikonfigurasi. "
                "Set GDRIVE_SERVICE_ACCOUNT_KEY di environment variables."
            )

        try:
            # Parse JSON key dari environment variable
            key_data = json.loads(settings.GDRIVE_SERVICE_ACCOUNT_KEY)
            credentials = service_account.Credentials.from_service_account_info(
                key_data,
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            self._drive_service = build("drive", "v3", credentials=credentials)
            return self._drive_service
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Gagal parse service account key: {e}")
            raise FolderProvisioningError(f"Format GDRIVE_SERVICE_ACCOUNT_KEY tidak valid: {e}")

    def sanitize_folder_name(self, name: str) -> str:
        """
        Ganti karakter tidak valid untuk nama folder Google Drive dengan underscore.

        Karakter yang diganti: / \\ * ? "

        Args:
            name: Nama asli (customer name atau project name)

        Returns:
            Nama yang sudah disanitasi, aman untuk folder Google Drive
        """
        return INVALID_FOLDER_CHARS.sub("_", name)

    async def _execute_with_retry(self, operation_name: str, func, *args, **kwargs):
        """
        Eksekusi operasi Google Drive dengan retry logic.

        Retry: 3 kali dengan interval 5 detik.
        Jika semua retry gagal, raise FolderProvisioningError.

        Args:
            operation_name: Nama operasi untuk logging
            func: Fungsi synchronous yang akan dieksekusi
            *args, **kwargs: Argumen untuk fungsi

        Returns:
            Hasil dari fungsi yang dieksekusi

        Raises:
            FolderProvisioningError: Jika semua retry habis
        """
        last_error = None
        loop = asyncio.get_running_loop()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Jalankan operasi sync di executor agar tidak blocking event loop
                result = await loop.run_in_executor(None, partial(func, *args, **kwargs))
                return result
            except FolderConflictError:
                raise
            except HttpError as e:
                last_error = e
                logger.warning(f"[{operation_name}] Percobaan {attempt}/{MAX_RETRIES} gagal: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_INTERVAL_SECONDS)
            except Exception as e:
                last_error = e
                logger.error(
                    f"[{operation_name}] Error tidak terduga pada percobaan "
                    f"{attempt}/{MAX_RETRIES}: {e}"
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_INTERVAL_SECONDS)

        # Semua retry gagal
        error_msg = (
            f"[{operation_name}] Gagal setelah {MAX_RETRIES} percobaan. "
            f"Error terakhir: {last_error}"
        )
        logger.error(error_msg)
        raise FolderProvisioningError(error_msg)

    def _create_folder_sync(
        self,
        name: str,
        parent_id: Optional[str] = None,
        app_properties: Optional[dict[str, str]] = None,
    ) -> str:
        """
        Buat folder di Google Drive (synchronous).

        Args:
            name: Nama folder
            parent_id: ID folder parent (opsional)

        Returns:
            ID folder yang dibuat
        """
        service = self._get_drive_service()
        file_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            file_metadata["parents"] = [parent_id]
        if app_properties:
            file_metadata["appProperties"] = app_properties

        folder = (
            service.files()
            .create(
                body=file_metadata,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )

        return folder.get("id")

    def _list_folder_children_sync(self, parent_id: str) -> list[dict[str, Any]]:
        """List all immediate child folders for a Shared Drive folder."""
        service = self._get_drive_service()
        children: list[dict[str, str]] = []
        page_token = None
        while True:
            response = (
                service.files()
                .list(
                    q=(
                        f"'{parent_id}' in parents and trashed = false and "
                        "mimeType = 'application/vnd.google-apps.folder'"
                    ),
                    fields="nextPageToken,files(id,name,appProperties)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                .execute()
            )
            children.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return children

    async def list_folder_children(self, parent_folder_id: str) -> list[dict[str, Any]]:
        """List immediate child folders from Google Drive."""
        return await self._execute_with_retry(
            "list_folder_children", self._list_folder_children_sync, parent_folder_id
        )

    def _ensure_customer_folder_sync(self, name: str, parent_id: str) -> str:
        matches = [
            folder
            for folder in self._list_folder_children_sync(parent_id)
            if folder.get("name", "").strip().casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise FolderConflictError(
                f"Multiple Customer folders named '{name}' exist under the configured "
                "Shared Drive parent. Remove or rename duplicates before provisioning."
            )
        if matches:
            return matches[0]["id"]
        return self._create_folder_sync(name, parent_id)

    def _create_project_folder_sync(
        self, name: str, parent_id: str, project_id: str
    ) -> str:
        children = self._list_folder_children_sync(parent_id)
        associated = [
            folder
            for folder in children
            if folder.get("appProperties", {}).get("portalSaProjectId") == project_id
        ]
        matches = [
            folder
            for folder in children
            if folder.get("name", "").strip().casefold() == name.casefold()
        ]
        if len(associated) > 1:
            raise FolderConflictError(
                f"Multiple project folders are associated with project '{project_id}' "
                f"under Customer folder '{parent_id}'. Resolve the duplicates manually."
            )
        if associated:
            if any(folder["id"] != associated[0]["id"] for folder in matches):
                raise FolderConflictError(
                    f"Project folder '{name}' collides with another folder under the Customer "
                    f"directory for project '{project_id}'. Resolve the duplicates manually."
                )
            return associated[0]["id"]

        if matches:
            raise FolderConflictError(
                f"Project folder '{name}' already exists under the Customer folder but is not "
                f"associated with project '{project_id}'. Verify the folder and project number; "
                "it was not reused."
            )
        return self._create_folder_sync(
            name,
            parent_id,
            app_properties={"portalSaProjectId": project_id},
        )

    async def ensure_customer_folder(
        self, customer_name: str, existing_folder_id: Optional[str] = None
    ) -> str:
        """Reuse a stored Customer folder ID, or resolve/create one under the configured parent."""
        if existing_folder_id:
            return existing_folder_id

        parent_folder_id = settings.GDRIVE_PARENT_FOLDER_ID.strip()
        if not parent_folder_id:
            raise FolderProvisioningError(
                "GDRIVE_PARENT_FOLDER_ID must identify a writable Shared Drive parent folder."
            )

        folder_name = self.sanitize_folder_name(customer_name.strip())
        return await self._execute_with_retry(
            "ensure_customer_folder",
            self._ensure_customer_folder_sync,
            folder_name,
            parent_folder_id,
        )


    def _ensure_child_folder_sync(self, name: str, parent_id: str) -> str:
        matches = [
            folder
            for folder in self._list_folder_children_sync(parent_id)
            if folder.get("name", "").strip().casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise FolderConflictError(
                f"Multiple '{name}' folders exist under Drive folder '{parent_id}'. "
                "Remove duplicates before retrying provisioning."
            )
        if matches:
            return matches[0]["id"]
        return self._create_folder_sync(name, parent_id)

    async def _ensure_child_folder(
        self, name: str, parent_id: str, operation_name: str
    ) -> str:
        return await self._execute_with_retry(
            operation_name, self._ensure_child_folder_sync, name, parent_id
        )

    def _set_permission_sync(self, file_id: str, email: str, role: str) -> str:
        """
        Set permission pada file/folder di Google Drive (synchronous).

        Args:
            file_id: ID file atau folder
            email: Email user yang diberi akses
            role: Role permission (writer/reader)

        Returns:
            ID permission yang dibuat
        """
        service = self._get_drive_service()
        permission = {
            "type": "user",
            "role": role,
            "emailAddress": email,
        }
        result = (
            service.permissions()
            .create(
                fileId=file_id,
                body=permission,
                sendNotificationEmail=False,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )

        return result.get("id")

    def _remove_permission_sync(self, file_id: str, permission_id: str) -> None:
        """
        Hapus permission dari file/folder di Google Drive (synchronous).

        Args:
            file_id: ID file atau folder
            permission_id: ID permission yang akan dihapus
        """
        service = self._get_drive_service()
        service.permissions().delete(
            fileId=file_id,
            permissionId=permission_id,
            supportsAllDrives=True,
        ).execute()

    def _find_permission_sync(self, file_id: str, email: str) -> Optional[str]:
        """
        Cari permission ID berdasarkan email pada file/folder (synchronous).

        Args:
            file_id: ID file atau folder
            email: Email user yang dicari

        Returns:
            Permission ID jika ditemukan, None jika tidak
        """
        service = self._get_drive_service()
        permissions = (
            service.permissions()
            .list(
                fileId=file_id,
                fields="permissions(id,emailAddress)",
                supportsAllDrives=True,
            )
            .execute()
        )

        for perm in permissions.get("permissions", []):
            if perm.get("emailAddress", "").lower() == email.lower():
                return perm.get("id")
        return None

    async def provision_project_folder(
        self,
        project,
        sa_email: str,
        lead_sa_email: str,
        sales_email: str,
        *,
        sa_team_emails: Sequence[str] = (),
        product_email: Optional[str] = None,
        dq_number: Optional[str] = None,
        persist_master_folder_id: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> ProvisionedFolders:
        """Create or resume a numbered Customer project folder and its subfolders."""
        customer = getattr(project, "customer", None)
        customer_folder_id = getattr(customer, "gdrive_folder_id", None)
        master_id = project.gdrive_folder_id
        if master_id is None and not customer_folder_id:
            raise FolderProvisioningError(
                "The project has no stored Customer Drive folder. Retry after its Customer "
                "identity and Drive folder have been provisioned."
            )

        if master_id is None:
            project_number = project.gdrive_folder_number
            if project_number is None:
                raise FolderProvisioningError(
                    "No project folder number is reserved for this Customer. Retry provisioning."
                )

            project_name = self.sanitize_folder_name(project.project_name)
            master_folder_name = f"{project_number:02d}-{project_name}"
            master_id = await self._execute_with_retry(
                "create_master_folder",
                self._create_project_folder_sync,
                master_folder_name,
                customer_folder_id,
                project.id_project,
            )
            if persist_master_folder_id is not None:
                await persist_master_folder_id(master_id)

        logger.info(
            "Provisioning project folder %s under Customer folder %s",
            project.id_project,
            customer_folder_id,
        )

        inventory_id = await self._ensure_child_folder(
            "Inventory", master_id, "create_inventory_subfolder"
        )
        diagram_id = await self._ensure_child_folder(
            "Diagram", master_id, "create_diagram_subfolder"
        )
        solutions_id = await self._ensure_child_folder(
            "Solutions", master_id, "create_solutions_subfolder"
        )

        sa_emails = dict.fromkeys((*sa_team_emails, sa_email, lead_sa_email))
        for email in sa_emails:
            await self._execute_with_retry(
                "set_permission_sa_team",
                self._set_permission_sync,
                master_id,
                email,
                "writer",
            )

        for role_email in (sales_email, product_email):
            if role_email:
                await self._execute_with_retry(
                    "set_permission_sales_product_inventory",
                    self._set_permission_sync,
                    inventory_id,
                    role_email,
                    "reader",
                )

        if dq_number:
            for role_email in (sales_email, product_email):
                if role_email:
                    await self._execute_with_retry(
                        "set_permission_sales_product_solutions",
                        self._set_permission_sync,
                        solutions_id,
                        role_email,
                        "reader",
                    )

        return ProvisionedFolders(
            master=master_id,
            inventory=inventory_id,
            diagram=diagram_id,
            solutions=solutions_id,
        )

    async def reassign_sa_access(
        self,
        master_folder_id: str,
        old_sa_email: Optional[str],
        new_sa_email: str,
    ) -> None:
        """Grant Editor access to the newly assigned SA without revoking team access.

        Args:
            master_folder_id: ID folder master proyek (`gdrive_folder_id`)
            old_sa_email: Email SA sebelumnya (dipertahankan sebagai anggota tim)
            new_sa_email: Email SA baru yang ditugaskan

        Raises:
            FolderProvisioningError: Jika gagal setelah 3x retry
        """
        if old_sa_email and old_sa_email.lower() == new_sa_email.lower():
            return

        logger.info(
            "Ensuring Editor access for assigned SA %s on folder %s",
            new_sa_email,
            master_folder_id,
        )

        sudah_punya = await self._execute_with_retry(
            "find_new_sa_permission",
            self._find_permission_sync,
            master_folder_id,
            new_sa_email,
        )
        if not sudah_punya:
            await self._execute_with_retry(
                "set_permission_new_sa",
                self._set_permission_sync,
                master_folder_id,
                new_sa_email,
                "writer",
            )

    async def lock_solutions_folder(
        self, solutions_folder_id: str, sales_email: str, product_email: Optional[str] = None
    ) -> None:
        """Remove assigned Sales and Product Viewer permissions from Solutions."""
        for email in dict.fromkeys(filter(None, (sales_email, product_email))):
            permission_id = await self._execute_with_retry(
                "find_requester_permission",
                self._find_permission_sync,
                solutions_folder_id,
                email,
            )
            if permission_id:
                await self._execute_with_retry(
                    "remove_requester_permission",
                    self._remove_permission_sync,
                    solutions_folder_id,
                    permission_id,
                )

    async def unlock_solutions_folder(
        self, solutions_folder_id: str, sales_email: str, product_email: Optional[str] = None
    ) -> None:
        """Restore assigned Sales and Product Viewer permissions on Solutions."""
        for email in dict.fromkeys(filter(None, (sales_email, product_email))):
            permission_id = await self._execute_with_retry(
                "find_requester_permission",
                self._find_permission_sync,
                solutions_folder_id,
                email,
            )
            if not permission_id:
                await self._execute_with_retry(
                    "restore_requester_permission",
                    self._set_permission_sync,
                    solutions_folder_id,
                    email,
                    "reader",
                )

    async def provision_handover(
        self,
        solutions_folder_id: str,
        pmo_email: str,
        delivery_email: str,
    ) -> str:
        """
        Buat subfolder Final_Deliverables di Solutions dan set permission PMO/Delivery.

        Dipanggil saat proyek Won dan HLD berstatus "Final".

        Args:
            solutions_folder_id: ID folder Solutions di Google Drive
            pmo_email: Email PMO Lead
            delivery_email: Email Delivery Lead

        Returns:
            ID subfolder Final_Deliverables yang dibuat

        Raises:
            FolderProvisioningError: Jika gagal setelah 3x retry
        """
        logger.info(
            f"Provisioning handover - membuat Final_Deliverables "
            f"di folder Solutions ({solutions_folder_id})"
        )

        # 1. Buat subfolder Final_Deliverables
        deliverables_id = await self._execute_with_retry(
            "create_final_deliverables",
            self._create_folder_sync,
            "Final_Deliverables",
            solutions_folder_id,
        )

        # 2. Set Viewer permission untuk PMO Lead
        await self._execute_with_retry(
            "set_permission_pmo",
            self._set_permission_sync,
            deliverables_id,
            pmo_email,
            "reader",
        )

        # 3. Set Viewer permission untuk Delivery Lead
        await self._execute_with_retry(
            "set_permission_delivery",
            self._set_permission_sync,
            deliverables_id,
            delivery_email,
            "reader",
        )

        logger.info(
            f"Handover provisioning selesai. "
            f"Final_Deliverables: {deliverables_id}, "
            f"PMO: {pmo_email}, Delivery: {delivery_email}"
        )

        return deliverables_id


# Singleton instance
folder_provisioner = FolderProvisioner()
