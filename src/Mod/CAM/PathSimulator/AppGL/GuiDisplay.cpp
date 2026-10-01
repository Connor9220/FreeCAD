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

#include "GuiDisplay.h"

#include "ui_GuiDisplay.h"
#include <QPainter>
#include <QStyleOptionSlider>
#include <Base/Quantity.h>
#include <Base/Unit.h>
#include <cmath>
#include <limits>

// include this last as the defines can mess up other includes
#include "OpenGlWrapper.h"

namespace CAMSimulator
{

// Lines across the stage slider where each operation starts, drawn over it and letting the mouse
// through to it
class OperationMarkers: public QWidget
{
public:
    explicit OperationMarkers(QSlider* slider)
        : QWidget(slider)
        , slider(slider)
    {
        setAttribute(Qt::WA_TransparentForMouseEvents);
        // a theme's style sheet may give every widget a background, which would hide the slider
        setStyleSheet(QStringLiteral("background: transparent;"));
        setGeometry(slider->rect());
    }

    void setStarts(const std::vector<float>& s)
    {
        if (s == starts) {
            return;
        }
        starts = s;
        update();
    }

protected:
    void paintEvent(QPaintEvent* /*event*/) override
    {
        if (starts.empty()) {
            return;
        }
        // where the slider puts its handle's middle for a value, so the lines meet the handle
        QStyleOptionSlider opt;
        opt.initFrom(slider);
        opt.orientation = slider->orientation();
        opt.minimum = slider->minimum();
        opt.maximum = slider->maximum();
        opt.sliderPosition = slider->sliderPosition();
        opt.sliderValue = slider->value();
        opt.subControls = QStyle::SC_SliderGroove | QStyle::SC_SliderHandle;
        QStyle* style = slider->style();
        const QRect groove
            = style->subControlRect(QStyle::CC_Slider, &opt, QStyle::SC_SliderGroove, slider);
        const QRect handle
            = style->subControlRect(QStyle::CC_Slider, &opt, QStyle::SC_SliderHandle, slider);
        const int span = groove.width() - handle.width();
        const int x0 = groove.x() + handle.width() / 2;

        QPainter painter(this);
        painter.setPen(QPen(QColor(255, 255, 255, 200), 2));
        for (float f : starts) {
            const int x = x0 + (int)std::lround(f * (float)span);
            painter.drawLine(x, 1, x, height() - 2);
        }
        // and where the last one stops
        painter.drawLine(x0 + span, 1, x0 + span, height() - 2);
    }

private:
    QSlider* slider;
    std::vector<float> starts;
};

GuiDisplay::GuiDisplay(QWidget* parent)
    : QWidget(parent)
    , ui(new Ui_GuiDisplay)
{
    ui->setupUi(this);

    opMarkers = new OperationMarkers(ui->stageSlider);
    ui->stageSlider->installEventFilter(this);

    playing = true;
    setPlaying(false);

    speed = 0;
    setSpeed(1);

    connect(ui->slowerButton, &QToolButton::clicked, this, &GuiDisplay::onSlowerFasterButtonClicked);
    connect(ui->fasterButton, &QToolButton::clicked, this, &GuiDisplay::onSlowerFasterButtonClicked);
    connect(ui->viewAllButton, &QToolButton::clicked, this, &GuiDisplay::viewAll);
    connect(ui->rotateButton, &QToolButton::toggled, this, &GuiDisplay::rotateEnableChanged);
    connect(ui->pathButton, &QToolButton::toggled, this, &GuiDisplay::pathVisibleChanged);
    connect(ui->ssaoButton, &QToolButton::toggled, this, &GuiDisplay::ssaoEnableChanged);
    connect(ui->tablePoseButton, &QToolButton::toggled, this, &GuiDisplay::tablePoseEnableChanged);
}

GuiDisplay::~GuiDisplay()
{
    delete ui;
}

bool GuiDisplay::eventFilter(QObject* watched, QEvent* event)
{
    // the markers cover the slider whatever its size
    if (watched == ui->stageSlider && event->type() == QEvent::Resize) {
        opMarkers->setGeometry(ui->stageSlider->rect());
    }
    return QWidget::eventFilter(watched, event);
}

void GuiDisplay::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    setMask(childrenRegion());
}

void GuiDisplay::setPlaying(bool b)
{
    if (b == playing) {
        return;
    }

    playing = b;

    const auto icon = playing ? ":/gl_simulator/Pause.png" : ":/gl_simulator/Play.png";
    ui->playButton->setIcon(QIcon(QString::fromUtf8(icon)));
}

void GuiDisplay::on_playButton_clicked()
{
    setPlaying(!playing);
    Q_EMIT play(playing);
}

void GuiDisplay::on_singleStepButton_clicked()
{
    setPlaying(false);
    Q_EMIT singleStep();
}

void GuiDisplay::on_nextOpButton_clicked()
{
    Q_EMIT nextOperation();
}

void GuiDisplay::setOperationStarts(const std::vector<float>& starts)
{
    opMarkers->setStarts(starts);
}

void GuiDisplay::setOperation(const QString& name)
{
    if (ui->opLabel->text() != name) {
        ui->opLabel->setText(name);
    }
}

void GuiDisplay::setSpeed(int s)
{
    if (s == speed) {
        return;
    }

    speed = s;
    ui->speedLabel->setText(tr("x%1").arg(speed));
}

// multiples of real time
static const std::vector<int> speeds = {1, 2, 5, 10, 25, 50, 100, 250, 500, 1000};

