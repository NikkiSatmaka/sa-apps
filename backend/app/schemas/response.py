"""
Standard response format untuk semua API endpoint.
Semua response mengikuti format: {"status": "success|error", "data": {...}, "message": "..."}
"""

from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ValidationErrorDetail(BaseModel):
    """Detail error per-field untuk response 422."""
    field: str
    reason: str


class StandardResponse(BaseModel, Generic[T]):
    """
    Format response standar untuk semua endpoint.
    Memastikan konsistensi format response di seluruh API.
    """
    status: str  # "success" atau "error"
    data: Optional[T] = None
    message: str



class SuccessResponse(BaseModel, Generic[T]):
    """Typed success envelope used by migrated endpoints."""

    status: Literal["success"] = "success"
    data: Optional[T] = None
    message: str = "Success"


class ErrorResponse(BaseModel, Generic[T]):
    """Typed error envelope; `data` carries structured error details when present."""

    status: Literal["error"] = "error"
    data: Optional[T] = None
    message: str

def success_response(data: Any = None, message: str = "Success") -> dict:
    """
    Helper untuk membuat response sukses.
    Digunakan di endpoint handler untuk mengembalikan response terstandar.
    """
    return {
        "status": "success",
        "data": data,
        "message": message,
    }


def error_response(message: str, data: Any = None) -> dict:
    """
    Helper untuk membuat response error.
    Digunakan di exception handler atau endpoint yang perlu return error.
    """
    return {
        "status": "error",
        "data": data,
        "message": message,
    }
