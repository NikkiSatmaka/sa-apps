import type { FileItem } from "@/components/FileUpload";

export interface ProjectFormData {
  projectName: string;
  customerName: string;
  targetSubmit: string;
  estimatedValue: string;
  dqNumber: string;
  productPic: string;
  salesPic: string;
}

export interface ProjectFormErrors {
  projectName?: string;
  customerName?: string;
  targetSubmit?: string;
  estimatedValue?: string;
  dqNumber?: string;
  productPic?: string;
  files?: string;
}

export function formatIDR(value: string): string {
  const cleaned = value.replace(/[^\d]/g, "");
  return cleaned ? cleaned.replace(/\B(?=(\d{3})+(?!\d))/g, ".") : "";
}

export function parseIDR(value: string): number {
  return parseInt(value.replace(/\./g, "")) || 0;
}

export function getTodayString(): string {
  return new Date().toISOString().split("T")[0];
}

export function validateProjectForm(
  form: ProjectFormData,
  validFiles: FileItem[],
  perluPilihProduct: boolean,
): ProjectFormErrors {
  const errors: ProjectFormErrors = {};
  if (!form.projectName.trim()) errors.projectName = "Nama proyek wajib diisi";
  else if (form.projectName.trim().length > 150) errors.projectName = "Nama proyek maksimal 150 karakter";

  if (!form.customerName.trim()) errors.customerName = "Nama customer wajib diisi";
  else if (form.customerName.trim().length > 150) errors.customerName = "Nama customer maksimal 150 karakter";

  if (!form.targetSubmit) errors.targetSubmit = "Target submit wajib diisi";
  else {
    const selectedDate = new Date(form.targetSubmit);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (selectedDate < today) errors.targetSubmit = "Target submit tidak boleh tanggal di masa lalu";
  }

  const numericValue = parseIDR(form.estimatedValue);
  if (!form.estimatedValue.trim()) errors.estimatedValue = "Estimasi nilai proyek wajib diisi";
  else if (numericValue < 1) errors.estimatedValue = "Estimasi nilai minimal Rp 1";
  else if (numericValue > 999999999999) errors.estimatedValue = "Estimasi nilai maksimal Rp 999.999.999.999";

  if (form.dqNumber.trim() && !/^[A-Za-z0-9\-]{5,20}$/.test(form.dqNumber.trim())) {
    errors.dqNumber = "Format DQ Number tidak valid (alfanumerik + hyphen, 5-20 karakter)";
  }
  if (perluPilihProduct && !form.productPic) errors.productPic = "Product Manager PIC wajib dipilih";
  if (validFiles.some((file) => !file.docType)) errors.files = "Pilih tipe (MoM atau RFP) untuk setiap file";
  return errors;
}

export function buildProjectFormData(
  form: ProjectFormData,
  qualificationAnswers: unknown,
  validFiles: FileItem[],
  perluPilihProduct: boolean,
  bolehPilihSales: boolean,
): FormData {
  const data = new window.FormData();
  data.append("project_name", form.projectName.trim());
  data.append("customer_name", form.customerName.trim());
  data.append("target_submit", form.targetSubmit);
  data.append("estimasi_nilai", parseIDR(form.estimatedValue).toString());
  if (perluPilihProduct && form.productPic) data.append("product_pic", form.productPic);
  if (bolehPilihSales && form.salesPic) data.append("sales_pic", form.salesPic);
  if (form.dqNumber.trim()) data.append("dq_number", form.dqNumber.trim());
  data.append("qualification_answers", JSON.stringify(qualificationAnswers));
  validFiles.forEach((item) => {
    data.append("files", item.file);
    data.append("file_types", item.docType ?? "");
  });
  return data;
}
