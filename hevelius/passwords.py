"""Shared password hashing (Argon2id)."""
from argon2 import PasswordHasher, Type  # type: ignore[import-not-found]

# Login passwords are plaintext over HTTPS; stored as argon2id in pass_d.
password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # KiB
    parallelism=1,
    type=Type.ID,
)
