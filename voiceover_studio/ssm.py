"""Secrets are read at runtime from SSM Parameter Store. Settings only ever hold the parameter NAME."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=16)
def ssm_secret(parameter_name: str, region: str) -> str:
    import boto3

    client = boto3.client("ssm", region_name=region)
    return client.get_parameter(Name=parameter_name, WithDecryption=True)["Parameter"]["Value"]
