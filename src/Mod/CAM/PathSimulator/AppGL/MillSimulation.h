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

#include "AxisOverlay.h"
#include "DexelStock.h"
#include "GCodeParser.h"
#include "MillPathLine.h"
#include "MillPathSegment.h"
#include "SimDisplay.h"
#include "SolidObject.h"
#include "StockObject.h"
#include "linmath.h"
#include <chrono>
#include <vector>

#define VIEWITEM_SIMULATION 1
#define VIEWITEM_BASE_SHAPE 2
#define VIEWITEM_MAX 4

namespace CAMSimulator
{

// How the table turns between two poses
enum IndexMode
{
    IndexSequenced = 0,  // axis by axis, one sequence after another, as the machine says
    IndexTogether,       // all axes at once, finishing together, as one rotary block moves them
    IndexShortest,       // the shortest rotation between the poses, whatever the axes
    IndexModeCount
};

struct MillSimulationState
{
    int mCurStep = 0;
    int mNTotalSteps = 0;
    int mPathStep = -1;
    int mSubStep = 0;
    int mNPathSteps = 0;
    int mSimSpeed = 10;    // multiple of real time
    float mSimTime = 0;    // seconds into the program, as the machine runs it
    float mTotalTime = 0;  // seconds the whole program takes
    float mCurFeed = 0;    // mm/s of the current move, 0 when not known
    bool mCurRapid = false;
    int mViewItems = VIEWITEM_SIMULATION;
    bool mViewPath = false;
    bool mViewSSAO = false;
    bool mViewTablePose = true;  // the part turns with the rotary table; else the tool tilts
    int mIndexMode = 0;          // how an index turns the table: an IndexMode
    bool mIncremental = false;   // keep the cut stock between frames and draw only new moves
    bool mDexelEngine = false;   // the stock as dexels, cut once, rather than CSG every frame
    bool mViewAxes = true;       // the work coordinates, work plane and rotary axes over the view

    bool mSimPlaying = false;
    bool mSingleStep = false;
};

class MillSimulation: private MillSimulationState
{
    typedef std::chrono::steady_clock clock;

public:
    MillSimulation();
    ~MillSimulation();
    void ClearMillPathSegments();
    void Clear();
    void InitSimulation(float quality, float maxStockDimension);
    void AddTool(EndMill* tool);
    void AddTool(const std::vector<float>& toolProfile, int toolid, float diameter);
    bool ToolExists(int toolid);
    void RenderSimulation();
    void RenderTool();
    void RenderPath();
    void RenderBaseShape();
    void Render();
    void ProcessSim(const clock::duration& elapsed);
    void SimNext(const clock::duration& elapsed);

    bool LoadGCodeFile(const char* fileName);
    bool AddGcodeLine(const char* line);
    void SetFrame(const MillFrame& frame);
    void BeginOperation(const std::string& name);
    void SkipToNextMark();
    void SkipToPreviousMark();
    const std::vector<SimTimeSpan>& GetIndexSpans() const;
    const std::vector<SimRotaryAxis>& GetRotaryAxes() const;
    bool GetIndexAngles(std::vector<float>& angles) const;
    const std::vector<float>& GetOperationStarts() const;
    std::string GetCurrentOperation() const;

    void SetPlaying(bool b);
    void SingleStep();
    void SetSpeed(int s);

    void SetSimulationStage(float stage);
    void SetState(const MillSimulationState& state);
    const MillSimulationState& GetState() const;

    void SetBoxStock(float x, float y, float z, float l, float w, float h);
    void SetArbitraryStock(const std::vector<Vertex>& verts, const std::vector<GLushort>& indices);
    void SetStockVisible(bool b);
    bool IsStockVisible() const;

    void SetBaseObject(const std::vector<Vertex>& verts, const std::vector<GLushort>& indices);
    void SetBaseVisible(bool b);
    bool IsBaseVisible() const;

    void SetPathVisible(bool b);
    void EnableSsao(bool b);
    void EnableIncremental(bool b);
    void EnableDexel(bool b);
    void EnableAxes(bool b);
    // FreeCAD's axis colours and the origin's, 0xRRGGBBAA
    void SetAxisColors(unsigned long x, unsigned long y, unsigned long z, unsigned long origin);
    // pixels a screen point, for the indicators' sizes
    void SetPixelRatio(float ratio);
    void EnableTablePose(bool b);
    void SetIndexMode(int mode);
    void SetRotaryAxes(const std::vector<SimRotaryAxis>& axes);

    void UpdateWindowScale(int width, int height);
    void UpdateCamera(const SoCamera& camera);

