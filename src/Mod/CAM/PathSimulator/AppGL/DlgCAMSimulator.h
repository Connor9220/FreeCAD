// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2017 Shai Seger <shaise at gmail>                       *
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

#ifdef _MSC_VER
# pragma warning(disable : 4251)
#endif

#include <deque>
#include <queue>
#include <functional>
#include <chrono>
#include <string>
#include <vector>

#include <QOpenGLWidget>
#include <QPainter>
#include <QTimer>
#include <QExposeEvent>
#include <QResizeEvent>
#include <QMouseEvent>
#include <QOpenGLContext>

#include <Mod/Part/App/TopoShape.h>

#include "MillMotion.h"

class SoCamera;

namespace Base
{
class Placement;
class Rotation;
}  // namespace Base

namespace Gui
{
class MDIView;
class Document;
}  // namespace Gui

namespace CAMSimulator
{

// use short declaration as using 'include' causes a header loop
class MillSimulation;
struct MillSimulationState;
struct Vertex;
class ViewCAMSimulator;
class GuiDisplay;
class Dummy3DViewer;

struct SimShape
{
public:
    float maxDimension() const;

public:
    std::vector<Vertex> verts;
    std::vector<GLushort> indices;
    bool needsUpdate = false;
    // the color it is drawn in, where it has one of its own
    bool colored = false;
    float color[3] = {0, 0, 0};
};

// A G-code line, or a change of the work plane frame the lines after it are given in
struct SimGCode
{
public:
    std::string line;  // the G-code, or the name of the operation that starts here
    bool isFrame = false;
    bool isOpStart = false;
    MillFrame frame;
};

struct SimTool
{
public:
    std::vector<float> profile;
    int id;
    float diameter;
    float resolution;
    std::vector<float> holder;  // the outline of the holder it is set in, if any
    std::vector<float> shank;   // the outline of the tool above its cutting edges, if known
};

class DlgCAMSimulator: public QOpenGLWidget
{
    Q_OBJECT

    typedef std::chrono::steady_clock clock;

public:
    explicit DlgCAMSimulator(QWidget* parent = nullptr);
    ~DlgCAMSimulator() override;

    void connectTo(GuiDisplay& gui, Dummy3DViewer& dv);
    void cloneFrom(const DlgCAMSimulator& from);

    static DlgCAMSimulator* instance(Gui::Document* doc = nullptr);

    void setAnimating(bool animating);
    void startSimulation(const Part::TopoShape& stock, float quality);
    void resetSimulation();

    void addGcodeCommand(const char* cmd);
    void beginOperation(const std::string& name);
    void setFrame(
        const Base::Placement& placement,
        const Base::Rotation& pose,
        float indexRate,
        const std::vector<float>& angles
    );
    void setRotaryAxes(const std::vector<SimRotaryAxis>& axes);
    void addTool(
        const std::vector<float>& toolProfilePoints,
        int toolNumber,
        float diameter,
        float resolution,
        const std::vector<float>& holderProfilePoints = {},
        const std::vector<float>& shankProfilePoints = {}
    );

    void setStockShape(const Part::TopoShape& shape, float resolution);
    void setStockVisible(bool b);
    void setBaseShape(const Part::TopoShape& shape, float resolution);
    // cuttable: soft jaws, the tool cutting them only a warning
    void setWorkholdingShape(
        const Part::TopoShape& shape,
        float resolution,
        bool cuttable = false,
        const float* color = nullptr,
        bool append = false
    );
    void setBaseVisible(bool b);

    void setRotateEnabled(bool b);

    void setBackgroundColor(const QColor& c);
    // FreeCAD's axis colors and the origin's, 0xRRGGBBAA
    void setAxisColors(unsigned long x, unsigned long y, unsigned long z, unsigned long origin);
    void setPathColor(const QColor& normal, const QColor& rapid);

Q_SIGNALS:
    void simulationStarted();

protected:
    void timerEvent(QTimerEvent* event) override;

    void updateResources();
    void updateWindowScale();
    void updateCamera();

    void initializeGL() override;
    void paintGL() override;
    void resizeGL(int w, int h) override;

    void updateGui();

private:
    bool mNeedsInitialize = false;
    bool mNeedsClear = false;
    bool mAnimating = false;
    int mAnimatingTimer = 0;

    std::unique_ptr<MillSimulation> mMillSimulator;
    float mQuality = 10;

    std::vector<SimGCode> mGCode;
    std::size_t mLastGCode = 0;

    std::vector<SimTool> mTools;
    std::vector<SimRotaryAxis> mRotaryAxes;

    const SoCamera* mCamera = nullptr;
    SimShape mStock;
    SimShape mBase;
    std::vector<SimShape> mWorkholding;  // in pieces each within short indices
    std::vector<SimShape> mSoftJaws;     // cut into with a warning, in pieces the same
    bool mWorkholdingNeedsUpdate = false;

    std::unique_ptr<MillSimulationState> mState;
    clock::time_point mLastProcessSim = clock::time_point::min();
    std::deque<clock::time_point> mFrameTimes;
    float mFps = 0;

    GuiDisplay* mGui = nullptr;
    // the 3D view's background, for the readouts over it once they are there
    QColor mBackground;
    Dummy3DViewer* mDummyViewer = nullptr;
};

}  // namespace CAMSimulator
