from __future__ import annotations

import logging
import os

import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runta_agent_eval.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeHandle:
    id: str
    name: str
    runtime: Any


class RuntaGateway:
    """Thin async adapter whose Runta-specific calls mirror the supplied official docs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Any | None = None
        self._runta_module: Any | None = None
        self._openai_secret_id: str | None = None

    async def __aenter__(self) -> "RuntaGateway":
        try:
            import runta as runta_module
            self._runta_module = runta_module
            self.client = runta_module.AsyncRunta(token=self.settings.runta_token or None)
            return self
        except Exception:
            logger.exception("Failed opening Runta client. Is runta-sdk installed in this Linux environment?")
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self.client is not None:
                await self.client.close()
        except Exception:
            logger.exception("Failed closing Runta client")

    async def health(self) -> bool:
        try:
            if self.client is None:
                raise RuntimeError("Runta client is not open")
            return await self.client.health()
        except Exception:
            logger.exception("Runta health check failed")
            raise

    async def list_runtimes(self) -> list[Any]:
        try:
            if self.client is None:
                raise RuntimeError("Runta client is not open")
            return await self.client.runtimes.list()
        except Exception:
            logger.exception("Listing Runta runtimes failed")
            raise


    async def list_checkpoints(self) -> list[Any]:
        try:
            if self.client is None:
                raise RuntimeError("Runta client is not open")
            return await self.client.checkpoints.list()
        except Exception:
            logger.exception("Listing Runta checkpoints failed")
            raise

    async def delete_checkpoint(self, checkpoint_id: str) -> None:
        try:
            if self.client is None:
                raise RuntimeError("Runta client is not open")
            await self.client.checkpoints.delete(checkpoint_id)
        except Exception:
            logger.exception("Deleting Runta checkpoint %s failed", checkpoint_id)
            raise

    async def ensure_openai_secret(self) -> str:
        """Store/update the tenant OpenAI secret and cache its immutable Runta UUID."""
        try:
            if self.client is None:
                raise RuntimeError("Runta client is not open")
            if not self.settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is missing")
            secret = await self.client.secrets.set(
                self.settings.runta_secret_name,
                self.settings.openai_api_key,
                cache_ttl_secs=0,
            )
            secret_id = str(secret.id)
            self._openai_secret_id = secret_id
            logger.info(
                "Stored/updated Runta tenant secret metadata: %s (id=%s)",
                self.settings.runta_secret_name,
                secret_id,
            )
            return secret_id
        except Exception:
            logger.exception("Failed storing OpenAI secret in Runta")
            raise

    def _openai_secret_configuration(self) -> list[dict[str, Any]]:
        secret_id = self._openai_secret_id
        if not secret_id:
            raise RuntimeError(
                "OpenAI tenant secret has not been initialized; call ensure_openai_secret() first"
            )
        return [
            {
                "secret_id": secret_id,
                "environment": [],
                "egress_rules": [
                    {
                        "host_pattern": "api.openai.com",
                        "path_pattern": "/v1/*",
                        "action": "header",
                        "name": "Authorization",
                        "value_template": "Bearer ${secret}",
                    }
                ],
                "files": [],
            }
        ]

    async def _create_runtime_v2_with_openai_secret(
        self,
        name: str,
        *,
        checkpoint_id: str | None,
        allowed_hosts: list[str],
        ingress_port: int | None,
        idle_suspend_after_secs: int | None,
        memory_mib: int | None,
        memory_max_mib: int | None,
    ) -> RuntimeHandle:
        """Create the runtime atomically with Runta secret_configuration.

        runta-sdk 0.2.5's public RuntimeManager does not expose
        secret_configuration even though the v2 REST create contract does.
        Creating atomically avoids the revision-sensitive PATCH path entirely.
        """
        if self.client is None:
            raise RuntimeError("Runta client is not open")
        if not self.settings.runta_token:
            raise RuntimeError("RUNTA_TOKEN is missing")

        egress_policy: dict[str, Any]
        if allowed_hosts:
            egress_policy = {"mode": "allowlist", "allowed_hosts": allowed_hosts}
        else:
            egress_policy = {"mode": "denylist", "denied_hosts": []}

        body: dict[str, Any] = {
            "name": name,
            "egress_policy": egress_policy,
            "secret_configuration": self._openai_secret_configuration(),
        }
        if ingress_port:
            body["ingress_specs"] = [
                {"protocol": "https", "runtime_port": int(ingress_port)}
            ]
        if idle_suspend_after_secs:
            body["idle_policy"] = {
                "mode": "suspend_and_wakeup",
                "suspend_after_secs": int(idle_suspend_after_secs),
            }
        else:
            body["idle_policy"] = {"mode": "disabled"}

        if checkpoint_id:
            body["checkpoint_id"] = checkpoint_id
        else:
            initial_memory = memory_mib or self.settings.runta_memory_mib
            maximum_memory = memory_max_mib or self.settings.runta_memory_max_mib
            body["resources"] = {
                "requests": {
                    "vcpus": self.settings.runta_vcpus,
                    "memory_mib": initial_memory,
                },
                "limits": {"memory_mib": maximum_memory},
            }

        endpoint = os.getenv("RUNTA_ENDPOINT", "https://api.runta.com").rstrip("/")
        url = f"{endpoint}/v2/runtimes"
        headers = {
            "Authorization": f"Bearer {self.settings.runta_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as http:
            response = await http.post(url, headers=headers, json=body)
        if response.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"Runta v2 runtime create with secret_configuration failed: "
                f"HTTP {response.status_code}: {response.text[:4000]}"
            )
        try:
            payload = response.json()
            runtime_id = str(payload["data"]["id"])
        except Exception as exc:
            raise RuntimeError(
                f"Runta v2 runtime create returned an unexpected response: {response.text[:4000]}"
            ) from exc

        runtime = await self.client.runtimes.get(runtime_id)
        await runtime.wait_until_ready(timeout=240.0, poll_interval=0.5)
        logger.info(
            "Created %s with OpenAI secret_configuration atomically via Runta v2",
            name,
        )
        return RuntimeHandle(id=runtime_id, name=name, runtime=runtime)

    async def create_runtime(
        self,
        name: str,
        *,
        checkpoint_id: str | None = None,
        allowed_hosts: list[str] | None = None,
        ingress_port: int | None = None,
        idle_suspend_after_secs: int | None = None,
        memory_mib: int | None = None,
        memory_max_mib: int | None = None,
        with_openai_secret: bool = False,
    ) -> RuntimeHandle:
        try:
            if self.client is None or self._runta_module is None:
                raise RuntimeError("Runta client is not open")
            hosts = list(dict.fromkeys(allowed_hosts or []))

            if with_openai_secret:
                return await self._create_runtime_v2_with_openai_secret(
                    name,
                    checkpoint_id=checkpoint_id,
                    allowed_hosts=hosts,
                    ingress_port=ingress_port,
                    idle_suspend_after_secs=idle_suspend_after_secs,
                    memory_mib=memory_mib,
                    memory_max_mib=memory_max_mib,
                )

            egress = None
            if hosts:
                egress = self._runta_module.EgressPolicy(
                    mode=self._runta_module.EgressMode.ALLOWLIST,
                    allowed_hosts=hosts,
                )
            ingress_specs = None
            if ingress_port:
                ingress_specs = [self._runta_module.IngressSpec(protocol="https", runtime_port=ingress_port)]
            runtime = await self.client.runtimes.create(
                name,
                checkpoint_id=checkpoint_id,
                vcpus=self.settings.runta_vcpus,
                memory_mib=memory_mib or self.settings.runta_memory_mib,
                memory_max_mib=memory_max_mib or self.settings.runta_memory_max_mib,
                egress_policy=egress,
                ingress_specs=ingress_specs,
                idle_suspend_after_secs=idle_suspend_after_secs,
                wait=True,
            )
            return RuntimeHandle(id=str(runtime.id), name=name, runtime=runtime)
        except Exception:
            logger.exception("Creating runtime %s failed", name)
            raise

    async def set_egress_allowlist(self, handle: RuntimeHandle, hosts: list[str]) -> None:
        try:
            if self._runta_module is None:
                raise RuntimeError("Runta client is not open")
            policy = self._runta_module.EgressPolicy(
                mode=self._runta_module.EgressMode.ALLOWLIST,
                allowed_hosts=list(dict.fromkeys(hosts)),
            )
            await handle.runtime.egress.set_policy(policy)
        except Exception:
            logger.exception("Failed setting egress allowlist on %s", handle.name)
            raise

    async def attach_openai_secret_stub(self, handle: RuntimeHandle) -> None:
        """Deprecated in this application.

        Secret configuration must be supplied atomically at runtime creation via
        ``create_runtime(..., with_openai_secret=True)``. The v2 PATCH route is
        revision-guarded and is intentionally not used here.
        """
        raise RuntimeError(
            "attach_openai_secret_stub() is no longer used; create the runtime with "
            "with_openai_secret=True instead"
        )

    async def exec(self, handle: RuntimeHandle, command: str, *, timeout: float | None = None, cwd: str | None = None, env: dict[str, str] | None = None) -> Any:
        try:
            return await handle.runtime.exec(command, timeout=timeout, cwd=cwd, env=env)
        except Exception:
            logger.exception("Runtime exec failed on %s: %s", handle.name, command)
            raise

    async def upload(self, handle: RuntimeHandle, src: Path, dst: str) -> None:
        try:
            await handle.runtime.files.upload(str(src), dst)
        except Exception:
            logger.exception("Upload failed to %s:%s", handle.name, dst)
            raise

    async def write(self, handle: RuntimeHandle, dst: str, content: str, *, executable: bool = False) -> None:
        try:
            await handle.runtime.files.write(dst, content, executable=executable)
        except Exception:
            logger.exception("Write failed to %s:%s", handle.name, dst)
            raise

    async def read(self, handle: RuntimeHandle, src: str, *, max_bytes: int | None = None) -> bytes:
        try:
            return await handle.runtime.files.read(src, max_bytes=max_bytes)
        except Exception:
            logger.exception("Read failed from %s:%s", handle.name, src)
            raise

    async def download(self, handle: RuntimeHandle, src: str, dst: Path) -> None:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            await handle.runtime.files.download(src, str(dst))
        except Exception:
            logger.exception("Download failed from %s:%s", handle.name, src)
            raise

    async def checkpoint(self, handle: RuntimeHandle, name: str) -> Any:
        try:
            return await handle.runtime.checkpoints.create(name=name, wait=True)
        except Exception:
            logger.exception("Checkpoint failed for %s", handle.name)
            raise

    async def pause(self, handle: RuntimeHandle) -> None:
        try:
            await handle.runtime.pause()
        except Exception:
            logger.exception("Pause failed for %s", handle.name)
            raise

    async def resume(self, handle: RuntimeHandle) -> None:
        try:
            await handle.runtime.resume(wait=True)
        except Exception:
            logger.exception("Resume failed for %s", handle.name)
            raise

    async def shutdown(self, handle: RuntimeHandle) -> None:
        try:
            await handle.runtime.shutdown()
        except Exception:
            logger.exception("Shutdown failed for %s", handle.name)
            raise

    async def boot(self, handle: RuntimeHandle) -> None:
        try:
            await handle.runtime.boot(wait=True)
        except Exception:
            logger.exception("Boot failed for %s", handle.name)
            raise

    async def resize_memory(self, handle: RuntimeHandle, memory_mib: int) -> Any:
        try:
            return await handle.runtime.resize_memory(memory_mib)
        except Exception:
            logger.exception("Memory resize failed for %s", handle.name)
            raise

    async def refresh(self, handle: RuntimeHandle) -> Any:
        try:
            return await handle.runtime.refresh_info()
        except Exception:
            logger.exception("Refresh failed for %s", handle.name)
            raise

    async def delete(self, handle: RuntimeHandle) -> None:
        try:
            await handle.runtime.delete()
        except Exception:
            logger.exception("Delete failed for %s", handle.name)
            raise
