"""Shared password hashing (Argon2id)."""
from argon2 import PasswordHasher, Type  # type: ignore[import-not-found]

# Login passwords are plaintext over HTTPS. Legacy DB values may still be MD5 hex;
# those are verified once and immediately replaced with argon2id.
password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # KiB
    parallelism=1,
    type=Type.ID,
)
