import copy
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CalypsHomeAPI, CalypsHomeAuthError, CalypsHomeError, CalypsHomeObject
from .const import DOMAIN, CONF_LOGIN, CONF_PASSWORD, PLATFORMS, UPDATE_INTERVAL

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure Calyps'HOME à partir d'une entrée config"""

    login = entry.data[CONF_LOGIN]
    password = entry.data[CONF_PASSWORD]

    api = CalypsHomeAPI(login, password)

    async def _async_update_data() -> list[CalypsHomeObject]:
        # Récupérer les données des objets (l'authentification est faite si nécessaire)
        try:
            return await hass.async_add_executor_job(api.get_objects)
        except CalypsHomeAuthError as err:
            # Déclenche le flux de réauthentification de Home Assistant
            raise ConfigEntryAuthFailed(f"Identifiants Calyps'HOME refusés: {err}") from err
        except CalypsHomeError as err:
            # Marque les entités comme indisponibles et, au démarrage, fait réessayer Home Assistant
            raise UpdateFailed(f"Impossible de mettre à jour les données Calyps'HOME: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        LOGGER,
        config_entry=entry,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=_async_update_data,
        update_interval=timedelta(minutes=UPDATE_INTERVAL),
    )

    async def on_ws_update(ws_update=None) -> None:
        """Callback appelé lorsqu'une mise à jour est reçue via le websocket"""
        # Vérifie que la mise à jour contient les informations nécessaires
        if (
            not ws_update
            or not (real_name := ws_update.get("real_name"))
            or not (field := ws_update.get("field"))
            or (field_value := ws_update.get("value")) is None
            or not coordinator.data
        ):
            return

        updated = False
        next_objects = []

        # Parcourt les objets existants pour trouver celui correspondant à la mise à jour
        for obj in coordinator.data:
            if obj.real_name == real_name:
                obj: CalypsHomeObject = copy.copy(obj)
                statuses = list(obj.statuses)

                # Met à jour le statut concerné (level, temperature, illuminance, ...) si présent, sinon l'ajoute
                if status := next((s for s in statuses if isinstance(s, dict) and s.get("name") == field), None):
                    status = dict(status)
                    status["value"] = field_value
                    statuses = [status if isinstance(s, dict) and s.get("name") == field else s for s in statuses]
                else:
                    statuses = statuses + [{"name": field, "value": field_value}]

                obj.statuses = statuses
                updated = True

            next_objects.append(obj)

        if updated:
            # On n'utilise pas `async_set_updated_data`, qui repousserait le polling à chaque
            # événement websocket: avec des sondes bavardes, le polling n'aurait plus jamais lieu.
            coordinator.data = next_objects
            coordinator.async_update_listeners()

    api.on_update = on_ws_update

    # Récupérer les données initiales. En cas d'échec, Home Assistant réessaiera automatiquement
    # (ConfigEntryNotReady) ou proposera de saisir à nouveau les identifiants (ConfigEntryAuthFailed).
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await hass.async_add_executor_job(api.close)
        raise

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    # Démarrer l'écouteur websocket pour les mises à jour en temps réel.
    # La tâche est rattachée à l'entrée: Home Assistant l'annule au déchargement et à l'arrêt.
    await api.start_websocket(
        lambda coro: entry.async_create_background_task(hass, coro, f"{DOMAIN}_websocket_{entry.entry_id}")
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée config"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and (api := entry_data.get("api")):
            await api.async_stop_websocket()
            await hass.async_add_executor_job(api.close)

    return unload_ok
