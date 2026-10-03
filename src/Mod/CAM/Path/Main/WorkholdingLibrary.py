# SPDX-License-Identifier: LGPL-2.1-or-later

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

"""Libraries of workholding to download vises from: each an index.json, at a web address or in a
folder, listing its vises, their files, settings, licences and the sha256 each is checked
against. The libraries looked in are a preference, one address a line; a vise downloaded is
saved in the user's Workholding folder, where the Vise panel finds it.

Nothing downloaded is opened as a document to be checked: what it holds is read from it as the
zip it is, and one holding Python, which would run when it is opened, is refused."""

import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request

import FreeCAD
import Path
import Path.Main.WorkholdingCheck as PathCheck

translate = FreeCAD.Qt.translate

# the library FreeCAD looks in unless told otherwise
DefaultSources = [
    "https://raw.githubusercontent.com/Connor9220/FreeCAD-Workholding/main/index.json"
]
# the index's layout this FreeCAD reads
IndexFormat = 1
TIMEOUT = 20


def _prefs():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CAM")


def sources():
    """sources() ... the libraries to look in, their index's addresses: the preference, one a
    line, else the default."""
    text = _prefs().GetString("WorkholdingSources", "")
    found = [line.strip() for line in text.splitlines() if line.strip()]
    return found or list(DefaultSources)


def setSources(addresses):
    """setSources(addresses) ... the libraries to look in, kept; none, the default again."""
    _prefs().SetString("WorkholdingSources", "\n".join(a.strip() for a in addresses if a.strip()))


def folder():
    """folder() ... where vises downloaded are saved: the CAM assets' Workholding folder."""
    import Path.Preferences

    return str(Path.Preferences.getAssetPath() / "Workholding")


def fetch(address):
    """fetch(address) ... what is at a web address, a file:// one or a path, as bytes."""
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(address, headers={"User-Agent": "FreeCAD CAM"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    if parsed.scheme == "file":
        address = urllib.request.url2pathname(parsed.path)
    with open(os.path.expanduser(address), "rb") as f:
        return f.read()


def _address(index, relative):
    """An index's entry's address, relative to the index's own."""
    if urllib.parse.urlparse(index).scheme in ("http", "https", "file"):
        return urllib.parse.urljoin(index, relative)
    return os.path.join(os.path.dirname(os.path.expanduser(index)), relative)


def loadIndex(address):
    """loadIndex(address) ... the vises a library's index lists, each a dict as the index has it,
    with url, its file's address, and thumbnailUrl. Raises ValueError for an index this FreeCAD
    cannot read."""
    try:
        index = json.loads(fetch(address).decode("utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(translate("CAM", "No library at %s: %s") % (address, e))
    if index.get("format", 0) > IndexFormat:
        raise ValueError(
            translate("CAM", "%s is a library for a newer FreeCAD (format %s)")
            % (address, index.get("format"))
        )
    items = []
    for item in index.get("items", []):
        if item.get("kind", "vise") != "vise" or not item.get("file") or not item.get("sha256"):
            continue
        item = dict(item)
        item["url"] = _address(address, item["file"])
        if item.get("thumbnail"):
            item["thumbnailUrl"] = _address(address, item["thumbnail"])
        items.append(item)
    return items


def localPath(item, where=None):
    """localPath(item, where=None) ... where an index's vise is, or would be, saved."""
    return os.path.join(where or folder(), os.path.basename(item["file"]))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def status(item, where=None):
    """status(item, where=None) ... whether an index's vise is here: "installed", the same file;
    "changed", a file of its name that differs, the library's newer or the user's own changes;
    "missing"."""
    path = localPath(item, where)
    if not os.path.exists(path):
        return "missing"
    return "installed" if _sha256(path) == item["sha256"] else "changed"


def download(item, where=None):
    """download(item, where=None) ... an index's vise saved where vises are kept, replacing one of
    its name: checked against the index's size and sha256, and as a vise's file, holding no
    Python, before it is put there. Returns its path; raises ValueError for one refused."""
    data = fetch(item["url"])
    if item.get("size") is not None and len(data) != item["size"]:
        raise ValueError(
            translate("CAM", "%s: %d bytes came, the library says %d")
            % (item["file"], len(data), item["size"])
        )
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError(
            translate("CAM", "%s is not the file the library lists: its sha256 differs")
            % item["file"]
        )
    handle, temporary = tempfile.mkstemp(suffix=".FCStd")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
        errors = PathCheck.checkZip(temporary)
        if errors:
            raise ValueError("%s: %s" % (item["file"], "; ".join(errors)))
        path = localPath(item, where)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # moved in one step where it can be, so a vise is never there half written
        if _sameDevice(temporary, path):
            os.replace(temporary, path)
        else:
            _copy(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    Path.Log.info(translate("CAM", "%s saved in %s") % (item.get("label", item["file"]), path))
    return path


def _sameDevice(a, b):
    try:
        return os.stat(a).st_dev == os.stat(os.path.dirname(b)).st_dev
    except OSError:
        return False


def _copy(source, target):
    with open(source, "rb") as f, open(target, "wb") as g:
        g.write(f.read())
