"""Plateforme button pour Calyps'HOME : rappel de la position favorite des volets"""
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.button import ButtonEntity

from .api import CalypsHomeObject
from .const import DOMAIN
from .entity import CalypsHomeEntity
from .cover import SHUTTER_CLASS, SHUTTER_MODEL

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Crée un bouton « Position favorite » pour chaque volet qui supporte cette action"""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    api = entry_data["api"]
    coordinator = entry_data["coordinator"]
    objects = coordinator.data or []

    entities = [
        CalypsHomeFavoriteButton(coordinator, api, obj)
        for obj in objects
        if isinstance(obj, CalypsHomeObject) and obj.class_name == SHUTTER_CLASS and obj.supports_favorite
    ]

    if entities:
        async_add_entities(entities)
        LOGGER.info("%d boutons de position favorite Calyps'HOME ajoutés", len(entities))


class CalypsHomeFavoriteButton(CalypsHomeEntity, ButtonEntity):
    """Bouton qui envoie le volet à la position favorite mémorisée dans son moteur"""

    _attr_translation_key = "favorite_position"

    def __init__(self, coordinator, api, object: CalypsHomeObject):
        super().__init__(coordinator, api, object, model=SHUTTER_MODEL)
        self._attr_unique_id = f"{self._device_id}_favorite"

    async def async_press(self) -> None:
        """Rappelle la position favorite (la position réelle remonte ensuite par le websocket)"""
        if not await self.hass.async_add_executor_job(self._api.call_favorite, self._device_id):
            raise HomeAssistantError(f"Impossible d'envoyer le volet {self._device_name} à sa position favorite")
