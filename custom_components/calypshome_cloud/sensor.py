import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, LIGHT_LUX

from .api import CalypsHomeAPI, CalypsHomeObject
from .const import DOMAIN
from .entity import CalypsHomeEntity

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Configure les sondes Calyps'HOME à partir d'une entrée config

    Args:
        hass: Instance de Home Assistant
        entry: Entrée de configuration
        async_add_entities: Callback pour ajouter des entités à Home Assistant
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    api = entry_data["api"]
    coordinator = entry_data["coordinator"]
    objects = coordinator.data

    if objects is None:
        LOGGER.error("Impossible de récupérer les objets de Calyps'HOME")
        return

    sonde_objects = [obj for obj in objects if isinstance(obj, CalypsHomeObject) and obj.class_name == "Sonde"]

    entities: list[SensorEntity] = []
    for obj in sonde_objects:
        statuses_names = {item.get("name") for item in (obj.statuses or []) if isinstance(item, dict)}
        if "temperature" in statuses_names:
            entities.append(CalypsHomeTemperatureSensor(coordinator, api, obj))
        if "illuminance" in statuses_names:
            entities.append(CalypsHomeIlluminanceSensor(coordinator, api, obj))

    if entities:
        async_add_entities(entities)
        LOGGER.info("%d capteurs Calyps'HOME ajoutés", len(entities))


SENSOR_MODEL = "Sensor"


class CalypsHomeSensorBase(CalypsHomeEntity, SensorEntity):
    """Base commune pour les capteurs Calyps'HOME (température, luminosité, ...)"""

    _status_name: str = ""
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, api: CalypsHomeAPI, object: CalypsHomeObject):
        """
        Args:
            coordinator: Coordinateur de mise à jour des données
            api: Instance de `CalypsHomeAPI`
            object: Objet `CalypsHomeObject` représentant la sonde
        """
        super().__init__(coordinator, api, object, model=SENSOR_MODEL)
        # Le nom du statut sert aussi de suffixe d'unique_id et de clé de traduction du nom
        self._attr_unique_id = f"{self._device_id}_{self._status_name}"
        self._attr_translation_key = self._status_name
        self._attr_native_value = None

    def _find_status_value(self) -> str | None:
        """Récupère la valeur brute (str) du statut `_status_name` pour cette sonde, ou None"""
        sonde = self._find_object()
        if not sonde:
            return None

        for item in sonde.statuses or []:
            if isinstance(item, dict) and item.get("name") == self._status_name:
                return item.get("value")
        return None

    def _handle_coordinator_update(self) -> None:
        """Met à jour la valeur du capteur à partir des données du coordinateur partagé"""
        try:
            raw_value = self._find_status_value()
            if raw_value is not None:
                self._attr_native_value = float(raw_value)
            self.async_write_ha_state()
        except (ValueError, TypeError) as err:
            LOGGER.error("Erreur lors de la mise à jour du capteur %s (%s): %s", self._device_name, self._status_name, err)

    async def async_added_to_hass(self) -> None:
        """Configure le callback pour les mises à jour du coordinateur"""
        await super().async_added_to_hass()
        self._handle_coordinator_update()


class CalypsHomeTemperatureSensor(CalypsHomeSensorBase):
    """Capteur de température d'une sonde Calyps'HOME"""

    _status_name = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1


class CalypsHomeIlluminanceSensor(CalypsHomeSensorBase):
    """Capteur de luminosité d'une sonde Calyps'HOME"""

    _status_name = "illuminance"
    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_suggested_display_precision = 0
