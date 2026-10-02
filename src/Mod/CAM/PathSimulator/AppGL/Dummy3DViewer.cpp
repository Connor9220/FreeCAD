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

#include "PreCompiled.h"

#include "Dummy3DViewer.h"
#include <Gui/NaviCube.h>
#include <Inventor/SoRenderManager.h>
#include <Inventor/actions/SoGLRenderAction.h>
#include <Inventor/fields/SoSFVec4f.h>
#include <Inventor/nodes/SoCamera.h>
#include <Inventor/nodes/SoGroup.h>
#include <QOpenGLContext>
#include <QOpenGLFunctions>
#include <QOpenGLWidget>
#include <algorithm>
#include <vector>

using namespace Gui;

namespace CAMSimulator
{

Dummy3DViewer::Dummy3DViewer(QWidget* parent)
    : View3DInventorViewer(parent)
{
    addViewProvider(&stockViewProvider);
    addViewProvider(&baseViewProvider);
    naviSensor.setFunction(&Dummy3DViewer::naviCubeChanged);
    naviSensor.setData(this);
}

void Dummy3DViewer::naviCubeChanged(void* data, SoSensor* /*sensor*/)
{
    static_cast<Dummy3DViewer*>(data)->naviDirty = true;
}

bool Dummy3DViewer::updateNaviCube()
{
    NaviCube* cube = isEnabledNaviCube() ? getNaviCube() : nullptr;
    auto glw = qobject_cast<QOpenGLWidget*>(viewport());
    if (!cube || !glw || !glw->isValid() || !glw->context()) {
        const bool had = !naviImage.isNull();
        naviImage = QImage();
        return had;
    }
    SoNode* root = cube->getCoinNode();
    if (root != naviNode) {
        naviSensor.detach();
        naviSensor.attach(root);
        naviNode = root;
        naviDirty = true;
    }
    SoRenderManager* manager = getSoRenderManager();
    const SoCamera* camera = manager->getCamera();
    const SbRotation rot = camera ? camera->orientation.getValue() : SbRotation();
    const SbViewportRegion region = manager->getViewportRegion();
    const SbVec2s size = region.getViewportSizePixels();
    if (!naviDirty && rot == naviCameraRot && size == naviSize) {
        return false;
    }
    naviDirty = false;
    naviCameraRot = rot;
    naviSize = size;
    if (size[0] <= 0 || size[1] <= 0) {
        return false;
    }

    // The cube alone, drawn into this viewer's own buffer, where Coin's caches for it live: on
    // black, then on white, the two giving each pixel's colour and how opaque it is. Its drawing
    // sets its own fields, which is no change to it.
    naviSensor.detach();
    glw->makeCurrent();
    QOpenGLFunctions* gl = glw->context()->functions();
    gl->glBindFramebuffer(GL_FRAMEBUFFER, glw->defaultFramebufferObject());
    SoGLRenderAction* action = manager->getGLRenderAction();
    action->setViewportRegion(region);
    auto group = static_cast<SoGroup*>(root);
    SoNode* cubeNode = group->getNumChildren() > 1 ? group->getChild(1) : nullptr;
    auto rectField = cubeNode
        ? dynamic_cast<SoSFVec4f*>(cubeNode->getField(SbName("viewportRect")))
        : nullptr;
    std::vector<unsigned char> pixels[2];
    int x = 0, y = 0, w = 0, h = 0;
    for (int pass = 0; pass < 2; pass++) {
        gl->glViewport(0, 0, size[0], size[1]);
        gl->glDisable(GL_SCISSOR_TEST);
        gl->glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        gl->glDepthMask(GL_TRUE);
        gl->glClearColor((float)pass, (float)pass, (float)pass, 1.f);
        gl->glClearDepthf(1.f);
        gl->glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        action->apply(root);
        if (pass == 0) {
            if (!rectField) {
                break;
            }
            const SbVec4f r = rectField->getValue();
            x = std::max(0, (int)r[0]);
            y = std::max(0, (int)r[1]);
            w = std::min((int)size[0] - x, (int)r[2]);
            h = std::min((int)size[1] - y, (int)r[3]);
            if (w <= 0 || h <= 0) {
                break;
            }
        }
        pixels[pass].resize((size_t)w * h * 4);
        gl->glPixelStorei(GL_PACK_ALIGNMENT, 1);
        gl->glReadPixels(x, y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, pixels[pass].data());
    }
    glw->doneCurrent();
    naviSensor.attach(root);

    if (pixels[1].empty()) {
        const bool had = !naviImage.isNull();
        naviImage = QImage();
        return had;
    }
    // over black the colour is already weighted by its opacity; white shows how much of the
    // background comes through
    QImage image(w, h, QImage::Format_RGBA8888_Premultiplied);
    for (int row = 0; row < h; row++) {
        const unsigned char* black = pixels[0].data() + (size_t)(h - 1 - row) * w * 4;
        const unsigned char* white = pixels[1].data() + (size_t)(h - 1 - row) * w * 4;
        uchar* out = image.scanLine(row);
        for (int col = 0; col < w; col++, black += 4, white += 4, out += 4) {
            const int through = std::clamp((int)white[1] - (int)black[1], 0, 255);
            const int alpha = 255 - through;
            out[0] = std::min<int>(black[0], alpha);
            out[1] = std::min<int>(black[1], alpha);
            out[2] = std::min<int>(black[2], alpha);
            out[3] = (uchar)alpha;
        }
    }
    naviImage = image;
    naviRect = QRect(x, size[1] - y - h, w, h);
    return true;
}

void Dummy3DViewer::cloneFrom(Dummy3DViewer& viewer)
{
    // move view providers from viewer to us

    stockViewProvider = std::move(viewer.stockViewProvider);
    baseViewProvider = std::move(viewer.baseViewProvider);
}

void Dummy3DViewer::setStockShape(const Part::TopoShape& shape)
{
    stockViewProvider.setShape(shape);
}

void Dummy3DViewer::setStockVisible(bool b)
{
    stockViewProvider.setShapeVisible(b);
}

void Dummy3DViewer::setBaseShape(const Part::TopoShape& shape)
{
    baseViewProvider.setShape(shape);
}

void Dummy3DViewer::setBaseVisible(bool b)
{
    baseViewProvider.setShapeVisible(b);
}

void Dummy3DViewer::paintEvent(QPaintEvent* event)
{
    if (discardPaintEvent_) {
        return;
    }

    View3DInventorViewer::paintEvent(event);
}

}  // namespace CAMSimulator