    void SetBackgroundColor(const vec3& c);
    void SetPathColor(const vec3& normal, const vec3& rapid);

protected:
    void InitDisplay(float quality);
    void GlsimStart();
    void GlsimToolStep1(void);
    void GlsimToolStep2(void);
    void GlsimClipBack(void);
    void GlsimRenderStock(void);
    void GlsimRenderTools(void);
    void GlsimEnd(void);
    void RenderSweeps(int first, bool fromScratch);
    bool PrepareDexel();
    bool CutDexel();
    void RenderDexel();
    void RenderAxes();
    bool CurrentAngles(std::vector<float>& angles) const;
    void RenderSimulationCached();
    void renderSegmentForward(int iSeg);
    void renderSegmentReversed(int iSeg);
    void CalcSegmentPositions();
    void StepFromTime();
    const MillPathSegment* SegmentAtTime(float t) const;
    void AdvanceTime(float seconds);
    void ComputeTimes();
    bool HasAxisAngles(const MillPathSegment* p) const;
    std::vector<float> MotionAngles(const MillMotion& m) const;
    void PartPos(vec3 out, const MillMotion& m, const std::vector<float>& angles) const;
    void MarkClearRapids();
    int AddContinuousSegments(
        const EndMill& tool,
        const MillMotion& from,
        const MillMotion& to,
        const std::vector<float>& angFrom,
        const std::vector<float>& angTo,
        int index,
        int segId
    );
    bool UsesAxisAngles(const MillPathSegment* p) const;
    float IndexAngles(const MillPathSegment* p, float s, std::vector<float>* angles) const;
    float IndexSchedule(const MillPathSegment* p, std::vector<float>& begin, std::vector<float>& span) const;
    void PoseFromAngles(quat pose, const std::vector<float>& angles) const;
    void HeadFromAngles(quat tilt, const std::vector<float>& angles) const;
    void AxesRotation(quat rot, const std::vector<float>& angles, bool head) const;
    float TimeOfStep(int step) const;
    void GetScenePose(quat pose);
    void GetFramePose(quat pose, const MillFrame& frame) const;
    void UpdateScene();
    EndMill* GetTool(int tool);
    void RemoveTool(int toolId);

protected:
    bool simulationInitiated = false;

    // protected:
public:
    std::vector<EndMill*> mToolTable;
    GCodeParser mCodeParser;
    SimDisplay simDisplay;
    MillPathLine millPathLine;
    std::vector<MillPathSegment*> MillPathSegments;
    std::vector<char> mOpTurns;    // for each operation, whether it turns the rotaries as it cuts
    std::vector<float> mOpStarts;  // when each operation starts, as a share of the program's time
    std::vector<SimRotaryAxis> mRotaryAxes;
    std::vector<Point3D> mStockPoints;  // the stock's vertices, for how far it reaches from an axis

    // the stock as dexels: set up from the stock's mesh, cut up to this step
    DexelStock mDexel;
    AxisOverlay mAxisOverlay;
    float mPixelRatio = 1;
    bool mToolShown = false;  // where the tool was last drawn, on the part, and its tilt
    vec3 mToolPos = {0, 0, 0};
    mat4x4 mToolRot = {{1, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, 1, 0}, {0, 0, 0, 1}};
    bool mDexelTried = false;
    bool mDexelBehind = false;
    int mDexelFramesBehind = 0;
    std::vector<std::pair<int, int>> mDexelSnaps;  // the segment each snapshot is before, its id
    int mDexelSeg = 0;
    int mDexelSub = 0;
    float mQuality = 10;
    std::vector<Vertex> mStockVerts;
    std::vector<GLushort> mStockIndices;

    // what the cache holds: the cut stock drawn up to this step, in this view
    bool mCacheValid = false;
    int mCachedPathStep = -1;
    int mCachedSubStep = 0;
    unsigned int mCachedViewVersion = 0;
    int mCachedViewItems = 0;
    std::vector<SimTimeSpan> mIndexSpans;  // when the rotaries turn
    std::vector<float> mMarks;             // seconds the skip button stops at, in order
    clock::time_point mHoldUntil;          // playback waits here after a back skip

    int mWidth = -1;
    int mHeight = -1;

    StockObject mStockObject;
    SolidObject mBaseShape;

    vec3 bgndColor = {0.1f, 0.2f, 0.3f};
    vec3 stockColor = {0.5f, 0.55f, 0.9f};
    vec3 cutColor = {0.5f, 0.84f, 0.73f};
    vec3 toolColor = {0.5f, 0.4f, 0.3f};
    vec3 baseShapeColor = {0.7f, 0.6f, 0.5f};
};

}  // namespace CAMSimulator
