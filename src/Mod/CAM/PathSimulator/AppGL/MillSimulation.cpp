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

#include "MillSimulation.h"

#include "GlUtils.h"
#include <algorithm>
#include <iostream>
#include <numbers>

// include this last as the defines can mess up other includes
#include "OpenGlWrapper.h"

#define DRAG_ZOOM_FACTOR 10

namespace CAMSimulator
{

MillSimulation::MillSimulation()
{}

MillSimulation::~MillSimulation()
{
    Clear();
}

void MillSimulation::ClearMillPathSegments()
{
    for (unsigned int i = 0; i < MillPathSegments.size(); i++) {
        delete MillPathSegments[i];
    }
    MillPathSegments.clear();
}

void MillSimulation::Clear()
{
    mCodeParser.Clear();

    ClearMillPathSegments();
    mOpStarts.clear();

    for (unsigned int i = 0; i < mToolTable.size(); i++) {
        delete mToolTable[i];
    }
    mToolTable.clear();

    mStockObject.Clear();
    simDisplay.CleanGL();

    mCurStep = 0;
    mPathStep = -1;
    mNTotalSteps = 0;

    simulationInitiated = false;
}

void MillSimulation::InitSimulation(float quality, float maxStockDimension)
{
    ClearMillPathSegments();
    mOpStarts.clear();
    millPathLine.Clear();
    // mViewSSAO = guiDisplay.IsChecked(eGuiItemAmbientOclusion);

    // gDestPos = curMillOperation->startPos;
    mCurStep = 0;
    mPathStep = -1;
    mNTotalSteps = 0;
    mSimPlaying = false;
    mSimSpeed = 10;
    mSimTime = 0;
    mTotalTime = 0;

    MillPathSegment::SetQuality(quality, maxStockDimension);

    int nOperations = (int)mCodeParser.Operations.size();
    int segId = 0;

    MillMotion prevMotion = !mCodeParser.Operations.empty() ? mCodeParser.Operations.front()
                                                            : MillMotion();

    const std::vector<MillFrame>& frames = mCodeParser.Frames;

    vec3 startPos;
    FramePosToWorld(startPos, frames[prevMotion.frame].mat, prevMotion.x, prevMotion.y, prevMotion.z);
    MillPathPosition mpPos;
    mpPos.X = startPos[0];
    mpPos.Y = startPos[1];
    mpPos.Z = startPos[2];
    mpPos.SegmentId = segId++;
    millPathLine.MillPathPointsBuffer.push_back(mpPos);

    for (int i = 1; i < nOperations; i++) {
        const MillMotion curMotion = mCodeParser.Operations[i];
        const EndMill* tool = GetTool(curMotion.tool);
        if (tool != nullptr) {
            // a move into another work plane frame starts where the last one ended, in the
            // world, and is drawn in the new frame. If it changes the tool axis the machine
            // indexes its rotary axes, which a straight sweep does not show: it cuts nothing.
            MillMotion fromMotion = prevMotion;
            bool isCutting = true;
            if (fromMotion.frame != curMotion.frame) {
                isCutting
                    = FramesShareToolAxis(frames[fromMotion.frame].mat, frames[curMotion.frame].mat);
                MotionToFrame(fromMotion, frames, curMotion.frame);
            }
            auto segment
                = new MillPathSegment(*tool, fromMotion, curMotion, frames[curMotion.frame].mat);
            segment->isCutting = isCutting;
            segment->frameFrom = prevMotion.frame;
            segment->frameTo = curMotion.frame;
            // How far the table turns: the angle between the poses, and each axis's travel when
            // the positions are known. Give it time to be seen: a step every 1.5 degrees.
            float turn = 0;
            float axisTurn = 0;
            if (prevMotion.frame != curMotion.frame) {
                turn = QuatAngle(frames[prevMotion.frame].pose, frames[curMotion.frame].pose)
                    * 180.f / std::numbers::pi_v<float>;
            }
            if (HasAxisAngles(segment)) {
                const MillFrame& a = frames[prevMotion.frame];
                const MillFrame& b = frames[curMotion.frame];
                for (size_t k = 0; k < a.angles.size(); k++) {
                    axisTurn += std::fabs(b.angles[k] - a.angles[k]);
                }
            }
            segment->SetMinSimSteps((int)(std::max(turn, axisTurn) / 1.5f));

            segment->op = curMotion.op;
            segment->turn = turn;
            segment->axisTurn = axisTurn;
            segment->feed = curMotion.feed;
            segment->isRapid = curMotion.rapid;
            segment->firstStep = mNTotalSteps;
            segment->indexInArray = i;
            segment->segmentIndex = segId++;
            mNTotalSteps += segment->numSimSteps;
            MillPathSegments.push_back(segment);
            segment->AppendPathPoints(millPathLine.MillPathPointsBuffer);
        }

        prevMotion = curMotion;
    }

    assert(mNTotalSteps >= 0);

    ComputeTimes();

    mNPathSteps = (int)MillPathSegments.size();
    millPathLine.GenerateModel();

    InitDisplay(quality);

    simulationInitiated = true;
}

EndMill* MillSimulation::GetTool(int toolId)
{
    for (unsigned int i = 0; i < mToolTable.size(); i++) {
        if (mToolTable[i]->toolId == toolId) {
            return mToolTable[i];
        }
    }
    return nullptr;
}

void MillSimulation::RemoveTool(const int toolId)
{
    EndMill* tool = GetTool(toolId);
    if (tool == nullptr) {
        return;
    }

    if (const auto it = std::ranges::find(mToolTable, tool); it != mToolTable.end()) {
        mToolTable.erase(it);
    }
    delete tool;
}


void MillSimulation::AddTool(EndMill* tool)
{
    // if we have another tool with same id, remove it
    RemoveTool(tool->toolId);
    mToolTable.push_back(tool);
}

void MillSimulation::AddTool(const std::vector<float>& toolProfile, int toolid, float diameter)
{
    // if we have another tool with same id, remove it
    RemoveTool(toolid);
    EndMill* tool = new EndMill(toolProfile, toolid, diameter);
    mToolTable.push_back(tool);
}

bool MillSimulation::ToolExists(int toolid)
{
    return GetTool(toolid) != nullptr;
}

void MillSimulation::GlsimStart()
{
    glDisable(GL_BLEND);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
    glEnable(GL_STENCIL_TEST);
}

void MillSimulation::GlsimToolStep1(void)
{
    glCullFace(GL_BACK);
    glDepthFunc(GL_LESS);
    glDepthMask(GL_FALSE);
    glStencilFunc(GL_ALWAYS, 1, 0xFF);
    glStencilOp(GL_ZERO, GL_ZERO, GL_REPLACE);
}

void MillSimulation::GlsimToolStep2(void)
{
    glCullFace(GL_FRONT);
    glDepthFunc(GL_GREATER);
    glDepthMask(GL_TRUE);
    glStencilFunc(GL_EQUAL, 1, 0xFF);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
}

void MillSimulation::GlsimClipBack(void)
{
    glCullFace(GL_FRONT);
    glDepthFunc(GL_LESS);
    glDepthMask(GL_FALSE);
    glStencilFunc(GL_ALWAYS, 1, 0xFF);
    glStencilOp(GL_REPLACE, GL_REPLACE, GL_ZERO);
}

void MillSimulation::GlsimRenderStock(void)
{
    glCullFace(GL_BACK);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthFunc(GL_EQUAL);
    glEnable(GL_STENCIL_TEST);
    glStencilFunc(GL_EQUAL, 1, 0xFF);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
}

void MillSimulation::GlsimRenderTools(void)
{
    glCullFace(GL_FRONT);
}

void MillSimulation::GlsimEnd(void)
{
    glCullFace(GL_BACK);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);

