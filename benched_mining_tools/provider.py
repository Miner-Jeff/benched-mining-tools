import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.pit import BenchedOpenPit
from .algorithms.pile import BenchedWasteRockPile
from . import core


class BenchedMiningProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(BenchedOpenPit())
        self.addAlgorithm(BenchedWasteRockPile())

    def id(self):
        return "benchedmining"

    def name(self):
        return "Benched Mining Tools"

    def longName(self):
        return "Benched Mining Tools v%s" % core.VERSION

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
