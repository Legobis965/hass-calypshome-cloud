"""Entité de base commune aux plateformes Calyps'HOME"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .api import CalypsHomeAPI, CalypsHomeObject
from .const import DOMAIN

MANUFACTURER = "Calyps'HOME"


class CalypsHomeEntity(CoordinatorEntity):
    """Entité rattachée à un objet Calyps'HOME (un appareil Home Assistant par objet)

    Le nom de l'entité est composé par Home Assistant à partir du nom de l'appareil
    (`has_entity_name`) et, pour les entités secondaires, d'un nom traduit (`translation_key`).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: CalypsHomeAPI,
        object: CalypsHomeObject,
        model: str,
    ) -> None:
        """
        Args:
            coordinator: Coordinateur de mise à jour des données
            api: Instance de `CalypsHomeAPI`
            object: Objet Calyps'HOME représenté par l'entité
            model: Modèle affiché sur la fiche de l'appareil
        """
        super().__init__(coordinator)
        self._api = api
        self._device_id = object.id
        self._device_name = object.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(object.id))},
            name=object.name,
            manufacturer=MANUFACTURER,
            model=model,
        )

    def _find_object(self) -> CalypsHomeObject | None:
        """Retourne l'objet Calyps'HOME courant de cette entité dans les données du coordinateur"""
        objects = self.coordinator.data
        if not objects:
            return None
        return next((obj for obj in objects if obj is not None and obj.id == self._device_id), None)