    glDepthFunc(GL_LESS);
    glDepthMask(GL_TRUE);

    glDisable(GL_STENCIL_TEST);
    glStencilFunc(GL_ALWAYS, 1, 0xFF);
}

void MillSimulation::renderSegmentForward(int iSeg)
{
    MillPathSegment* p = MillPathSegments.at(iSeg);
    if (!p->isCutting) {
        return;
    }
    int step = iSeg == mPathStep ? mSubStep : p->numSimSteps;
    int start = p->isMultyPart ? 1 : step;
    for (int i = start; i <= step; i++) {
        GlsimToolStep1();
        p->render(i);
        GlsimToolStep2();
        p->render(i);
    }
}

void MillSimulation::renderSegmentReversed(int iSeg)
{
    MillPathSegment* p = MillPathSegments.at(iSeg);
    if (!p->isCutting) {
        return;
    }
    int step = iSeg == mPathStep ? mSubStep : p->numSimSteps;
    int end = p->isMultyPart ? 1 : step;
    for (int i = step; i >= end; i--) {
        GlsimToolStep1();
        p->render(i);
        GlsimToolStep2();
        p->render(i);
    }
}

void MillSimulation::ComputeTimes()
{
    // The machine's time over each segment: its length at its feed, as the cycle time estimate
    // counts it. A move with no feed known keeps the old pace, 60 steps a second. An index takes
    // at least as long as the rotaries take to turn.
    const std::vector<MillFrame>& frames = mCodeParser.Frames;
    mTotalTime = 0;
    for (MillPathSegment* p : MillPathSegments) {
        float duration = p->feed > 0 ? p->Length() / p->feed : (float)p->numSimSteps / 60.f;
        p->rotaryTime = 0;
        if (UsesAxisAngles(p)) {
            p->rotaryTime = IndexAngles(p, 0, nullptr);
        }
        else if (p->turn > 0 && frames[p->frameTo].indexRate > 0) {
            p->rotaryTime = p->turn / frames[p->frameTo].indexRate;
        }
        p->duration = std::max(duration, p->rotaryTime);
        p->startTime = mTotalTime;
        mTotalTime += p->duration;
    }

    // the time each operation's first move starts, and when the rotaries turn: axis by axis,
    // or the table as a whole. The skip button stops at each.
    mOpStarts.clear();
    mIndexSpans.clear();
    mMarks.clear();
    const float total = mTotalTime > 0 ? mTotalTime : 1.f;
    int op = -1;
    for (const MillPathSegment* p : MillPathSegments) {
        if (p->op != op) {
            op = p->op;
            mOpStarts.push_back(p->startTime / total);
            mMarks.push_back(p->startTime);
        }
        if (p->rotaryTime <= 0) {
            continue;
        }
        if (UsesAxisAngles(p)) {
            const std::vector<float>& a = frames[p->frameFrom].angles;
            const std::vector<float>& b = frames[p->frameTo].angles;
            std::vector<float> begin, span;
            IndexSchedule(p, begin, span);
            for (size_t k = 0; k < a.size(); k++) {
                if (std::fabs(b[k] - a[k]) > 1e-4f && span[k] > 0) {
                    const float t0 = p->startTime + begin[k];
                    const float t1 = t0 + span[k];
                    mIndexSpans.push_back({t0 / total, t1 / total, (int)k});
                    mMarks.push_back(t0);
                    mMarks.push_back(t1);
                }
            }
        }
        else {
            const float t1 = p->startTime + p->rotaryTime;
            mIndexSpans.push_back({p->startTime / total, t1 / total, -1});
            mMarks.push_back(p->startTime);
            mMarks.push_back(t1);
        }
    }
    std::sort(mMarks.begin(), mMarks.end());
}

