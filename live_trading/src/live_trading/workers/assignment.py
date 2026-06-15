from __future__ import annotations

import hashlib


class WorkerAssignment:
    def __init__(self, worker_count: int) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be positive")
        self.worker_count = worker_count

    def worker_for(self, event_id: str, mode: str) -> int:
        digest = hashlib.blake2b(
            f"{event_id}:{mode}".encode(), digest_size=8
        ).digest()
        return int.from_bytes(digest, "big") % self.worker_count
