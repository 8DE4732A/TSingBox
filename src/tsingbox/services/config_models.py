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


class RouteConfig(BaseModel):
    final: str
    rules: list[RouteRule] = Field(default_factory=list)


class DNSServer(BaseModel):
    type: str
    tag: str | None = None
    server: str | None = None
    server_port: int | None = None


class DNSConfig(BaseModel):
    servers: list[DNSServer] = Field(default_factory=list)


class SingBoxConfig(BaseModel):
    log: dict[str, Any] = Field(default_factory=lambda: {"level": "info"})
    dns: DNSConfig = Field(default_factory=DNSConfig)
    outbounds: list[dict[str, Any]]
    endpoints: list[WireGuardEndpoint] = Field(default_factory=list)
    route: RouteConfig