std::vector<int>::const_iterator findNearestSpeed(int speed)
{
    int dist = std::numeric_limits<int>::max();
    auto ret = speeds.cend();

    for (auto it = speeds.cbegin(); it != speeds.cend(); it++) {
        const int curdist = std::abs(*it - speed);
        if (curdist < dist) {
            dist = curdist;
            ret = it;
        }
    }

    return ret;
}

void GuiDisplay::onSlowerFasterButtonClicked()
{
    auto it = findNearestSpeed(speed);

    const bool slower = sender() == ui->slowerButton;
    const bool faster = !slower;

    if (slower && it != speeds.begin()) {
        it--;
    }
    else if (faster && it != (speeds.end() - 1)) {
        it++;
    }

    setSpeed(*it);
    Q_EMIT speedChanged(*it);
}

void GuiDisplay::setStage(float f, int total)
{
    ui->stageSlider->setMaximum(total);
    ui->stageSlider->setValue(f * total);
}

static QString formatTime(float seconds)
{
    const int s = (int)std::lround(seconds);
    if (s >= 3600) {
        return QStringLiteral("%1:%2:%3")
            .arg(s / 3600)
            .arg((s / 60) % 60, 2, 10, QLatin1Char('0'))
            .arg(s % 60, 2, 10, QLatin1Char('0'));
    }
    return QStringLiteral("%1:%2").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0'));
}

void GuiDisplay::setTime(float seconds, float totalSeconds)
{
    ui->timeLabel->setText(
        QStringLiteral("%1 / %2").arg(formatTime(seconds), formatTime(totalSeconds))
    );
}

void GuiDisplay::setFeed(float feed, bool rapid)
{
    if (feed <= 0) {
        ui->feedLabel->setText(rapid ? tr("Rapid") : QString());
        return;
    }
    // Feeds are mm/s; the user's unit schema picks the unit, and one decimal is plenty for a feed
    // to be read off
    double factor = 1;
    std::string unit;
    Base::Quantity(feed, Base::Unit::Velocity).getUserString(factor, unit);
    const QString rate = QStringLiteral("%1 %2")
                             .arg(feed / (factor != 0 ? factor : 1.0), 0, 'f', 1)
                             .arg(QString::fromStdString(unit));
    const QString text = rapid ? tr("Rapid %1").arg(rate) : tr("F %1").arg(rate);
    if (ui->feedLabel->text() != text) {
        ui->feedLabel->setText(text);
    }
}

void GuiDisplay::on_stageSlider_sliderMoved(int value)
{
    const float f = (float)value / ui->stageSlider->maximum();
    Q_EMIT stageChanged(f);
}

void GuiDisplay::setStockVisible(bool b)
{
    stockVisible = b;

    QSignalBlocker blocker(ui->stockModelButton);
    ui->stockModelButton->setChecked(stockVisible && baseVisible);
}

void GuiDisplay::setBaseVisible(bool b)
{
    baseVisible = b;

    QSignalBlocker blocker(ui->stockModelButton);
    ui->stockModelButton->setChecked(stockVisible && baseVisible);
}

void GuiDisplay::on_stockModelButton_clicked()
{
    // stock -> base -> both
    //   ^---------------'

    bool sv = false;
    bool bv = false;

    if (stockVisible == baseVisible) {
        sv = true;
        bv = false;
    }
    else if (!baseVisible) {
        sv = false;
        bv = true;
    }
    else if (!stockVisible) {
        sv = true;
        bv = true;
    }

    if (sv != stockVisible) {
        setStockVisible(sv);
        Q_EMIT stockVisibleChanged(sv);
    }

    if (bv != baseVisible) {
        setBaseVisible(bv);
        Q_EMIT baseVisibleChanged(bv);
    }
}

void GuiDisplay::setRotateEnabled(bool b)
{
    ui->rotateButton->setChecked(b);
}

void GuiDisplay::setPathVisible(bool b)
{
    QSignalBlocker blocker(ui->pathButton);
    ui->pathButton->setChecked(b);
}

void GuiDisplay::setSsaoEnabled(bool b)
{
    QSignalBlocker blocker(ui->ssaoButton);
    ui->ssaoButton->setChecked(b);
}

void GuiDisplay::setIndexMode(int mode)
{
    if (mode == indexMode) {
        return;
    }
    indexMode = mode;

    // as MillSimulation's IndexMode: sequenced, together, shortest
    static const char* const icons[] = {
        ":/gl_simulator/RotarySequence.png",
        ":/gl_simulator/RotaryTogether.png",
        ":/gl_simulator/RotaryShortest.png",
    };
    const QString tips[] = {
        tr("Rotary axes turn one after another, in the machine's sequence. Click to cycle."),
        tr("Rotary axes turn together and finish together. Click to cycle."),
        tr("The part takes the shortest turn between poses, whatever the axes. Click to cycle."),
    };
    if (mode >= 0 && mode < 3) {
        ui->indexModeButton->setIcon(QIcon(QString::fromUtf8(icons[mode])));
        ui->indexModeButton->setToolTip(tips[mode]);
    }
}

void GuiDisplay::on_indexModeButton_clicked()
{
    const int mode = (indexMode + 1) % 3;
    setIndexMode(mode);
    Q_EMIT indexModeChanged(mode);
}

void GuiDisplay::setTablePoseEnabled(bool b)
{
    QSignalBlocker blocker(ui->tablePoseButton);
    ui->tablePoseButton->setChecked(b);
}

}  // namespace CAMSimulator
