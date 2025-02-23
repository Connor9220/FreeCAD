/***************************************************************************
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>              *
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

#ifndef Fem_FemMeshObject_H
#define Fem_FemMeshObject_H

#include <App/FeaturePython.h>
#include <App/GeoFeature.h>
#include <App/SuppressibleExtension.h>

#include "FemMesh.h"
#include "FemMeshProperty.h"


namespace Fem
{

class FemExport FemMeshObject: public App::GeoFeature
{
    PROPERTY_HEADER_WITH_OVERRIDE(Fem::FemMeshObject);

public:
    /// Constructor
    FemMeshObject();
    ~FemMeshObject() override;

    /// returns the type name of the ViewProvider
    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemMesh";
    }
    App::DocumentObjectExecReturn* execute() override
    {
        return App::DocumentObject::StdReturn;
    }
    short mustExecute() const override;
    PyObject* getPyObject() override;
    const App::PropertyComplexGeoData* getPropertyOfGeometry() const override
    {
        return &FemMesh;
    }

    PropertyFemMesh FemMesh;

protected:
    /// get called by the container when a property has changed
    void onChanged(const App::Property* prop) override;

private:
    App::SuppressibleExtension suppressibleExt;
};

using FemMeshObjectPython = App::FeaturePythonT<FemMeshObject>;


}  // namespace Fem


#endif  // Fem_FemMeshObject_H
