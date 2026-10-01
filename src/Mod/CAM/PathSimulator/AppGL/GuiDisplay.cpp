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

// The colour a rotary axis is shown in: its turns under the slider and its name in the label
static QColor axisColor(int axis)
{
    static const QColor colors[] = {
        QColor(255, 159, 26),   // orange
        QColor(62, 197, 255),   // cyan
        QColor(179, 136, 255),  // purple
        QColor(124, 252, 0),    // green
    };
    if (axis < 0) {
        return QColor(255, 213, 79);  // the table as a whole
    }
    return colors[axis % 4];
}

// x of a share of the slider's range, in the slider's coordinates: where its handle's middle goes
static void sliderSpan(const QSlider* slider, int& x0, int& span)
{
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
    span = groove.width() - handle.width();
    x0 = groove.x() + handle.width() / 2;
}

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

    void setSpans(const std::vector<SimTimeSpan>& s)
    {
        bool same = s.size() == spans.size();
        for (size_t i = 0; i < s.size() && same; i++) {
            same = s[i].start == spans[i].start && s[i].end == spans[i].end
                && s[i].axis == spans[i].axis;
        }
        if (same) {
            return;
        }
        spans = s;
        update();
    }

protected:
    void paintEvent(QPaintEvent* /*event*/) override
    {
        if (starts.empty()) {
            return;
        }
        // where the slider puts its handle's middle for a value, so the lines meet the handle
        int x0, span;
        sliderSpan(slider, x0, span);

        QPainter painter(this);
        painter.setPen(QPen(QColor(255, 255, 255, 200), 2));
        for (float f : starts) {
            const int x = x0 + (int)std::lround(f * (float)span);
            painter.drawLine(x, 1, x, height() - 2);
        }
        // and where the last one stops
        painter.drawLine(x0 + span, 1, x0 + span, height() - 2);

        // and where each rotary axis starts and stops turning; the bars under say which
        for (const SimTimeSpan& s : spans) {
            for (float f : {s.start, s.end}) {
                const int x = x0 + (int)std::lround(f * (float)span);
                painter.drawLine(x, 1, x, height() - 2);
            }
        }
    }

private:
    QSlider* slider;
    std::vector<float> starts;
    std::vector<SimTimeSpan> spans;
};

// Bars under the stage slider for when the rotary axes turn, a row and a colour for each axis
class IndexTimeline: public QWidget
{
public:
    IndexTimeline(QSlider* slider, QWidget* parent)
        : QWidget(parent)
        , slider(slider)
    {
        setStyleSheet(QStringLiteral("background: transparent;"));
        setFixedHeight(16);
    }

    void setSpans(const std::vector<SimTimeSpan>& s, const QStringList& names)
    {
        bool same = s.size() == spans.size() && names == axisNames;
        for (size_t i = 0; i < s.size() && same; i++) {
            same = s[i].start == spans[i].start && s[i].end == spans[i].end
                && s[i].axis == spans[i].axis;
        }
        if (same) {
            return;
        }
        spans = s;
        axisNames = names;

        // the legend: each axis's name in its colour
        QString tip = QObject::tr("When the rotary axes turn:");
        for (int k = 0; k < names.size(); k++) {
            tip += QStringLiteral(" <b style='color:%1'>%2</b>").arg(axisColor(k).name(), names[k]);
        }
        setToolTip(names.isEmpty() ? QString() : tip);
        update();
    }

protected:
    void paintEvent(QPaintEvent* /*event*/) override
    {
        if (axisNames.isEmpty() && spans.empty()) {
            return;
        }
        int x0, span;
        sliderSpan(slider, x0, span);
        x0 += slider->x() - x();  // the slider's x in this widget's coordinates

        const int rows = std::max(1, (int)axisNames.size());
        const int rowHeight = std::max(2, (height() - 1) / rows);
        QPainter painter(this);

        // each row's axis, named in its colour at the left
        QFont font = painter.font();
        font.setBold(true);
        font.setPixelSize(std::max(6, rowHeight));
        painter.setFont(font);
        for (int k = 0; k < axisNames.size(); k++) {
            painter.setPen(axisColor(k));
            painter.drawText(
                QRect(0, k * rowHeight, std::max(1, x0 - 1), rowHeight),
                Qt::AlignRight | Qt::AlignVCenter,
                axisNames[k]
            );
        }

        for (const SimTimeSpan& s : spans) {
            const int left = x0 + (int)std::lround(s.start * (float)span);
            const int right = std::max(left + 2, x0 + (int)std::lround(s.end * (float)span));
            // the whole table's turn covers every row
            const int top = s.axis < 0 ? 0 : s.axis * rowHeight;
            const int h = s.axis < 0 ? rows * rowHeight - 1 : rowHeight - 1;
            painter.fillRect(left, top, right - left, h, axisColor(s.axis));
        }
    }

private:
    QSlider* slider;
    std::vector<SimTimeSpan> spans;
    QStringList axisNames;
};

