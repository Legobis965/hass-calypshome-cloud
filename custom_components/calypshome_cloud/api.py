import asyncio
import logging
import requests
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from .const import DEFAULT_CLOUD_URL

LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

# Codes HTTP pouvant indiquer un token expiré ou invalide
TOKEN_ERROR_STATUSES = (400, 401, 403)

# Action cloud rappelant la position favorite mémorisée dans le moteur du volet
FAVORITE_ACTION = "FAV_CALL_1"


class CalypsHomeError(Exception):
    """Erreur générique de l'API Calyps'HOME"""


class CalypsHomeConnectionError(CalypsHomeError):
    """Le cloud Calyps'HOME est injoignable ou a renvoyé une réponse inattendue"""


class CalypsHomeAuthError(CalypsHomeError):
    """Les identifiants Calyps'HOME ont été refusés"""


class CalypsHomeObject:
    """Représentation d'un objet Calyps'HOME"""

    def __init__(
        self,
        id: int,
        name: str,
        class_name: str,
        real_name: str,
        statuses: list,
        actions: list[str] | None = None,
        hidden: bool = False,
    ):
        """
        Args:
            id (int): Identifiant unique de l'objet
            name (str): Nom convivial de l'objet
            class_name (str): Nom de la classe de l'objet
            real_name (str): Nom réel de l'objet utilisé par le cloud
            statuses (list): Liste des statuts de l'objet
            actions (list[str] | None): Noms des actions supportées par l'objet (OPEN, FAV_CALL_1, ...)
            hidden (bool): Objet masqué dans l'application Calyps'HOME
        """
        self.id = id
        self.name = name
        self.class_name = class_name
        self.real_name = real_name
        self.statuses = statuses
        self.actions = actions or []
        self.hidden = hidden

    @property
    def supports_favorite(self) -> bool:
        """Indique si l'objet supporte le rappel de position favorite"""
        return FAVORITE_ACTION in self.actions


