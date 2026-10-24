"""
Módulo de utilidades de logging para la aplicación.

Proporciona:
- MonthlyDailyRotatingFileHandler: un handler que rota logs diariamente y organiza
  los ficheros dentro de carpetas por mes (YYYY-MM).
- Logger: wrapper singleton para obtener un logger configurado con consola y archivo.

Ejemplos:
    logger = Logger.get_logger()
    logger.info("Arrancando aplicación")
"""

import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

class MonthlyDailyRotatingFileHandler(TimedRotatingFileHandler):
    """
    Rotates log files daily and creates a new folder for each month.
    """
    def __init__(self, base_dir="./output-logs", when="midnight", interval=1, backupCount=30, encoding=None):
        self.base_dir = base_dir
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        self.current_month = None
        log_path = self._get_log_path()
        super().__init__(log_path, when=when, interval=interval, backupCount=backupCount, encoding=encoding)

    def _get_log_path(self):
        now = datetime.now()
        month_folder = os.path.join(self.base_dir, now.strftime("%Y-%m"))
        if not os.path.exists(month_folder):
            os.makedirs(month_folder, exist_ok=True)
        return os.path.join(month_folder, now.strftime("%Y-%m-%d") + ".log")

    def doRollover(self):
        """Overrides TimedRotatingFileHandler rollover to also handle monthly folder creation"""
        self.stream.close()
        self.baseFilename = self._get_log_path()
        self.stream = self._open()

class Logger:
    """
    Singleton que expone un logger configurado para la aplicación.

    Configura:
    - StreamHandler (consola) a nivel DEBUG.
    - MonthlyDailyRotatingFileHandler (archivo) a nivel DEBUG.
    - Formato: "%(asctime)s - %(levelname)s - %(message)s".

    Uso:
        logger = Logger.get_logger()
        logger.debug("mensaje")
    """
    
    _ENV = os.getenv("ENV", "development")
    assert _ENV in ["development", "production"], "ENV debe ser 'development' o 'production'"

    @classmethod
    def get_logger(cls):
        """
        Devuelve la instancia singleton del logger.

        Si aún no existe la instancia, la crea.

        Returns:
            logging.Logger: Logger configurado para la aplicación.
        """
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance.logger
    
    def __init__(self):
        """
        Configura el logger (stream + file handler) si aún no tiene handlers.
        """
        self.logger = logging.getLogger("aqua-logger")
        self.formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        if not self.logger.hasHandlers():
            
            if self._ENV == "production":
                handler = MonthlyDailyRotatingFileHandler("./logs", encoding="utf-8")
            else:
                handler = logging.StreamHandler(sys.stdout)

            handler.stream.reconfigure(encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(self.formatter)
            self.logger.setLevel(logging.DEBUG)
            self.logger.propagate = False
            self.logger.addHandler(handler)

logger = Logger.get_logger()