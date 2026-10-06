# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *   Copyright (c) 2021 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import FreeCAD
import FreeCADGui
import Path

if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())

translate = FreeCAD.Qt.translate

# where the simulator runs, as the preferences keep it, and what Automatic's test of this computer
# left: its date and what it last picked
SimulatorRunsOn = "SimulatorDexelCutting"
SimulatorAutoResults = (
    "SimulatorAutoKey",
    "SimulatorAutoTested",
    "SimulatorAutoPick",
    "SimulatorAutoCardUsable",
    "SimulatorAutoCpuCut",
    "SimulatorAutoCpuArea",
    "SimulatorAutoCardCut",
    "SimulatorAutoCardArea",
)


class AdvancedPreferencesPage:
    def __init__(self, parent=None):
        self.form = FreeCADGui.PySideUic.loadUi(":preferences/Advanced.ui")
        if hasattr(self.form.WarningSuppressAllSpeeds, "checkStateChanged"):  # Qt version >= 6.7.0
            self.form.WarningSuppressAllSpeeds.checkStateChanged.connect(self.updateSelection)
            self.form.EnableAdvancedOCLFeatures.checkStateChanged.connect(self.updateSelection)
        else:  # Qt version < 6.7.0
            self.form.WarningSuppressAllSpeeds.stateChanged.connect(self.updateSelection)
            self.form.EnableAdvancedOCLFeatures.stateChanged.connect(self.updateSelection)
        self.form.SimulatorRunsOn.currentIndexChanged.connect(self.showSimulatorPick)
        self.form.SimulatorClearTest.clicked.connect(self.clearSimulatorTest)

    def saveSettings(self):
        Path.Preferences.setPreferencesAdvanced(
            self.form.EnableAdvancedOCLFeatures.isChecked(),
            self.form.WarningSuppressAllSpeeds.isChecked(),
            self.form.WarningSuppressRapidSpeeds.isChecked(),
            self.form.WarningSuppressSelectionMode.isChecked(),
            self.form.WarningSuppressOpenCamLib.isChecked(),
        )
        Path.Preferences.preferences().SetInt(
            SimulatorRunsOn, self.form.SimulatorRunsOn.currentIndex()
        )

    def loadSettings(self):
        Path.Log.track()
        self.form.WarningSuppressAllSpeeds.setChecked(Path.Preferences.suppressAllSpeedsWarning())
        self.form.WarningSuppressRapidSpeeds.setChecked(
            Path.Preferences.suppressRapidSpeedsWarning(False)
        )
        self.form.WarningSuppressSelectionMode.setChecked(
            Path.Preferences.suppressSelectionModeWarning()
        )
        self.form.EnableAdvancedOCLFeatures.setChecked(
            Path.Preferences.advancedOCLFeaturesEnabled()
        )
        self.form.WarningSuppressOpenCamLib.setChecked(Path.Preferences.suppressOpenCamLibWarning())
        self.form.SimulatorRunsOn.setCurrentIndex(
            Path.Preferences.preferences().GetInt(SimulatorRunsOn, 0)
        )
        self.updateSelection()
        self.showSimulatorPick()

    def showSimulatorPick(self, *args):
        """What Automatic picked the last time the simulator ran, and when it tested this
        computer; nothing for a side chosen here."""
        note = self.form.SimulatorAutoNote
        prefs = Path.Preferences.preferences()
        tested = prefs.GetString("SimulatorAutoTested", "")
        automatic = self.form.SimulatorRunsOn.currentIndex() == 0
        note.setVisible(automatic)
        self.form.SimulatorClearTest.setEnabled(bool(tested))
        if not tested:
            note.setText(
                translate(
                    "CAM_Preferences",
                    "Automatic: not tested yet. It tests this computer the next time the "
                    "simulator starts.",
                )
            )
            return
        picks = {
            "Processor": translate("CAM_Preferences", "Processor"),
            "Graphics card": translate("CAM_Preferences", "Graphics card"),
        }
        pick = prefs.GetString("SimulatorAutoPick", "")
        note.setText(
            translate("CAM_Preferences", "Automatic: %s (tested %s)")
            % (picks.get(pick, pick), tested)
        )

    def clearSimulatorTest(self):
        """The test of this computer forgotten: done again the next time the simulator starts."""
        prefs = Path.Preferences.preferences()
        for name in SimulatorAutoResults:
            prefs.RemString(name)
            prefs.RemFloat(name)
            prefs.RemBool(name)
        self.showSimulatorPick()

    def updateSelection(self, state=None):
        self.form.WarningSuppressOpenCamLib.setEnabled(
            self.form.EnableAdvancedOCLFeatures.isChecked()
        )

        if self.form.WarningSuppressAllSpeeds.isChecked():
            self.form.WarningSuppressRapidSpeeds.setChecked(True)
            self.form.WarningSuppressRapidSpeeds.setEnabled(False)
        else:
            self.form.WarningSuppressRapidSpeeds.setEnabled(True)
