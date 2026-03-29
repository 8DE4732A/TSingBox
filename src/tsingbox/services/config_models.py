from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Outbound(BaseModel):
    type: str
    tag: str
    detour: str | None = None


class WireGuardPeer(BaseModel):
    address: str
    port: int
    public_key: str
    allowed_ips: list[str] = Field(default_factory=list)
    reserved: list[int] = Field(default_factory=list)


class WireGuardEndpoint(BaseModel):
    type: str = "wireguard"
    tag: str
    address: list[str] = Field(default_factory=list)
    private_key: str
    peers: list[WireGuardPeer] = Field(default_factory=list)
    detour: str | None = None


class RouteRule(BaseModel):
    outbound: str


class RuleSetConfigEntry(BaseModel):
    type: str = "remote"
    tag: str
    format: str = "binary"
    url: str
    download_detour: str


class RouteConfig(BaseModel):
    final: str
    rules: list[dict[str, Any] | RouteRule] = Field(default_factory=list)
    rule_set: list[RuleSetConfigEntry] = Field(default_factory=list)
    default_domain_resolver: dict[str, Any] | None = None


class DNSServer(BaseModel):
    type: str
    tag: str | None = None
    server: str | None = None
    server_port: int | None = None
    detour: str | None = None
    domain_resolver: str | None = None
    path: str | None = None
    predefined: dict[str, list[str]] | None = None


class DNSConfig(BaseModel):
    servers: list[DNSServer] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    final: str | None = None


class CacheFileConfig(BaseModel):
    enabled: bool = True


class ExperimentalConfig(BaseModel):
    cache_file: CacheFileConfig = Field(default_factory=CacheFileConfig)


class SingBoxConfig(BaseModel):
    log: dict[str, Any] = Field(default_factory=lambda: {"level": "info"})
    dns: DNSConfig = Field(default_factory=DNSConfig)
    inbounds: list[dict[str, Any]] = Field(default_factory=list)
    outbounds: list[dict[str, Any]]
    endpoints: list[WireGuardEndpoint] = Field(default_factory=list)
    route: RouteConfig
    experimental: ExperimentalConfig = Field(default_factory=ExperimentalConfig)
