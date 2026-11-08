from __future__ import annotations

import re
import base64
import asyncio
import logging
import websockets
from typing import TYPE_CHECKING, Any
from collections.abc import Awaitable, Callable, Coroutine

from homeassistant.util.ssl import client_context

from .api import CalypsHomeError

if TYPE_CHECKING:
    from .api import CalypsHomeAPI

LOGGER = logging.getLogger(__name__)

# Délai avant reconnexion après une fermeture ou une erreur du websocket
RECONNECT_DELAY = 5

class CalypsHomeWebSocket:

    WS_EVENT_RE = re.compile(r"^event/io/ezsp/(?P<real_name>.+)/(?P<field>[^/]+)$")

    @property
    def on_update(self) -> Callable[[dict | None], Awaitable[None]] | None:
        """Getter pour le callback de mise à jour"""
        return self._on_update

    @on_update.setter
    def on_update(self, value: Callable[[dict | None], Awaitable[None]] | None):
        """Setter pour le callback de mise à jour"""
        self._on_update = value


    def __init__(
        self,
        api: CalypsHomeAPI,
        on_update: Callable[[dict | None], Awaitable[None]] | None = None,
        task_factory: Callable[[Coroutine[Any, Any, None]], asyncio.Task] | None = None,
    ):
        """
        Args:
            api: Instance de `CalypsHomeAPI` pour accéder aux données et au token
            on_update: Callback asynchrone appelé lorsqu'une mise à jour est reçue
            task_factory: Fonction créant la tâche d'écoute (par défaut `asyncio.create_task`)
        """
        self._api = api
        self._on_update = on_update
        self._task_factory = task_factory or asyncio.create_task
        self._ws_task: asyncio.Task | None = None
        self._ws_connected = False
        self._stopped = False
        self._loop: asyncio.AbstractEventLoop | None = None


    def _decode_ws_event_path(self, encoded_path: str) -> str | None:
        """Décode un chemin d'événement websocket encodé en base64

        Args:
            encoded_path: Chemin d'événement encodé en base64

        Returns:
            Chemin d'événement décodé ou `None` en cas d'erreur
        """
        try:
            payload = encoded_path[1:] if encoded_path.startswith("@") else encoded_path
            payload += "=" * (-len(payload) % 4)
            return base64.b64decode(payload).decode("utf-8")
        except Exception as e:
            LOGGER.debug("Impossible de décoder le chemin websocket '%s': %s", encoded_path, e)
            return None


    def _parse_ws_message(self, message: str | bytes) -> dict | None:
        """Parse un message websocket et extrait les mises à jour de niveau

        Args:
            message: Message websocket brut (texte ou binaire)

        Returns:
            Dictionnaire avec les données si succès, sinon `None`
        """
        # Les trames binaires sont décodées en texte pour être traitées de la même façon
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")

        # Extrait le chemin d'événement encodé en b64 et la valeur
        parts = message.split()
        encoded_index = next((i for i, token in enumerate(parts) if token.startswith("@")), -1)
        if encoded_index == -1 or encoded_index + 1 >= len(parts):
            return None

        # Décode le chemin d'événement
        event_path = self._decode_ws_event_path(parts[encoded_index])
        if not event_path:
            return None

        # Extrait le nom réel et le champ à partir du chemin d'événement
        match = self.WS_EVENT_RE.match(event_path)
        if not match:
            return None

        # Extrait la valeur, en la décodant si elle est elle aussi encodée en base64 (préfixe @)
        raw_value = parts[encoded_index + 1]
        value = self._decode_ws_event_path(raw_value) if raw_value.startswith("@") else raw_value
        if value is None:
            return None

        return {
            "real_name": match.group("real_name"),
            "field": match.group("field"),
            "value": value
        }


    async def _ws_listen_loop(self) -> None:
        """Écoute le websocket et déclenche les mises à jour sur les messages"""
        ws_url = self._api.base_url.replace("https://", "wss://") + "/ws"
        loop = asyncio.get_running_loop()

        while not self._stopped:
            try:
                # Authentification HTTP hors de la boucle d'événements (appel bloquant)
                if not self._api.token:
                    try:
                        await loop.run_in_executor(None, self._api.login)
                    except CalypsHomeError as e:
                        LOGGER.warning("Impossible d'authentifier le websocket, nouvel essai dans %ss: %s", RECONNECT_DELAY, e)
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue

                token = self._api.token
                if not token:
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                # Connexion au websocket
                LOGGER.debug("Connexion au websocket: %s", ws_url)

                async with websockets.connect(
                    ws_url,
                    ping_interval=30,
                    subprotocols=["lws-mirror-protocol"],
                    ssl=client_context()
                ) as ws:
                    self._ws_connected = True
                    LOGGER.info("Websocket connecté")

                    # Envoie immédiatement le login websocket avec le token encodé
                    await ws.send(f"p1 1 _web / login @{base64.b64encode(token.encode()).decode()}")
                    LOGGER.debug("Message de connexion websocket envoyé")

                    # Boucle d'écoute des messages websocket
                    async for message in ws:
                        try:
                            ws_update = self._parse_ws_message(message)
                        except Exception as e:
                            LOGGER.debug("Message websocket ignoré (%s): %r", e, message)
                            continue

                        # Notifie uniquement les messages de niveau reconnus
                        if ws_update and self._on_update:
                            try:
                                await self._on_update(ws_update)
                            except Exception as e:
                                LOGGER.error("Erreur dans le callback de mise à jour: %s", e)

                # Fermeture propre par le serveur: on attend avant de se reconnecter
                self._ws_connected = False
                LOGGER.info("Websocket fermé par le serveur, reconnexion dans %ss", RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

            except Exception as e:
                self._ws_connected = False
                LOGGER.warning("Erreur websocket, reconnexion dans %ss: %s", RECONNECT_DELAY, e)
                await asyncio.sleep(RECONNECT_DELAY)

        self._ws_connected = False


    def _create_listen_task(self) -> None:
        """Crée la tâche d'écoute websocket"""
        self._ws_task = self._task_factory(self._ws_listen_loop())


    async def start_websocket(self) -> None:
        """Commence à écouter le websocket pour les mises à jour en temps réel"""
        if self._ws_task and not self._ws_task.done():
            return

        self._stopped = False
        self._loop = asyncio.get_running_loop()

        # Lancer la boucle d'écoute websocket
        self._create_listen_task()


    def restart_websocket_threadsafe(self) -> None:
        """Redémarre le websocket en toute sécurité depuis n'importe quel thread."""
        if not self._loop or self._stopped:
            return

        self._loop.call_soon_threadsafe(self._restart_websocket)


    def _restart_websocket(self) -> None:
        """Annule la tâche websocket courante et relance une nouvelle écoute."""
        # Ne relance rien si l'écoute a été arrêtée entre-temps (déchargement de l'intégration)
        if self._stopped:
            return

        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()

        self._ws_connected = False
        self._create_listen_task()


    async def async_stop_websocket(self) -> None:
        """Arrête l'écoute du websocket et attend la fin de la tâche"""
        self._stopped = True
        task = self._ws_task
        self._ws_task = None

        if task and not task.done():
            task.cancel()
            # asyncio.wait n'avale pas une éventuelle annulation de la tâche appelante
            await asyncio.wait([task])

        self._ws_connected = False
