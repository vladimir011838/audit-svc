"""Конфигурация сервиса: YAML-файл с параметрами подключения к БД."""

import os
from dataclasses import dataclass

import yaml

DEFAULT_CONFIG_PATH = "/etc/audit-svc/config.yaml"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    def dsn_params(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.name,
            "user": self.user,
            "password": self.password,
        }


@dataclass(frozen=True)
class Config:
    database: DatabaseConfig


def config_path() -> str:
    return os.getenv("AUDIT_SVC_CONFIG", DEFAULT_CONFIG_PATH)


def load_config(path: str | None = None) -> Config:
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

    db = raw.get("database")
    if not isinstance(db, dict):
        raise ConfigError(f"{path}: section 'database' is required")
    missing = [key for key in ("host", "name", "user", "password") if not db.get(key)]
    if missing:
        raise ConfigError(f"{path}: database.{', database.'.join(missing)} is required")

    try:
        port = int(db.get("port", 5432))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: database.port must be a number") from exc

    return Config(
        database=DatabaseConfig(
            host=str(db["host"]),
            port=port,
            name=str(db["name"]),
            user=str(db["user"]),
            password=str(db["password"]),
        )
    )