const std::vector<SimTimeSpan>& MillSimulation::GetIndexSpans() const
{
    return mIndexSpans;
}

const std::vector<SimRotaryAxis>& MillSimulation::GetRotaryAxes() const
{
    return mRotaryAxes;
}

bool MillSimulation::GetIndexAngles(std::vector<float>& angles) const
{
    // the rotaries' positions while they turn, axis by axis
    if (mPathStep < 0 || mPathStep >= (int)MillPathSegments.size()) {
        return false;
    }
    const MillPathSegment* p = MillPathSegments[mPathStep];
    if (!UsesAxisAngles(p) || p->rotaryTime <= 0) {
        return false;
    }
    const float t = std::clamp((float)mSubStep / (float)p->numSimSteps, 0.f, 1.f);
    IndexAngles(p, t * p->duration, &angles);
    return true;
}

bool MillSimulation::UsesAxisAngles(const MillPathSegment* p) const
{
    // the turn goes axis by axis, unless the shortest rotation is asked for
    return mIndexMode != IndexShortest && HasAxisAngles(p);
}

bool MillSimulation::HasAxisAngles(const MillPathSegment* p) const
{
    // a move between frames whose rotary positions are both known
    const std::vector<MillFrame>& frames = mCodeParser.Frames;
    return p->frameFrom != p->frameTo && !mRotaryAxes.empty()
        && frames[p->frameFrom].angles.size() == mRotaryAxes.size()
        && frames[p->frameTo].angles.size() == mRotaryAxes.size();
}

