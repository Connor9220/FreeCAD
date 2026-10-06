// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 The FreeCAD project association AISBL              *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#include "DexelAuto.h"
#include "DexelStock.h"
#include "EndMill.h"
#include "MillPathSegment.h"

#include <App/Application.h>
#include <Base/Console.h>
#include <QDate>
#include <QOpenGLContext>
#include <QSysInfo>

#include <chrono>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#if defined(Q_OS_MACOS)
# include <sys/sysctl.h>
#elif defined(Q_OS_WIN)
# include <QSettings>
#endif

// include this last as the defines can mess up other includes
#include "OpenGlWrapper.h"

// the graphics card's free memory, where it says: NVIDIA's and AMD's
#ifndef GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX
# define GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX 0x9049
#endif
#ifndef GL_TEXTURE_FREE_MEMORY_ATI
# define GL_TEXTURE_FREE_MEMORY_ATI 0x87FC
#endif

namespace CAMSimulator
{

namespace
{

constexpr const char* PrefPath = "User parameter:BaseApp/Preferences/Mod/CAM";

// what one side, the processor or the card, takes for a cut, seconds, and for each mm² its tool
// sweeps; not usable when it could not be set up
struct Speed
{
    bool usable = false;
    double perCut = 0;
    double perArea = 0;
};

std::string processorName()
{
#if defined(Q_OS_LINUX)
    std::ifstream info("/proc/cpuinfo");
    std::string line;
    while (std::getline(info, line)) {
        if (line.rfind("model name", 0) == 0) {
            const auto colon = line.find(':');
            return colon == std::string::npos ? line : line.substr(colon + 2);
        }
    }
#elif defined(Q_OS_MACOS)
    char name[256] = {};
    size_t size = sizeof(name);
    if (sysctlbyname("machdep.cpu.brand_string", name, &size, nullptr, 0) == 0) {
        return name;
    }
#elif defined(Q_OS_WIN)
    QSettings cpu(
        QStringLiteral("HKEY_LOCAL_MACHINE\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0"),
        QSettings::NativeFormat
    );
    return cpu.value(QStringLiteral("ProcessorNameString")).toString().toStdString();
#endif
    return QSysInfo::currentCpuArchitecture().toStdString();
}

// this computer's processor and graphics card, its driver too: tested again when it changes
std::string hardwareKey()
{
    auto glString = [](GLenum name) {
        const auto* text = reinterpret_cast<const char*>(gOpenGLFunctions.glGetString(name));
        return std::string(text ? text : "");
    };
    return processorName() + " x" + std::to_string(std::thread::hardware_concurrency()) + " | "
        + glString(GL_RENDERER) + " | " + glString(GL_VERSION);
}

// a block of stock, 100 x 100 x 30 mm
void block(std::vector<Vertex>& verts, std::vector<GLushort>& indices)
{
    const float lo[3] = {0, 0, 0};
    const float hi[3] = {100, 100, 30};
    for (int axis = 0; axis < 3; axis++) {
        for (int side = 0; side < 2; side++) {
            const int a = (axis + 1) % 3;
            const int b = (axis + 2) % 3;
            const float at = side ? hi[axis] : lo[axis];
            float n[3] = {0, 0, 0};
            n[axis] = side ? 1.f : -1.f;
            const auto first = (GLushort)verts.size();
            for (int corner = 0; corner < 4; corner++) {
                float p[3];
                p[axis] = at;
                p[a] = (corner == 1 || corner == 2) ? hi[a] : lo[a];
                p[b] = corner >= 2 ? hi[b] : lo[b];
                verts.emplace_back(p[0], p[1], p[2], n[0], n[1], n[2]);
            }
            // facing out
            if (side) {
                indices.insert(indices.end(), {first, (GLushort)(first + 1), (GLushort)(first + 2)});
                indices.insert(indices.end(), {first, (GLushort)(first + 2), (GLushort)(first + 3)});
            }
            else {
                indices.insert(indices.end(), {first, (GLushort)(first + 2), (GLushort)(first + 1)});
                indices.insert(indices.end(), {first, (GLushort)(first + 3), (GLushort)(first + 2)});
            }
        }
    }
}

MillMotion at(float x, float y, float z)
{
    MillMotion m;
    m.cmd = eMoveLiner;
    m.x = x;
    m.y = y;
    m.z = z;
    return m;
}

// The time a program of moves takes, seconds: each move cut, and the tool looked at where it
// ends, as a holder is, then all of it done and drawn.
double timeMoves(DexelStock& stock, const EndMill& tool, const std::vector<MillMotion>& points)
{
    mat4x4 frame;
    mat4x4_identity(frame);
    std::vector<std::unique_ptr<MillPathSegment>> moves;
    for (size_t i = 1; i < points.size(); i++) {
        moves.push_back(std::make_unique<MillPathSegment>(tool, points[i - 1], points[i], frame));
    }
    const auto start = std::chrono::steady_clock::now();
    int id = 0;
    for (const auto& move : moves) {
        vec3 lo, hi;
        move->BoundingBox(lo, hi);
        MillPathSegment* p = move.get();
        stock.Cut(lo, hi, [p] { p->render(p->numSimSteps); });
        stock.Probe(lo, hi, id++, [p] { p->render(p->numSimSteps); });
    }
    stock.Flush();
    std::vector<std::pair<int, int>> hits;
    stock.TakeHits(hits);
    stock.Sync(1e9);
    gOpenGLFunctions.glFinish();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

// How fast one side cuts: many short moves, where a cut's own cost tells, then a few long ones,
// where the area tells; each a cost a cut and a cost a mm² from the two.
Speed measure(bool cpu)
{
    Speed speed;
    std::vector<Vertex> verts;
    std::vector<GLushort> indices;
    block(verts, indices);
    DexelStock stock;
    if (!stock.Init(verts, indices, 0.5f, cpu) || stock.OnProcessor() != cpu) {
        return speed;
    }
    // a 6 mm end mill
    EndMill tool({3.f, 25.f, 3.f, 0.f, 0.f, 0.f}, -1, 6.f);
    tool.GenerateDisplayLists(5.f);

    // warmed up first, its shaders and buffers made
    timeMoves(stock, tool, {at(5, 5, 29), at(8, 5, 29), at(8, 8, 29)});

    // short moves: 300 half millimeters, zigzagging a millimeter deep
    std::vector<MillMotion> zigzag;
    const int shortMoves = 300;
    for (int i = 0; i <= shortMoves; i++) {
        const float x = 10.f + 0.5f * (float)(i % 150);
        const float y = 20.f + 7.f * (float)(i / 150) + ((i % 2) ? 0.2f : 0.f);
        zigzag.push_back(at(x, y, 29.f));
    }
    const double shortTime = timeMoves(stock, tool, zigzag);
    const double shortArea = shortMoves * 0.5 * 6.0;

    // long moves: 8 passes of 90 mm, 5 mm deep
    std::vector<MillMotion> passes;
    const int longMoves = 8;
    for (int i = 0; i <= longMoves; i++) {
        const float y = 40.f + 5.f * (float)i;
        passes.push_back(at((i % 2) ? 95.f : 5.f, y, 25.f));
    }
    const double longTime = timeMoves(stock, tool, passes);
    const double longArea = longMoves * 90.0 * 6.0;

    // shortTime = shortMoves * perCut + shortArea * perArea, and the same for the long ones
    const double det = (double)shortMoves * longArea - (double)longMoves * shortArea;
    if (std::abs(det) < 1e-9) {
        return speed;
    }
    speed.perCut = std::max(0.0, (shortTime * longArea - longTime * shortArea) / det);
    speed.perArea = std::max(0.0, ((double)shortMoves * longTime - (double)longMoves * shortTime) / det);
    speed.usable = true;
    return speed;
}

// the graphics card's free memory, bytes; 0 when it does not say
double cardFreeMemory()
{
    QOpenGLContext* context = QOpenGLContext::currentContext();
    if (!context) {
        return 0;
    }
    GLint kb[4] = {0, 0, 0, 0};
    if (context->hasExtension(QByteArrayLiteral("GL_NVX_gpu_memory_info"))) {
        gOpenGLFunctions.glGetIntegerv(GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX, kb);
    }
    else if (context->hasExtension(QByteArrayLiteral("GL_ATI_meminfo"))) {
        gOpenGLFunctions.glGetIntegerv(GL_TEXTURE_FREE_MEMORY_ATI, kb);
    }
    return 1024.0 * (double)kb[0];
}

}  // namespace

bool RunOnProcessor(const DexelJob& job)
{
    auto prefs = App::GetApplication().GetParameterGroupByPath(PrefPath);
    // the environment, for testing, then the preference
    if (const char* forced = std::getenv("CAMSIM_DEXEL_GPU")) {
        return forced[0] != '1';
    }
    const long choice = prefs->GetInt("SimulatorDexelCutting", 0);
    if (choice == 1) {
        return true;
    }
    if (choice == 2) {
        return false;
    }

    // Automatic: tested on this computer once, again when its processor or card changes
    const std::string key = hardwareKey();
    if (prefs->GetASCII("SimulatorAutoKey", "") != key) {
        const Speed cpu = measure(true);
        const Speed card = measure(false);
        prefs->SetBool("SimulatorAutoCardUsable", card.usable);
        prefs->SetFloat("SimulatorAutoCpuCut", cpu.perCut);
        prefs->SetFloat("SimulatorAutoCpuArea", cpu.perArea);
        prefs->SetFloat("SimulatorAutoCardCut", card.perCut);
        prefs->SetFloat("SimulatorAutoCardArea", card.perArea);
        prefs->SetASCII(
            "SimulatorAutoTested",
            QDate::currentDate().toString(Qt::ISODate).toStdString().c_str()
        );
        prefs->SetASCII("SimulatorAutoKey", key.c_str());
    }

    bool processor = true;
    if (prefs->GetBool("SimulatorAutoCardUsable", false)) {
        const double cpuTime = job.cuts * prefs->GetFloat("SimulatorAutoCpuCut", 0)
            + job.sweptArea * prefs->GetFloat("SimulatorAutoCpuArea", 0);
        const double cardTime = job.cuts * prefs->GetFloat("SimulatorAutoCardCut", 0)
            + job.sweptArea * prefs->GetFloat("SimulatorAutoCardArea", 0);
        // on the card only when its stock fits, where the card says how much room it has
        const double room = cardFreeMemory();
        const bool fits = room <= 0 || job.cardBytes < 0.8 * room;
        processor = !(cardTime < cpuTime && fits);
    }
    prefs->SetASCII("SimulatorAutoPick", processor ? "Processor" : "Graphics card");
    return processor;
}

}  // namespace CAMSimulator
