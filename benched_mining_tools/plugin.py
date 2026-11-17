from qgis.core import QgsApplication

from .provider import BenchedMiningProvider


class BenchedMiningPlugin:
    def __init__(self):
        self.provider = None

    def initProcessing(self):
        if self.provider is None:
            self.provider = BenchedMiningProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