float MillSimulation::IndexSchedule(
    const MillPathSegment* p,
    std::vector<float>& begin,
    std::vector<float>& span
) const
{
    // The rotaries turn from one frame's positions to the next. Axes of one sequence move
    // together and finish together, at the pace of the slowest; the sequences follow one
    // another, lowest first, or all axes move at once when the index mode says together.
    // begin and span get each axis's start and length in seconds into the turn; returns the
    // time the whole turn takes.
    const std::vector<float>& a = mCodeParser.Frames[p->frameFrom].angles;
    const std::vector<float>& b = mCodeParser.Frames[p->frameTo].angles;
    const size_t n = mRotaryAxes.size();
    std::vector<int> sequences;
    for (const SimRotaryAxis& axis : mRotaryAxes) {
        sequences.push_back(mIndexMode == IndexSequenced ? axis.sequence : 0);
    }
    std::vector<int> order = sequences;
    std::sort(order.begin(), order.end());
    order.erase(std::unique(order.begin(), order.end()), order.end());

    begin.assign(n, 0.f);
    span.assign(n, 0.f);
    float start = 0;
    for (int seq : order) {
        float group = 0;
        for (size_t k = 0; k < n; k++) {
            if (sequences[k] == seq && mRotaryAxes[k].rate > 0) {
                group = std::max(group, std::fabs(b[k] - a[k]) / mRotaryAxes[k].rate);
            }
        }
        for (size_t k = 0; k < n; k++) {
            if (sequences[k] == seq) {
                begin[k] = start;
                span[k] = group;
            }
        }
        start += group;
    }
    return start;
}

float MillSimulation::IndexAngles(const MillPathSegment* p, float s, std::vector<float>* angles) const
{
    // the time the turn takes; angles, when given, gets the positions s seconds into it
    std::vector<float> begin, span;
    const float total = IndexSchedule(p, begin, span);
    if (angles) {
        const std::vector<float>& a = mCodeParser.Frames[p->frameFrom].angles;
        const std::vector<float>& b = mCodeParser.Frames[p->frameTo].angles;
        *angles = a;
        for (size_t k = 0; k < a.size(); k++) {
            const float frac = span[k] > 0 ? std::clamp((s - begin[k]) / span[k], 0.f, 1.f)
                                           : (s >= begin[k] ? 1.f : 0.f);
            (*angles)[k] = a[k] + (b[k] - a[k]) * frac;
        }
    }
    return total;
}

void MillSimulation::PoseFromAngles(quat pose, const std::vector<float>& angles) const
{
    // the table's rotations, the first axis's applied first, as the post composes them
    quat_identity(pose);
    for (size_t k = 0; k < mRotaryAxes.size() && k < angles.size(); k++) {
        quat r, total;
        quat_rotate(r, angles[k] * std::numbers::pi_v<float> / 180.f, mRotaryAxes[k].axis);
        quat_mul(total, r, pose);
        vec4_dup(pose, total);
    }
}

void MillSimulation::SetRotaryAxes(const std::vector<SimRotaryAxis>& axes)
{
    mRotaryAxes = axes;
}

void MillSimulation::SetIndexMode(int mode)
{
    if (mode == mIndexMode || mode < 0 || mode >= IndexModeCount) {
        return;
    }
    mIndexMode = mode;
    // the turns take another time: keep the step and find its time again
    ComputeTimes();
    mSimTime = TimeOfStep(mCurStep);
    simDisplay.updateDisplay = true;
}

const MillPathSegment* MillSimulation::SegmentAtTime(float t) const
{
    // the segment running at time t: the last one to start by then
    auto it = std::upper_bound(
        MillPathSegments.begin(),
        MillPathSegments.end(),
        t,
        [](float time, const MillPathSegment* p) { return time < p->startTime; }
    );
    return *(it == MillPathSegments.begin() ? it : it - 1);
}

// The fastest a table turn plays, in degrees per second of real time. The machine's own turn is
// often over in a fraction of a second, which no simulation speed would let anyone see.
constexpr float MaxShownTurnRate = 90.f;

