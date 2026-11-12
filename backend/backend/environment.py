"""Parse environment configuration without exposing secret values in errors."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def required_environment(name, environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"Set {name} in the environment or backend/.env.")
    return value


def boolean_environment(name, default=False, environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean (true or false).")


def integer_environment(name, default, *, minimum=1, maximum=None, environ=None):
    environ = os.environ if environ is None else environ
    try:
        value = int(environ.get(name, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer.") from None
    if value < minimum or (maximum is not None and value > maximum):
        bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        raise ImproperlyConfigured(f"{name} must be {bounds}.")
    return value


def list_environment(name, default=(), environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    if value is None:
        return list(default)
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def origins_environment(name, default=(), environ=None):
    origins = list_environment(name, default, environ)
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and "*" not in parsed.netloc
                and parsed.username is None
                and parsed.password is None
                and not (parsed.path or parsed.query or parsed.fragment)
                and (parsed.port is None or 1 <= parsed.port <= 65535)
                and not any(character.isspace() or character == ";" for character in origin)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ImproperlyConfigured(f"{name} must contain HTTP(S) origins with no path or credentials.")
    return origins


def path_environment(name, base_dir, default, environ=None):
    environ = os.environ if environ is None else environ
    path = Path(environ.get(name, "").strip() or default).expanduser()
    if not path.is_absolute():
        path = Path(base_dir) / path
    return path.resolve()


def database_from_environment(environ=None, *, base_dir=None):
    environ = os.environ if environ is None else environ
    sslmode = environ.get("DB_SSLMODE", "verify-full")
    if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ImproperlyConfigured("DB_SSLMODE must be a PostgreSQL SSL mode.")
    rootcert = environ.get("DB_SSLROOTCERT", "")
    if sslmode in {"verify-ca", "verify-full"} and not rootcert.strip():
        raise ImproperlyConfigured("Set DB_SSLROOTCERT when using certificate verification.")

    port = integer_environment("DB_PORT", 5432, maximum=65535, environ=environ)

    options = {"sslmode": sslmode}
    if rootcert:
        if base_dir is not None:
            rootcert = str(path_environment("DB_SSLROOTCERT", base_dir, rootcert, environ))
        options["sslrootcert"] = rootcert

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required_environment("DB_NAME", environ),
        "USER": required_environment("DB_USER", environ),
        "PASSWORD": required_environment("DB_PASSWORD", environ),
        "HOST": required_environment("DB_HOST", environ),
        "PORT": str(port),
        "OPTIONS": options,
        "CONN_MAX_AGE": 0,
    }
