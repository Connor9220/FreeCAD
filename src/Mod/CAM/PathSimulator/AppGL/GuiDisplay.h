// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Shai Seger <shaise at gmail>                       *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#pragma once

#include <QWidget>
#include <string>
#include <vector>

#include "MillMotion.h"

namespace CAMSimulator
{
class Ui_GuiDisplay;
class OperationMarkers;
class IndexTimeline;

class GuiDisplay: public QWidget
{
    Q_OBJECT

public:
    explicit GuiDisplay(QWidget* parent = nullptr);
    ~GuiDisplay();

    void setPlaying(bool b);
    void setSpeed(int s);
    void setStage(float f, int total);
    void setTime(float seconds, float totalSeconds);
    void setFeed(float feed, bool rapid);
    void setFeedLabel(const QString& text, bool rapid);
    void setOperationStarts(const std::vector<float>& starts);
    void setOperation(const QString& name);
    void setIndexSpans(const std::vector<SimTimeSpan>& spans, const QStringList& axisNames);
    void setIndexAngles(const QStringList& axisNames, const std::vector<float>& angles);

    void setStockVisible(bool b);
    void setBaseVisible(bool b);
    void setRotateEnabled(bool b);
    void setPathVisible(bool b);
    void setSsaoEnabled(bool b);
    void setTablePoseEnabled(bool b);
    void setIndexMode(int mode);
    void setIncrementalEnabled(bool b);
    void setDexelEnabled(bool b);
    void setFps(float fps);

Q_SIGNALS:
    void play(bool b);
    void singleStep();
    void nextMark();
    void previousMark();
    void speedChanged(int s);
    void stageChanged(float f);

    void viewAll();
    void stockVisibleChanged(bool b);
    void baseVisibleChanged(bool b);
    void rotateEnableChanged(bool b);
    void pathVisibleChanged(bool b);
    void ssaoEnableChanged(bool b);
    void tablePoseEnableChanged(bool b);
    void indexModeChanged(int mode);
    void incrementalEnableChanged(bool b);
    void dexelEnableChanged(bool b);

protected:
    void resizeEvent(QResizeEvent* event) override;
    bool eventFilter(QObject* watched, QEvent* event) override;

private Q_SLOTS:
    void on_playButton_clicked();
    void on_singleStepButton_clicked();
    void on_nextOpButton_clicked();
    void on_prevOpButton_clicked();
    void on_indexModeButton_clicked();

    void onSlowerFasterButtonClicked();
    void on_stageSlider_sliderMoved(int value);

    void on_stockModelButton_clicked();

private:
    Ui_GuiDisplay* ui;
    OperationMarkers* opMarkers;
    IndexTimeline* indexTimeline;

    bool playing = true;
    int indexMode = -1;
    int speed = 1;

    bool stockVisible = true;
    bool baseVisible = false;
};

}  // namespace CAMSimulator