void MillSimulation::AdvanceTime(float seconds)
{
    // The program runs on the machine's clock, sped up by the simulation speed, except that a
    // table turn slows down to be seen. The machine's time stays what it is.
    for (int guard = 0; seconds > 0 && mSimTime < mTotalTime && guard < 100000; guard++) {
        const MillPathSegment* p = SegmentAtTime(mSimTime);
        float rate = (float)mSimSpeed;
        const float shown = UsesAxisAngles(p) ? p->axisTurn : p->turn;
        if (shown > 0 && p->duration > 0) {
            rate = std::min(rate, p->duration * MaxShownTurnRate / shown);
        }
        const float end = p->startTime + p->duration;
        const float needed = (end - mSimTime) / rate;  // real seconds to finish the segment
        if (needed > seconds) {
            mSimTime += seconds * rate;
            return;
        }
        mSimTime = end;
        seconds -= needed;
        if (p == MillPathSegments.back()) {
            break;
        }
        if (p->duration <= 0) {
            // step over a segment that takes no time, which the lookup would find again
            mSimTime = std::nextafter(mSimTime, mTotalTime);
        }
    }
    mSimTime = std::min(mSimTime, mTotalTime);
}

void MillSimulation::StepFromTime()
{
    // the step drawn at the current time: the segment running then, and how far along it is
    if (MillPathSegments.empty() || mSimTime >= mTotalTime) {
        mCurStep = mNTotalSteps;
        return;
    }
    const MillPathSegment* p = SegmentAtTime(mSimTime);
    const float frac = p->duration > 0 ? (mSimTime - p->startTime) / p->duration : 1.f;
    const int sub = std::clamp((int)(frac * (float)p->numSimSteps), 0, p->numSimSteps - 1);
    mCurStep = p->firstStep + sub;
}

float MillSimulation::TimeOfStep(int step) const
{
    if (MillPathSegments.empty() || step >= mNTotalSteps) {
        return mTotalTime;
    }
    auto it = std::upper_bound(
        MillPathSegments.begin(),
        MillPathSegments.end(),
        step,
        [](int s, const MillPathSegment* p) { return s < p->firstStep; }
    );
    const MillPathSegment* p = *(it == MillPathSegments.begin() ? it : it - 1);
    return p->startTime + p->duration * (float)(step - p->firstStep) / (float)p->numSimSteps;
}

void MillSimulation::CalcSegmentPositions()
{
    mSubStep = mCurStep;
    for (mPathStep = 0; mPathStep < mNPathSteps; mPathStep++) {
        MillPathSegment* p = MillPathSegments[mPathStep];
        if (mSubStep < p->numSimSteps) {
            break;
        }
        mSubStep -= p->numSimSteps;
    }
    if (mPathStep >= mNPathSteps) {
        mPathStep = mNPathSteps - 1;
        mSubStep = MillPathSegments[mPathStep]->numSimSteps;
    }
    else {
        mSubStep++;
    }
    if (mPathStep >= 0) {
        mCurFeed = MillPathSegments[mPathStep]->feed;
        mCurRapid = MillPathSegments[mPathStep]->isRapid;
    }
}

void MillSimulation::GetFramePose(quat pose, const MillFrame& frame) const
{
    // with the table pose off the part stays put and the tool tilts instead
    if (mViewTablePose) {
        vec4_dup(pose, frame.pose);
    }
    else {
        quat_identity(pose);
    }
}

void MillSimulation::GetScenePose(quat pose)
{
    quat_identity(pose);
    if (MillPathSegments.empty()) {
        return;
    }
    const std::vector<MillFrame>& frames = mCodeParser.Frames;
    if (mPathStep < 0) {
        GetFramePose(pose, frames[MillPathSegments[0]->frameFrom]);
        return;
    }
    // the table turns over a move between frames, and holds its pose otherwise
    const MillPathSegment* p = MillPathSegments.at(mPathStep);
    const float t = std::clamp((float)mSubStep / (float)p->numSimSteps, 0.f, 1.f);
    if (mViewTablePose && UsesAxisAngles(p)) {
        // axis by axis, as the machine turns
        std::vector<float> angles;
        IndexAngles(p, t * p->duration, &angles);
        PoseFromAngles(pose, angles);
        return;
    }
    quat from, to;
    GetFramePose(from, frames[p->frameFrom]);
    GetFramePose(to, frames[p->frameTo]);
    QuatSlerp(pose, from, to, t);
}

void MillSimulation::UpdateScene()
{
    // the scene turns with the table, about the middle of the stock so it stays in view
    quat pose;
    GetScenePose(pose);
    const vec3& c = mStockObject.center;
    mat4x4 scene, rot;
    mat4x4_from_quat(rot, pose);
    mat4x4_translate(scene, c[0], c[1], c[2]);
    mat4x4_mul(scene, scene, rot);
    mat4x4_translate_in_place(scene, -c[0], -c[1], -c[2]);
    simDisplay.SetSceneMatrix(scene);
}

