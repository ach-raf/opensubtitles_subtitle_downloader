import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict
from pathlib import Path
import yaml
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class ModelName(Enum):
    GEMINI = "gemini-1.5-flash"
    GPT4O = "gpt-4o-mini"
    MISTRAL_LARGE = "mistral-large-latest"


@dataclass
class ModelParameters:
    context_length: int
    default_temperature: float
    max_tokens: int = 4096
    top_p: float = 1.0


@dataclass
class ProviderConfig:
    api_base: str
    api_key: str
    models: Dict[str, ModelParameters]


class ModelConfiguration:
    def __init__(self, config_path: str | Path = "model_config.yaml"):
        self.config_path = Path(config_path)
        self.reload_config()

    def reload_config(self) -> None:
        """Reload configuration from YAML file"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)

        self.providers: Dict[str, ProviderConfig] = {}
        for provider_name, provider_data in raw_config["providers"].items():
            models = {
                model_name: ModelParameters(**model_params)
                for model_name, model_params in provider_data["models"].items()
            }
            self.providers[provider_name] = ProviderConfig(
                api_base=provider_data["api_base"],
                api_key=provider_data["api_key"],
                models=models,
            )

    def get_model_info(self, model_name: str) -> tuple[ProviderConfig, ModelParameters]:
        """Get provider config and model parameters for given model"""
        for provider in self.providers.values():
            if model_name in provider.models:
                return provider, provider.models[model_name]
        raise ValueError(f"Model {model_name} not found in any provider")

    def list_available_models(self) -> Dict[str, list[str]]:
        """Return dictionary of provider -> list of available models"""
        return {
            provider: list(config.models.keys())
            for provider, config in self.providers.items()
        }


_config_cache: Optional[ModelConfiguration] = None


def get_model_parameters(
    model_name: str,
    config_path: Optional[str | Path] = None,
) -> ModelParameters:
    """Get model parameters without initializing the client"""
    global _config_cache

    if _config_cache is None:
        _config_cache = (
            ModelConfiguration(config_path) if config_path else ModelConfiguration()
        )

    _, model_params = _config_cache.get_model_info(model_name)
    return model_params


def initialize_client(
    model_name: str,
    api_key: Optional[str] = None,
    config_path: Optional[str | Path] = None,
) -> OpenAI:
    """Initialize OpenAI client"""
    global _config_cache

    if _config_cache is None:
        _config_cache = (
            ModelConfiguration(config_path) if config_path else ModelConfiguration()
        )

    provider_config, _ = _config_cache.get_model_info(model_name)

    api_key = api_key or os.getenv(provider_config.api_key)
    if not api_key:
        raise ValueError(f"API key required via {provider_config.api_key}")

    client = OpenAI(api_key=api_key, base_url=provider_config.api_base)

    return client
