"""
Rate limiter sederhana menggunakan in-memory storage.
Membatasi request per menit per pengguna terautentikasi (id dari token), anonim per IP klien.
Untuk production, bisa diganti dengan Redis-based rate limiter.
"""

import ipaddress
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


def _user_id_dari_token(authorization: str | None) -> str | None:
    """Id pengguna dari access token Bearer yang valid; selain itu None (tanpa error)."""
    if not authorization:
        return None
    skema, _, token = authorization.partition(" ")
    token = token.strip()
    if skema.lower() != "bearer" or not token:
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


def _ip_klien(request: Request) -> str:
    """
    IP klien. Default: alamat peer socket.

    Dengan `TRUSTED_PROXY_HOPS` = N > 0, pakai entri ke-N dari KANAN `X-Forwarded-For`
    (entri yang ditambahkan infrastruktur tepercaya). Entri lebih kiri dapat dipalsukan klien
    sehingga diabaikan; entri pertama TIDAK PERNAH dipercaya. Rantai lebih pendek dari N,
    kosong, atau entri target bukan IP valid -> peer socket.
    """
    peer = request.client.host if request.client else "unknown"
    hops = settings.TRUSTED_PROXY_HOPS
    if hops <= 0:
        return peer
    rantai = [e.strip() for e in request.headers.get("X-Forwarded-For", "").split(",")]
    if len(rantai) < hops:
        return peer
    kandidat = rantai[-hops]
    try:
        return str(ipaddress.ip_address(kandidat))
    except ValueError:
        return peer


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Middleware rate limiter yang membatasi jumlah request per user per menit.
    Menggunakan sliding window algorithm sederhana dengan in-memory storage.
    """

    def __init__(self, app, max_requests: int = None):
        super().__init__(app)
        self.max_requests = max_requests or settings.RATE_LIMIT_PER_MINUTE
        self.window_seconds = 60  # 1 menit
        # Menyimpan timestamp request per user: {user_id: [timestamps]}
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def _get_user_identifier(self, request: Request) -> str:
        """
        Dapatkan identifier kuota dari request.
        Prioritas: user dari access token valid > IP klien.

        Token diselesaikan di sini (bukan lewat `request.state`, yang baru terisi di
        `get_current_user` SETELAH middleware). Token tidak ada/tidak valid -> kuota per IP.
        """
        user_id = _user_id_dari_token(request.headers.get("Authorization"))
        if user_id:
            return f"user:{user_id}"
        return f"ip:{_ip_klien(request)}"

    def _cleanup_old_requests(self, user_id: str, now: float):
        """Hapus timestamp request yang sudah di luar window."""
        cutoff = now - self.window_seconds
        self._requests[user_id] = [ts for ts in self._requests[user_id] if ts > cutoff]

    def _calculate_retry_after(self, user_id: str, now: float) -> int:
        """Hitung jumlah detik sebelum user bisa request lagi."""
        if not self._requests[user_id]:
            return 0
        oldest_in_window = self._requests[user_id][0]
        retry_after = int(oldest_in_window + self.window_seconds - now) + 1
        return max(retry_after, 1)

    async def dispatch(self, request: Request, call_next):
        """Proses setiap request dan terapkan rate limiting."""
        # Skip rate limiting untuk health check dan docs
        skip_paths = ["/health", "/docs", "/redoc", "/openapi.json"]
        if request.url.path in skip_paths:
            return await call_next(request)

        now = time.time()
        user_id = self._get_user_identifier(request)

        # Bersihkan request lama
        self._cleanup_old_requests(user_id, now)

        # Cek apakah melebihi limit
        if len(self._requests[user_id]) >= self.max_requests:
            retry_after = self._calculate_retry_after(user_id, now)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "status": "error",
                    "data": None,
                    "message": f"Rate limit exceeded. Maksimal {self.max_requests} request per menit.",
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Catat request ini
        self._requests[user_id].append(now)

        # Lanjutkan ke handler berikutnya
        response = await call_next(request)
        return response