void MillSimulation::RenderSimulation()
{
    if ((mViewItems & VIEWITEM_SIMULATION) == 0) {
        return;
    }

    simDisplay.StartDepthPass();

    GlsimStart();
    mStockObject.render();

    GlsimToolStep2();

    for (int i = 0; i <= mPathStep; i++) {
        renderSegmentForward(i);
    }

    for (int i = mPathStep; i >= 0; i--) {
        renderSegmentForward(i);
    }

    for (int i = 0; i < mPathStep; i++) {
        renderSegmentReversed(i);
    }

    for (int i = mPathStep; i >= 0; i--) {
        renderSegmentReversed(i);
    }

    GlsimClipBack();
    mStockObject.render();

    // start coloring
    simDisplay.StartGeometryPass(stockColor, false);
    GlsimRenderStock();
    mStockObject.render();

    // render cuts (back faces of tools)
    simDisplay.StartGeometryPass(cutColor, true);
    GlsimRenderTools();
    for (int i = 0; i <= mPathStep; i++) {
        MillPathSegment* p = MillPathSegments.at(i);
        if (!p->isCutting) {
            continue;
        }
        int step = (i == mPathStep) ? mSubStep : p->numSimSteps;
        int start = p->isMultyPart ? 1 : step;
        for (int j = start; j <= step; j++) {
            MillPathSegments.at(i)->render(j);
        }
    }

    GlsimEnd();
}

void MillSimulation::RenderTool()
{
    if (mPathStep < 0) {
        return;
    }

    MillPathSegment* p = MillPathSegments.at(mPathStep);
    vec3 toolPos;
    p->GetHeadPosition(toolPos);
    mat4x4 tmat, rmat;
    p->GetToolRotation(rmat);
    if (p->frameFrom != p->frameTo && !p->isCutting) {
        // While the table turns, the tool turns from its orientation in the old frame to the
        // one in the new, as seen on the machine; the scene's pose takes back the table's part.
        const std::vector<MillFrame>& frames = mCodeParser.Frames;
        const MillFrame& from = frames[p->frameFrom];
        const MillFrame& to = frames[p->frameTo];
        quat poseFrom, poseTo, seenFrom, seenTo, seen, pose, unposed;
        GetFramePose(poseFrom, from);
        GetFramePose(poseTo, to);
        quat_mul(seenFrom, poseFrom, from.rot);
        quat_mul(seenTo, poseTo, to.rot);
        const float t = std::clamp((float)mSubStep / (float)p->numSimSteps, 0.f, 1.f);
        QuatSlerp(seen, seenFrom, seenTo, t);
        GetScenePose(pose);
        quat_conj(pose, pose);
        quat_mul(unposed, pose, seen);
        mat4x4_from_quat(rmat, unposed);
    }
    mat4x4_translate(tmat, toolPos[0], toolPos[1], toolPos[2]);
    mat4x4_mul(tmat, tmat, rmat);
    // mat4x4_translate(tmat, toolPos.x, toolPos.y, toolPos.z);
    simDisplay.StartGeometryPass(toolColor, false);
    p->endmill->toolShape.Render(tmat, rmat);
}

void MillSimulation::RenderPath()
{
    if (!mViewPath) {
        return;
    }
    simDisplay.SetupLinePathPass(mPathStep, false);
    millPathLine.Render();
    simDisplay.SetupLinePathPass(mPathStep, true);
    millPathLine.Render();
    glDepthMask(GL_TRUE);
}

void MillSimulation::RenderBaseShape()
{
    if ((mViewItems & VIEWITEM_BASE_SHAPE) == 0) {
        return;
    }
    simDisplay.StartDepthPass();
    glPolygonOffset(0, -2);
    glEnable(GL_POLYGON_OFFSET_FILL);
    simDisplay.StartGeometryPass(baseShapeColor, false);
    mBaseShape.render();
    glDisable(GL_POLYGON_OFFSET_FILL);
}

