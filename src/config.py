"""Configuration module for Crypto Market Data Service.

Implements configuration management using Pydantic Settings with support for:
- Environment variables
- YAML configuration files
- Type validation and defaults
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExchangeConfig(BaseModel):
    """交易所配置（嵌套配置不应继承 BaseSettings）"""
    
    id: str = Field(..., description="交易所ID (binance, okx等)")
    api_key: Optional[str] = Field(default=None, description="API Key")
    secret: Optional[str] = Field(default=None, description="API Secret")
    symbols: List[str] = Field(default_factory=list, description="交易对列表")


class Settings(BaseSettings):
    """应用配置"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )
    
    # 数据库
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/market_data",
        description="PostgreSQL连接字符串",
    )
    database_pool_size: int = Field(default=10, ge=1, le=50, description="数据库连接池大小")
    
    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis连接URL",
    )
    ohlcv_cache_size: int = Field(default=500, ge=100, le=2000, description="OHLCV缓存条数")
    ticker_ttl_seconds: int = Field(default=10, ge=1, le=60, description="Ticker缓存TTL")
    
    # API
    api_host: str = Field(default="0.0.0.0", description="API监听地址")
    api_port: int = Field(default=8000, ge=1, le=65535, description="API监听端口")
    
    # Authentication
    api_token: str = Field(
        default="",
        description="API认证Token（生产环境必须配置）",
    )
    
    # 调度
    retry_max_attempts: int = Field(default=5, ge=1, le=10, description="最大重试次数")
    
    # 数据采集
    exchanges: List[ExchangeConfig] = Field(default_factory=list, description="交易所配置列表")
    timeframes: List[str] = Field(
        default=["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"],
        description="支持的K线周期",
    )
    gap_fill_enabled: bool = Field(default=True, description="是否启用数据补全")
    gap_fill_days: int = Field(default=7, ge=1, le=365, description="数据补全天数")
    
    # 配置文件路径
    config_file: Optional[str] = Field(default=None, description="YAML配置文件路径")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 如果指定了配置文件，从YAML加载交易所配置
        if self.config_file:
            self._load_yaml_config()
    
    def _load_yaml_config(self) -> None:
        """从YAML文件加载配置"""
        config_path = Path(self.config_file)
        if not config_path.exists():
            raise ValueError(f"Configuration file not found: {self.config_file}")
        
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_config = yaml.safe_load(f)
        
        if yaml_config and "exchanges" in yaml_config:
            self.exchanges = [
                ExchangeConfig(**ex) for ex in yaml_config["exchanges"]
            ]
        
        # 覆盖其他配置项
        if yaml_config:
            for key in ["timeframes", "gap_fill_enabled", "gap_fill_days"]:
                if key in yaml_config:
                    setattr(self, key, yaml_config[key])


@lru_cache
def get_settings() -> Settings:
    """获取配置单例（使用 lru_cache 避免重复加载）"""
    return Settings()


def clear_settings_cache() -> None:
    """清除配置缓存（用于热重载）"""
    get_settings.cache_clear()