GuiDisplay::GuiDisplay(QWidget* parent)
    : QWidget(parent)
    , ui(new Ui_GuiDisplay)
{
    ui->setupUi(this);

    opMarkers = new OperationMarkers(ui->stageSlider);
    ui->stageSlider->installEventFilter(this);

    // the slider is set in a little from the left, where the bars under it name their axes
    const int sliderRow = ui->verticalLayout->indexOf(ui->stageSlider);
    ui->verticalLayout->removeWidget(ui->stageSlider);
    auto row = new QHBoxLayout();
    row->setSpacing(0);
    row->addSpacing(14);
    row->addWidget(ui->stageSlider);
    ui->verticalLayout->insertLayout(sliderRow, row);

    indexTimeline = new IndexTimeline(ui->stageSlider, this);
    ui->verticalLayout->insertWidget(sliderRow + 1, indexTimeline);

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
    connect(ui->incrementalButton, &QToolButton::toggled, this, &GuiDisplay::incrementalEnableChanged);
    connect(ui->dexelButton, &QToolButton::toggled, this, &GuiDisplay::dexelEnableChanged);
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
    Q_EMIT nextMark();
}

void GuiDisplay::on_prevOpButton_clicked()
{
    Q_EMIT previousMark();
}

void GuiDisplay::setIndexSpans(const std::vector<SimTimeSpan>& spans, const QStringList& axisNames)
{
    indexTimeline->setSpans(spans, axisNames);
    opMarkers->setSpans(spans);
}

void GuiDisplay::setIndexAngles(const QStringList& axisNames, const std::vector<float>& angles)
{
    // while the rotaries turn, their positions in place of the feed, each in its axis's colour
    QString text = tr("Index");
    for (size_t k = 0; k < angles.size() && (int)k < axisNames.size(); k++) {
        text += QStringLiteral(" &nbsp;<b style='color:%1'>%2</b> %3°")
                    .arg(axisColor((int)k).name(), axisNames[(int)k])
                    .arg(angles[k], 0, 'f', 1);
    }
    setFeedLabel(text, false);
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

void GuiDisplay::setFeedLabel(const QString& text, bool rapid)
{
    if (ui->feedLabel->text() != text) {
        ui->feedLabel->setText(text);
    }
    // rapids in red
    const QString style = QStringLiteral("color:%1; padding-left:12px")
                              .arg(rapid ? QStringLiteral("#ff5050") : QStringLiteral("white"));
    if (ui->feedLabel->styleSheet() != style) {
        ui->feedLabel->setStyleSheet(style);
    }
}

void GuiDisplay::setFeed(float feed, bool rapid)
{
    if (feed <= 0) {
        setFeedLabel(rapid ? tr("Rapid") : QString(), rapid);
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
    setFeedLabel(rapid ? tr("Rapid %1").arg(rate) : tr("F %1").arg(rate), rapid);
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

void GuiDisplay::setIncrementalEnabled(bool b)
{
    QSignalBlocker blocker(ui->incrementalButton);
    ui->incrementalButton->setChecked(b);
}

void GuiDisplay::setDexelEnabled(bool b)
{
    QSignalBlocker blocker(ui->dexelButton);
    ui->dexelButton->setChecked(b);
}

void GuiDisplay::setFps(float fps)
{
    const QString text = fps > 0 ? tr("%1 fps").arg(fps, 0, 'f', 0) : QString();
    if (ui->fpsLabel->text() != text) {
        ui->fpsLabel->setText(text);
    }
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
