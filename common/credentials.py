"""Throwaway credentials for test containers.

Passwords are generated per test session and live only in memory and in the container's
environment. Nothing secret is committed, and nothing is reused between runs.
"""

import secrets


def generate_password() -> str:
    """A random password that also meets SQL Server's complexity policy.

    SQL Server wants at least 8 characters from 3 of 4 classes (upper, lower, digit,
    symbol). Hex gives lower case and digits; the fixed prefix adds upper case. No
    symbols, so the password can go into a database URL without escaping.
    """
    return "Tc" + secrets.token_hex(16)
