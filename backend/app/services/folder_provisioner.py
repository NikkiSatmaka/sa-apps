"""
Folder Provisioner — Modul auto-provisioning folder Google Drive.

Membuat struktur folder proyek secara otomatis di Google Drive,
mengelola permission (Editor/Viewer) untuk SA, Lead_SA, dan Sales,
serta mendukung lock/unlock folder Solutions berdasarkan SLA.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from functools import partial
from typing import Optional

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
        [Customer_Name] - [Project_Name]/
        ├── Inventory/    (Viewer: Sales, Editor: SA + Lead_SA)
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

    def _create_folder_sync(self, name: str, parent_id: Optional[str] = None) -> str:
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

        folder = (
            service.files()
            .create(
                body=file_metadata,
                fields="id",
            )
            .execute()
        )

        return folder.get("id")

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
    ) -> ProvisionedFolders:
        """
        Buat folder master proyek + 3 subfolder dan set permission.

        Struktur:
            [Customer_Name] - [Project_Name]/
            ├── Inventory/    (Viewer: Sales)
            ├── Diagram/      (No access: Sales)
            └── Solutions/    (No access: Sales)

        Permission pada folder master: Editor untuk SA + Lead_SA (inherited ke subfolder).
        Permission tambahan pada Inventory: Viewer untuk Sales.

        Args:
            project: Object Project dengan atribut customer_name dan project_name
            sa_email: Email SA yang ditugaskan
            lead_sa_email: Email Lead SA
            sales_email: Email Sales PIC

        Returns:
            ProvisionedFolders: id folder master + subfolder
            (inventory/diagram/solutions)

        Raises:
            FolderProvisioningError: Jika gagal setelah 3x retry
        """
        # Sanitasi nama folder
        customer = self.sanitize_folder_name(project.customer_name)
        project_name = self.sanitize_folder_name(project.project_name)
        master_folder_name = f"{customer} - {project_name}"

        logger.info(f"Memulai provisioning folder: {master_folder_name}")

        # 1. Buat folder master
        master_id = await self._execute_with_retry(
            "create_master_folder",
            self._create_folder_sync,
            master_folder_name,
        )
        logger.info(f"Folder master dibuat: {master_id}")

        # 2. Buat 3 subfolder
        inventory_id = await self._execute_with_retry(
            "create_inventory_subfolder",
            self._create_folder_sync,
            "Inventory",
            master_id,
        )

        diagram_id = await self._execute_with_retry(
            "create_diagram_subfolder",
            self._create_folder_sync,
            "Diagram",
            master_id,
        )

        solutions_id = await self._execute_with_retry(
            "create_solutions_subfolder",
            self._create_folder_sync,
            "Solutions",
            master_id,
        )

        logger.info(
            f"Subfolder dibuat - Inventory: {inventory_id}, "
            f"Diagram: {diagram_id}, Solutions: {solutions_id}"
        )

        # 3. Set permission Editor pada folder master untuk SA + Lead_SA
        # (inherited ke semua subfolder)
        await self._execute_with_retry(
            "set_permission_sa",
            self._set_permission_sync,
            master_id,
            sa_email,
            "writer",
        )

        await self._execute_with_retry(
            "set_permission_lead_sa",
            self._set_permission_sync,
            master_id,
            lead_sa_email,
            "writer",
        )

        # 4. Set permission Viewer untuk Sales HANYA pada Inventory
        await self._execute_with_retry(
            "set_permission_sales_inventory",
            self._set_permission_sync,
            inventory_id,
            sales_email,
            "reader",
        )

        logger.info(
            f"Permission berhasil diset untuk proyek: "
            f"{project.customer_name} - {project.project_name}"
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
        """
        Pindahkan akses Editor folder master dari SA lama ke SA baru (reassign, issue #77).

        SA baru diberi `writer` (dilewati bila sudah punya), lalu akses SA lama dicabut. Izin
        Editor pada folder master diwarisi subfolder, jadi cukup menyentuh folder master.
        Urutannya sengaja beri-dulu-baru-cabut agar proyek tidak pernah tanpa SA bila gagal di
        tengah. Tidak melakukan apa pun bila SA lama dan baru adalah orang yang sama.

        Args:
            master_folder_id: ID folder master proyek (`gdrive_folder_id`)
            old_sa_email: Email SA lama, atau None bila tidak ada
            new_sa_email: Email SA baru

        Raises:
            FolderProvisioningError: Jika gagal setelah 3x retry
        """
        if old_sa_email and old_sa_email.lower() == new_sa_email.lower():
            return

        logger.info(
            f"Memindahkan akses SA pada folder {master_folder_id}: "
            f"{old_sa_email or '-'} -> {new_sa_email}"
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

        if old_sa_email:
            permission_id = await self._execute_with_retry(
                "find_old_sa_permission",
                self._find_permission_sync,
                master_folder_id,
                old_sa_email,
            )
            if permission_id:
                await self._execute_with_retry(
                    "remove_old_sa_permission",
                    self._remove_permission_sync,
                    master_folder_id,
                    permission_id,
                )

    async def lock_solutions_folder(self, solutions_folder_id: str, sales_email: str) -> None:
        """
        Hapus akses Sales dari folder Solutions (SLA auto-lock H+5).

        Dipanggil oleh SLA_Timer saat DQ Number belum diinput
        setelah 5 hari dari assignment.

        Args:
            solutions_folder_id: ID folder Solutions di Google Drive
            sales_email: Email Sales yang aksesnya akan dihapus

        Raises:
            FolderProvisioningError: Jika gagal setelah 3x retry
        """
        logger.info(f"Locking folder Solutions ({solutions_folder_id}) untuk {sales_email}")

        # Cari permission ID Sales di folder Solutions
        permission_id = await self._execute_with_retry(
            "find_sales_permission",
            self._find_permission_sync,
            solutions_folder_id,
            sales_email,
        )

        if permission_id:
            await self._execute_with_retry(
                "remove_sales_permission",
                self._remove_permission_sync,
                solutions_folder_id,
                permission_id,
            )
            logger.info(f"Akses Sales dihapus dari folder Solutions")
        else:
            logger.info(f"Sales ({sales_email}) tidak punya akses ke folder Solutions, skip lock.")

    async def unlock_solutions_folder(self, solutions_folder_id: str, sales_email: str) -> None:
        """
        Kembalikan akses Viewer untuk Sales ke folder Solutions.

        Dipanggil saat DQ Number berhasil diinput setelah sebelumnya
        folder di-lock oleh SLA_Timer.

        Args:
            solutions_folder_id: ID folder Solutions di Google Drive
            sales_email: Email Sales yang aksesnya akan dikembalikan

        Raises:
            FolderProvisioningError: Jika gagal setelah 3x retry
        """
        logger.info(f"Unlocking folder Solutions ({solutions_folder_id}) untuk {sales_email}")

        await self._execute_with_retry(
            "restore_sales_permission",
            self._set_permission_sync,
            solutions_folder_id,
            sales_email,
            "reader",
        )

        logger.info(f"Akses Viewer Sales dikembalikan ke folder Solutions")

    async def provision_handover(
        self,
        solutions_folder_id: str,
        pmo_email: str,
        delivery_email: str,
    ) -> str:
        """
        Buat subfolder Final_Deliverables di Solutions dan set permission PMO/Delivery.

        Dipanggil saat proyek Closed-Win dan HLD berstatus "Final".

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
