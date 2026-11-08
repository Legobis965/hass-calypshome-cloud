import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult

from .api import CalypsHomeAPI, CalypsHomeAuthError, CalypsHomeError
from .const import DOMAIN, CONF_LOGIN, CONF_PASSWORD

LOGGER = logging.getLogger(__name__)
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOGIN): str,
        vol.Required(CONF_PASSWORD): str
    }
)


def _unique_id(login: str) -> str:
    """Identifiant unique d'un compte Calyps'HOME (l'email, normalisé)"""
    return login.strip().lower()


def _entry_title(login: str) -> str:
    """Titre de l'entrée de configuration"""
    return f"Calyps'HOME ({login})"


def _check_credentials(login: str, password: str) -> None:
    """Vérifie que les identifiants permettent de se connecter et de lister les objets (bloquant)

    Raises:
        CalypsHomeAuthError: Si les identifiants sont refusés
        CalypsHomeError: Si le cloud est injoignable
    """
    api = CalypsHomeAPI(login, password)
    try:
        api.login()
        api.get_objects()
    finally:
        api.close()


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, str]:
    """Valide que l'entrée utilisateur permet de se connecter"""
    await hass.async_add_executor_job(_check_credentials, data[CONF_LOGIN], data[CONF_PASSWORD])
    return {"title": _entry_title(data[CONF_LOGIN])}


async def _async_validate(hass: HomeAssistant, data: dict) -> tuple[dict[str, str] | None, dict[str, str]]:
    """Valide les identifiants et retourne `(info, errors)`"""
    try:
        return await validate_input(hass, data), {}
    except CalypsHomeAuthError as err:
        LOGGER.warning("Identifiants Calyps'HOME refusés: %s", err)
        return None, {"base": "invalid_auth"}
    except CalypsHomeError as err:
        LOGGER.warning("Impossible de se connecter à Calyps'HOME: %s", err)
        return None, {"base": "cannot_connect"}
    except Exception:
        LOGGER.exception("Exception inattendue")
        return None, {"base": "unknown"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère un flux de configuration pour Calyps'HOME"""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        """Gère l'étape initiale"""

        errors: dict[str, str] = {}

        if user_input is not None:
            # Empêche d'ajouter deux fois le même compte (y compris les entrées créées sans unique_id)
            await self.async_set_unique_id(_unique_id(user_input[CONF_LOGIN]))
            self._abort_if_unique_id_configured()
            self._async_abort_entries_match({CONF_LOGIN: user_input[CONF_LOGIN]})

            # Valider la configuration
            info, errors = await _async_validate(self.hass, user_input)
            if info is not None:
                # Créer l'entrée de configuration
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input or {}),
            errors=errors,
        )


    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Démarre la réauthentification lorsque le cloud refuse les identifiants"""
        return await self.async_step_reauth_confirm()


    async def async_step_reauth_confirm(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        """Demande de nouveaux identifiants (l'email peut être changé) pour le compte existant"""
        return await self._async_step_update_credentials("reauth_confirm", self._get_reauth_entry(), user_input)


    async def async_step_reconfigure(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        """Permet de changer l'email ou le mot de passe du compte à tout moment"""
        return await self._async_step_update_credentials("reconfigure", self._get_reconfigure_entry(), user_input)


    async def _async_step_update_credentials(
        self,
        step_id: str,
        entry: ConfigEntry,
        user_input: dict[str, str] | None,
    ) -> ConfigFlowResult:
        """Étape commune à la réauthentification et à la reconfiguration

        Valide les nouveaux identifiants, refuse un email déjà utilisé par une autre entrée,
        puis met à jour l'entrée (email, mot de passe, unique_id, titre) et la recharge.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            login = user_input[CONF_LOGIN].strip()
            new_unique_id = _unique_id(login)

            # L'email a pu changer : il ne doit pas correspondre à un autre compte déjà configuré
            if any(
                other.entry_id != entry.entry_id
                and (other.unique_id == new_unique_id or _unique_id(other.data.get(CONF_LOGIN, "")) == new_unique_id)
                for other in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")

            data = {**entry.data, CONF_LOGIN: login, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            info, errors = await _async_validate(self.hass, data)
            if info is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_unique_id,
                    title=info["title"],
                    data=data,
                )

        suggested = {CONF_LOGIN: (user_input or entry.data).get(CONF_LOGIN)}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, suggested),
            description_placeholders={"login": entry.data[CONF_LOGIN]},
            errors=errors,
        )