class CalypsHomeAPI:
    """Client API pour Calyps'HOME cloud"""

    @property
    def token(self):
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value
        if value:
            self.session.headers["Authorization"] = f"Bearer {value}"
        else:
            self.session.headers.pop("Authorization", None)


    def __init__(self, email: str, password: str):
        """
        Args:
            email: Email de connexion
            password: Mot de passe
        """
        self.base_url = DEFAULT_CLOUD_URL
        self.email = email
        self.password = password
        self._token = None
        self._request_lock = threading.RLock()
        self.on_update: Callable[[dict | None], Awaitable[None]] | None = None
        self._ws_client = None

        # Session standard, sans pool persistant forcé
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"


    def _extract_object_from_response(self, response: dict) -> CalypsHomeObject | None:
        """Extrait les informations d'un objet depuis la réponse de l'API

        Args:
            response: Dictionnaire JSON de la réponse de l'API

        Returns:
            L'objet extrait ou `None` en cas d'erreur
        """
        try:
            objectData = response["resource"]
            actions = [
                action["name"] if isinstance(action, dict) else action
                for action in objectData.get("actions") or []
                if (isinstance(action, dict) and action.get("name")) or isinstance(action, str)
            ]
            return CalypsHomeObject(
                id=objectData["id"],
                name=objectData.get("name") or objectData.get("realName", "Inconnu"),
                class_name=objectData["className"],
                real_name=objectData["realName"],
                statuses=objectData.get("statuses") or [],
                actions=actions,
                hidden=bool((objectData.get("flags") or {}).get("hidden")),
            )
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            LOGGER.error("Erreur lors de l'extraction de l'objet depuis la réponse: %s", e)
            return None


    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Envoie une requête HTTP brute sur la session

        Raises:
            CalypsHomeConnectionError: En cas d'erreur réseau
        """
        try:
            # Verrouillage pour éviter les conflits de session entre threads
            with self._request_lock:
                return self.session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.exceptions.RequestException as e:
            raise CalypsHomeConnectionError(f"Erreur réseau lors de la requête HTTP : {e}") from e


    def _send_calypshome_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Envoie une requête Calyps'HOME avec reprise d'authentification automatique

        Args:
            method: Méthode HTTP
            url: URL relative de la requête
            kwargs: Arguments supplémentaires pour `requests.request()`

        Returns:
            La réponse de la requête (quel que soit son code HTTP)

        Raises:
            CalypsHomeAuthError: Si les identifiants sont refusés
            CalypsHomeConnectionError: En cas d'erreur réseau
        """
        url = f"{self.base_url}{url}"

        # S'authentifie si aucun token n'est présent
        self.login()
        token_used = self.token

        response = self._request(method, url, **kwargs)

        # Si le token est peut-être expiré ou invalide, réessaye une fois après réauthentification
        if response.status_code in TOKEN_ERROR_STATUSES:
            LOGGER.warning("Token expiré ou invalide (HTTP %s), réauthentification...", response.status_code)
            renewed = self._relogin(token_used)
            response = self._request(method, url, **kwargs)

            # Le websocket peut rester connecté avec l'ancien token: on force un redémarrage,
            # mais seulement si le nouveau token a réellement résolu l'erreur.
            if renewed and response.status_code not in TOKEN_ERROR_STATUSES:
                self._restart_websocket_after_relogin()

        return response


    def _send_action(self, device_id: str, action: str, args: dict = None) -> bool:
        """Envoie une action à un appareil

        Args:
            device_id: ID de l'objet
            action: Nom de l'action à effectuer
            args: Dictionnaire optionnel avec les arguments

        Returns:
            `True` si succès, sinon `False`
        """
        cloud_action = {"name": action}

        # Ajoute les arguments si fournis
        if args:
            cloud_action["mArgs"] = [
                {"name": key, "value": str(value)}
                for key, value in args.items()
            ]

        payload = {"actions": [cloud_action]}

        try:
            # Envoie la requête pour lancer l'action
            response = self._send_calypshome_request("PUT", f"/services/durin/my/objects/{device_id}", json=payload)
        except CalypsHomeError as e:
            LOGGER.error("Erreur lors de l'envoi de l'action %s: %s", action, e)
            return False

        if 200 <= response.status_code < 300:
            LOGGER.debug("Action %s envoyée à %s", action, device_id)
            return True

        LOGGER.error("Erreur lors de l'envoi de l'action %s: HTTP %s", action, response.status_code)
        return False


    def _authenticate(self) -> None:
        """Demande un nouveau token au cloud (le verrou doit être détenu)

        Raises:
            CalypsHomeAuthError: Si les identifiants sont refusés
            CalypsHomeConnectionError: En cas d'erreur réseau ou de réponse inattendue
        """
        try:
            response = self.session.post(
                url=f"{self.base_url}/services/dain/login",
                json={"login": self.email, "password": self.password},
                timeout=REQUEST_TIMEOUT
            )
        except requests.exceptions.RequestException as e:
            raise CalypsHomeConnectionError(f"Erreur lors de l'authentification auprès de l'API cloud: {e}") from e

        if 400 <= response.status_code < 500:
            raise CalypsHomeAuthError(f"Identifiants refusés par le cloud (HTTP {response.status_code})")
        if not 200 <= response.status_code < 300:
            raise CalypsHomeConnectionError(f"Erreur du cloud lors de l'authentification (HTTP {response.status_code})")

        try:
            token = response.json().get("token")
        except (ValueError, AttributeError) as e:
            raise CalypsHomeConnectionError(f"Réponse d'authentification invalide: {e}") from e

        if not token:
            raise CalypsHomeConnectionError("Connexion cloud réussie mais aucun token retourné")

        self.token = token
        LOGGER.debug("Authentification cloud réussie pour %s", self.email)


    def login(self) -> bool:
        """S'authentifie auprès de l'API cloud si aucun token n'est présent

        Returns:
            `True` si l'authentification est réussie

        Raises:
            CalypsHomeAuthError: Si les identifiants sont refusés
            CalypsHomeConnectionError: En cas d'erreur réseau ou de réponse inattendue
        """
        # On verrouille pour qu'un seul thread à la fois puisse tenter de se connecter
        with self._request_lock:
            if not self.token:
                self._authenticate()
            return True


    def _relogin(self, token_used: str | None) -> bool:
        """Renouvelle le token s'il n'a pas déjà été renouvelé par un autre thread

        Args:
            token_used: Token utilisé par la requête qui a échoué

        Returns:
            `True` si un nouveau token a été obtenu par cet appel, `False` si un autre thread l'avait déjà renouvelé
        """
        with self._request_lock:
            if self.token and self.token != token_used:
                return False

            self.token = None
            self._authenticate()
            return True


    def _restart_websocket_after_relogin(self) -> None:
        """Redémarre le websocket après une réauthentification API réussie."""
        if self._ws_client is None:
            return

        try:
            self._ws_client.restart_websocket_threadsafe()
            LOGGER.debug("Redémarrage websocket demandé après relogin API")
        except Exception as e:
            LOGGER.warning("Impossible de redémarrer le websocket après relogin: %s", e)


    def get_objects(self) -> list[CalypsHomeObject]:
        """Récupère la liste de tous les objets

        Returns:
            Liste des objets

        Raises:
            CalypsHomeAuthError: Si les identifiants sont refusés
            CalypsHomeConnectionError: En cas d'erreur réseau ou de réponse inattendue
        """
        response = self._send_calypshome_request("GET", "/services/durin/my/objects?all")

        if not 200 <= response.status_code < 300:
            raise CalypsHomeConnectionError(f"Erreur lors de la récupération des objets: HTTP {response.status_code}")

        try:
            data = response.json()["content"]
        except (ValueError, KeyError, TypeError) as e:
            raise CalypsHomeConnectionError(f"Réponse inattendue lors de la récupération des objets: {e}") from e

        if not isinstance(data, list):
            raise CalypsHomeConnectionError("Réponse inattendue lors de la récupération des objets: 'content' n'est pas une liste")

        objects = [self._extract_object_from_response(obj) for obj in data]

        # Les objets masqués dans l'application Calyps'HOME ne sont pas exposés à Home Assistant
        return [obj for obj in objects if obj is not None and not obj.hidden]


    def open_shutter(self, device_id: str) -> bool:
        """Ouvre un volet"""
        return self._send_action(device_id, "OPEN")

    def close_shutter(self, device_id: str) -> bool:
        """Ferme un volet"""
        return self._send_action(device_id, "CLOSE")

    def stop_shutter(self, device_id: str) -> bool:
        """Arrête un volet"""
        return self._send_action(device_id, "STOP")

    def set_level(self, device_id: str, level: int) -> bool:
        """Définit le niveau d'ouverture du volet"""
        return self._send_action(device_id, "LEVEL", {"level": level})

    def call_favorite(self, device_id: str) -> bool:
        """Envoie le volet à sa position favorite mémorisée dans le moteur"""
        return self._send_action(device_id, FAVORITE_ACTION)


    def close(self) -> None:
        """Ferme la session HTTP (appel bloquant, à exécuter hors de la boucle d'événements)"""
        self.session.close()


    async def start_websocket(
        self,
        task_factory: Callable[[Coroutine[Any, Any, None]], asyncio.Task] | None = None,
    ) -> None:
        """Démarre l'écoute websocket pour les mises à jour en temps réel

        Args:
            task_factory: Fonction créant la tâche d'écoute (par ex. `entry.async_create_background_task`)
        """
        if self._ws_client is None:
            # Import local pour éviter les imports circulaires au chargement du module
            from .websocket import CalypsHomeWebSocket
            self._ws_client = CalypsHomeWebSocket(self, self.on_update, task_factory)
        else:
            self._ws_client.on_update = self.on_update

        await self._ws_client.start_websocket()


    async def async_stop_websocket(self) -> None:
        """Arrête l'écoute websocket si elle est en cours et attend la fin de la tâche"""
        if self._ws_client is not None:
            await self._ws_client.async_stop_websocket()