void MillSimulation::Render()
{
    if (!simulationInitiated) {
        return;
    }

    // set background
    glClearColor(bgndColor[0], bgndColor[1], bgndColor[2], 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);

    // render the simulation offscreen in an FBO

    if (simDisplay.updateDisplay) {
        UpdateScene();
        simDisplay.PrepareFrameBuffer();
        RenderSimulation();
        RenderTool();
        RenderBaseShape();
        RenderPath();
        simDisplay.updateDisplay = false;
        simDisplay.RenderResult(true, mViewSSAO);
    }
    else {
        simDisplay.RenderResult(false, mViewSSAO);
    }

    /*   if (mDebug > 0) {
           mat4x4 test;
           mat4x4_identity(test);
           mat4x4_translate_in_place(test, 20, 20, 3);
           mat4x4_rotate_Z(test, test, 30.f * 3.14f / 180.f);
           int dpos = mNPathSteps - mDebug2;
           MillPathSegment* p = MillPathSegments.at(dpos);
           if (mDebug > p->numSimSteps) {
               mDebug = 1;
           }
           p->render(mDebug);
       }*/

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void MillSimulation::ProcessSim(const clock::duration& elapsed)
{
    SimNext(elapsed);
    Render();
}

void MillSimulation::SimNext(const clock::duration& elapsed)
{
    // calculate number of steps based on elapsed time

    const int oldStep = mCurStep;

    if (mSimPlaying) {
        if (clock::now() < mHoldUntil) {
            return;  // holding after a back skip
        }
        const float seconds = std::chrono::duration_cast<std::chrono::duration<float>>(elapsed).count();
        if (!MillPathSegments.empty()) {
            AdvanceTime(seconds);
        }
        StepFromTime();
    }
    else if (mSingleStep) {
        mCurStep = std::min(mCurStep + 1, mNTotalSteps);
        mSimTime = TimeOfStep(mCurStep);
        mSingleStep = false;
    }
    else {
        return;
    }

    if (mCurStep == mNTotalSteps) {
        mSimPlaying = false;
    }

    if (mCurStep != oldStep) {
        CalcSegmentPositions();
        simDisplay.updateDisplay = true;
    }
}

void MillSimulation::InitDisplay(float quality)
{
    // generate tools
    for (unsigned int i = 0; i < mToolTable.size(); i++) {
        mToolTable[i]->GenerateDisplayLists(quality);
    }

    // Make sure the next call to UpdateWindowScale will not return early.
    mWidth = -1;
    mHeight = -1;

    // init 3d display
    simDisplay.InitGL();
}

void MillSimulation::SetBoxStock(float x, float y, float z, float l, float w, float h)
{
    mStockObject.GenerateBoxStock(x, y, z, l, w, h);
    simDisplay.ScaleViewToStock(&mStockObject);
}

void MillSimulation::SetArbitraryStock(
    const std::vector<Vertex>& verts,
    const std::vector<GLushort>& indices
)
{
    mStockObject.GenerateSolid(verts, indices);
    simDisplay.ScaleViewToStock(&mStockObject);
}

void MillSimulation::SetStockVisible(bool b)
{
    if (b == IsStockVisible()) {
        return;
    }

    mViewItems ^= VIEWITEM_SIMULATION;
    simDisplay.updateDisplay = true;
}

bool MillSimulation::IsStockVisible() const
{
    return mViewItems & VIEWITEM_SIMULATION;
}

void MillSimulation::SetBaseObject(const std::vector<Vertex>& verts, const std::vector<GLushort>& indices)
{
    mBaseShape.GenerateSolid(verts, indices);
}

void MillSimulation::SetBaseVisible(bool b)
{
    if (b == IsBaseVisible()) {
        return;
    }

    mViewItems ^= VIEWITEM_BASE_SHAPE;
    simDisplay.updateDisplay = true;
}

bool MillSimulation::IsBaseVisible() const
{
    return mViewItems & VIEWITEM_BASE_SHAPE;
}

void MillSimulation::UpdateWindowScale(int width, int height)
{
    if (width == mWidth && height == mHeight) {
        return;
    }

    mWidth = width;
    mHeight = height;

    simDisplay.UpdateWindowScale(width, height);
}

void MillSimulation::SetPathVisible(bool b)
{
    if (b == mViewPath) {
        return;
    }

    mViewPath = b;
    simDisplay.updateDisplay = true;
}

void MillSimulation::EnableSsao(bool b)
{
    if (b == mViewSSAO) {
        return;
    }

    mViewSSAO = b;
    simDisplay.updateDisplay = true;
}

void MillSimulation::EnableTablePose(bool b)
{
    if (b == mViewTablePose) {
        return;
    }

    mViewTablePose = b;
    simDisplay.updateDisplay = true;
}

void MillSimulation::UpdateCamera(const SoCamera& camera)
{
    simDisplay.UpdateCamera(camera);
}

bool MillSimulation::LoadGCodeFile(const char* fileName)
{
    if (mCodeParser.Parse(fileName)) {
        std::cout << "GCode file loaded successfully" << std::endl;
        return true;
    }
    return false;
}

bool MillSimulation::AddGcodeLine(const char* line)
{
    return mCodeParser.AddLine(line);
}

void MillSimulation::SetFrame(const MillFrame& frame)
{
    mCodeParser.SetFrame(frame);
}

void MillSimulation::BeginOperation(const std::string& name)
{
    mCodeParser.BeginOperation(name);
}

const std::vector<float>& MillSimulation::GetOperationStarts() const
{
    return mOpStarts;
}

std::string MillSimulation::GetCurrentOperation() const
{
    if (mPathStep < 0 || mPathStep >= (int)MillPathSegments.size()) {
        return {};
    }
    const int op = MillPathSegments[mPathStep]->op;
    if (op < 0 || op >= (int)mCodeParser.OpNames.size()) {
        return {};
    }
    return mCodeParser.OpNames[op];
}

void MillSimulation::SkipToPreviousMark()
{
    // Back to the start of what is running, or, from there, to the mark before. While playing,
    // playback holds at the mark for a moment, so another press finds it there and goes further
    // back, and carries on once the presses stop.
    if (mSimPlaying) {
        mHoldUntil = clock::now() + std::chrono::milliseconds(750);
    }
    auto it = std::lower_bound(mMarks.begin(), mMarks.end(), mSimTime - 1e-4f);
    const float previous = it == mMarks.begin() ? 0.f : *(it - 1);
    if (previous == mSimTime) {
        return;
    }
    mSimTime = previous;
    StepFromTime();
    CalcSegmentPositions();
    simDisplay.updateDisplay = true;
}

void MillSimulation::SkipToNextMark()
{
    // to the next operation's start, or a rotary axis starting or stopping, whichever comes
    // first; to the end of the program after the last
    auto it = std::upper_bound(mMarks.begin(), mMarks.end(), mSimTime + 1e-4f);
    const float next = it == mMarks.end() ? mTotalTime : *it;
    if (next == mSimTime) {
        return;
    }
    mSimTime = next;
    StepFromTime();
    CalcSegmentPositions();
    simDisplay.updateDisplay = true;
}

void MillSimulation::SetPlaying(bool b)
{
    if (b == mSimPlaying) {
        return;
    }

    mSimPlaying = b;
    simDisplay.updateDisplay = true;
}

void MillSimulation::SingleStep()
{
    if (!mSimPlaying && mSingleStep) {
        return;
    }

    mSimPlaying = false;
    mSingleStep = true;
    simDisplay.updateDisplay = true;
}

void MillSimulation::SetSpeed(int s)
{
    mSimSpeed = s;
}

void MillSimulation::SetSimulationStage(float stage)
{
    // the stage is a share of the program's time
    mSimTime = std::clamp(stage, 0.f, 1.f) * mTotalTime;
    const int oldStep = mCurStep;
    StepFromTime();
    if (mCurStep == oldStep) {
        return;
    }

    CalcSegmentPositions();

    simDisplay.updateDisplay = true;
}

void MillSimulation::SetState(const MillSimulationState& state)
{
    SetPlaying(state.mSimPlaying);
    if (state.mSingleStep) {
        SingleStep();
    }

    const float stage = state.mTotalTime > 0 ? state.mSimTime / state.mTotalTime : 0.f;
    SetSimulationStage(stage);

    SetSpeed(state.mSimSpeed);

    mViewItems = state.mViewItems;
    mViewPath = state.mViewPath;
    mViewSSAO = state.mViewSSAO;
    mViewTablePose = state.mViewTablePose;
    SetIndexMode(state.mIndexMode);
}

const MillSimulationState& MillSimulation::GetState() const
{
    return *this;
}

void MillSimulation::SetBackgroundColor(const vec3& c)
{
    bgndColor[0] = c[0];
    bgndColor[1] = c[1];
    bgndColor[2] = c[2];
}

void MillSimulation::SetPathColor(const vec3& normal, const vec3& rapid)
{
    simDisplay.SetPathColor(normal, rapid);
}


}  // namespace CAMSimulator
