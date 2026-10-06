# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Billy Huddleston <billy@ivdc.com>
# SPDX-FileNotice: Part of the FreeCAD project.

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

"""Libraries of workholding to download vises and clamps from: each an index.json, at a web
address or in a folder, listing its vises and clamps, their files, settings, licenses and the
sha256 each is checked
against; a GitHub repository's address stands for the index.json at its top. The libraries looked
in are a preference, one address a line; a vise downloaded is
saved in the Vises folder of the user's Workholding folder, a clamp in its Clamps folder, where
the Vise panel finds them.

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
import Path.Workholding.Check as PathCheck

from Path.Workholding.Common import objectKinds, objectProperties, readDocumentXml, readMember
from Path.Workholding.Constants import CLAMP_KINDS

translate = FreeCAD.Qt.translate

# the libraries FreeCAD looks in unless told otherwise: none, the user adds those they use
DefaultSources = []
# the index's layout this FreeCAD reads
IndexFormat = 1
# what a library lists
Kinds = ("vise", "clamp")
TIMEOUT = 20


def _prefs():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CAM")


def libraries():
    """libraries() ... the libraries to look in as the user gave them, (address, branch) pairs,
    the branch a GitHub repository's, empty for its default: the preference, one a line, the
    branch after a tab; else the default."""
    found = []
    for line in _prefs().GetString("WorkholdingSources", "").splitlines():
        address, _, branch = line.partition("\t")
        if address.strip():
            found.append((address.strip(), branch.strip()))
    return found or [(a, "") for a in DefaultSources]


def setLibraries(pairs):
    """setLibraries(pairs) ... the libraries to look in, (address, branch) pairs, kept; none, the
    default again."""
    lines = []
    for address, branch in pairs:
        if address.strip():
            lines.append(address.strip() + ("\t" + branch.strip() if branch.strip() else ""))
    _prefs().SetString("WorkholdingSources", "\n".join(lines))


# the hosts of a GitHub repository's pages, and of its files served raw
GitHub = ("github.com", "www.github.com")
GitHubRaw = "raw.githubusercontent.com"


def _github(address, hosts=GitHub):
    """A GitHub repository's address taken apart, its host one of hosts: (owner, repo, rest), the
    repository's name without .git and the parts of the path after it; None for any other."""
    parsed = urllib.parse.urlparse(address)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc.lower() not in hosts or len(parts) < 2:
        return None
    repo = parts[1][: -len(".git")] if parts[1].endswith(".git") else parts[1]
    return parts[0], repo, parts[2:]


def withBranch(address, branch):
    """withBranch(address, branch) ... a library's address on a branch: a GitHub repository's
    https://github.com/owner/repo/tree/branch; any other, or no branch, as it is."""
    found = _github(address) if branch else None
    if found is None:
        return address
    return "https://github.com/%s/%s/tree/%s" % (found[0], found[1], branch)


def libraryName(address):
    """libraryName(address) ... a library's name to show: a GitHub repository's name, with its
    branch if one is given; a folder's or an index's folder's name."""
    found = _github(address)
    if found is not None:
        _, name, rest = found
        if len(rest) >= 2 and rest[0] == "tree":
            return "%s (%s)" % (name, rest[1])
        return name
    parsed = urllib.parse.urlparse(address)
    host = parsed.netloc.lower()
    parts = [p for p in parsed.path.split("/") if p]
    if host == GitHubRaw and len(parts) >= 3:
        return parts[1] if parts[2] in ("HEAD", "main", "master") else "%s (%s)" % tuple(parts[1:3])
    path = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else address
    if parsed.scheme in ("http", "https"):
        path = parsed.path
    path = path.rstrip("/\\")
    if path.lower().endswith(".json"):
        path = os.path.dirname(path)
    return os.path.basename(path) or address


def sources():
    """sources() ... the libraries to look in, their addresses with their branches."""
    return [withBranch(address, branch) for address, branch in libraries()]


def folder(kind="vise"):
    """folder(kind="vise") ... where vises are kept, and those downloaded saved: the Vises folder
    of the CAM assets' Workholding folder; clamps, its Clamps folder."""
    import Path.Preferences

    if kind == "clamp":
        return str(Path.Preferences.getAssetPath() / "Workholding" / "Clamps")
    return str(Path.Preferences.getAssetPath() / "Workholding" / "Vises")


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


def indexAddress(address):
    """indexAddress(address) ... the address of a library's index.json: a GitHub repository's,
    https://github.com/owner/repo, of its default branch, or with /tree/branch[/folder] of that
    branch and folder, and /blob/... its file, as GitHub serves it raw; a folder's, the index.json
    in it; any other as it is."""
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme in ("http", "https") and parsed.netloc.lower() in GitHub:
        found = _github(address)
        if found is None:
            return address
        owner, repo, rest = found
        if rest[:1] in (["tree"], ["blob"]) and len(rest) >= 2:
            ref, path = rest[1], rest[2:]
        else:
            ref, path = "HEAD", []
        if not path or not path[-1].endswith(".json"):
            path = path + ["index.json"]
        return "https://%s/%s/%s/%s/%s" % (GitHubRaw, owner, repo, ref, "/".join(path))
    if not parsed.scheme and os.path.isdir(os.path.expanduser(address)):
        return os.path.join(os.path.expanduser(address), "index.json")
    return address


def _cached(address):
    """Where a library's index is kept between fetches."""
    name = hashlib.sha1(indexAddress(address).encode("utf-8")).hexdigest() + ".json"
    return os.path.join(FreeCAD.getUserCachePath(), "CAM", "WorkholdingIndexes", name)


def _fetchIndex(address):
    """A library's index fetched, and kept: its bytes. Raises OSError or ValueError."""
    data = fetch(indexAddress(address))
    json.loads(data.decode("utf-8"))
    path = _cached(address)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        pass
    return data


def refreshIndex(address):
    """refreshIndex(address) ... a library's index fetched and kept, for when it cannot be: its
    bytes, None when it could not be fetched, nothing said."""
    try:
        return _fetchIndex(address)
    except (OSError, ValueError):
        return None


def loadIndex(address, kind="vise", online=True):
    """loadIndex(address, kind="vise", online=True) ... the vises a library's index lists, or the
    clamps, or with kind None both, each a dict as the index has it, with url, its file's
    address, and thumbnailUrl: fetched, and kept; the one kept when it cannot be, or online is
    False. Raises ValueError for an index neither fetched nor kept, or one this FreeCAD cannot
    read."""
    where = indexAddress(address)
    data = None
    failed = None
    if online:
        try:
            data = _fetchIndex(address)
        except (OSError, ValueError) as e:
            failed = e
    if data is None:
        try:
            with open(_cached(address), "rb") as f:
                data = f.read()
        except OSError:
            raise ValueError(
                translate("CAM", "No library at %s: %s")
                % (address, failed or translate("CAM", "not fetched yet"))
            )
    try:
        index = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise ValueError(translate("CAM", "No library at %s: %s") % (address, e))
    if index.get("format", 0) > IndexFormat:
        raise ValueError(
            translate("CAM", "%s is a library for a newer FreeCAD (format %s)")
            % (address, index.get("format"))
        )
    items = []
    for item in index.get("items", []):
        if item.get("kind", "vise") not in Kinds or not item.get("file") or not item.get("sha256"):
            continue
        if kind is not None and item.get("kind", "vise") != kind:
            continue
        item = dict(item)
        item["url"] = _address(where, item["file"])
        item["index"] = address
        if item.get("thumbnail"):
            item["thumbnailUrl"] = _address(where, item["thumbnail"])
        items.append(item)
    return items


class IndexCache:
    """IndexCache(online=True, said=None) ... the libraries' indexes, each read once by
    loadIndex, online or only as kept: items(address, kind) its items; one that cannot be read
    none, why said to said, a function, when given."""

    def __init__(self, online=True, said=None):
        self.online = online
        self.said = said
        self.indexes = {}

    def items(self, address, kind=None):
        if (address, kind) not in self.indexes:
            try:
                self.indexes[(address, kind)] = loadIndex(address, kind, online=self.online)
            except ValueError as e:
                if self.said is not None:
                    self.said(str(e))
                self.indexes[(address, kind)] = []
        return self.indexes[(address, kind)]


def localPath(item, where=None):
    """localPath(item, where=None) ... where an index's vise or clamp is, or would be, saved."""
    return os.path.join(where or folder(item.get("kind", "vise")), os.path.basename(item["file"]))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def history(item):
    """history(item) ... the sha256s an index's item was published with before, oldest first.
    An entry is a sha256, or, from indexes that keep it, {"sha256", "commit"}: the commit that
    published it."""
    return [e.get("sha256") if isinstance(e, dict) else e for e in item.get("history", [])]


def publishedIn(item, sha):
    """publishedIn(item, sha) ... the commit that published the version of sha256 sha of an
    index's item, None if the index does not say."""
    for e in item.get("history", []):
        if isinstance(e, dict) and e.get("sha256") == sha:
            return e.get("commit")
    return None


def state(sha, item):
    """state(sha, item) ... a file of sha256 sha against an index's item: "current", the file
    the library has now; "update", one it published before; "modified", one it never did."""
    if sha == item["sha256"]:
        return "current"
    return "update" if sha in history(item) else "modified"


def status(item, where=None):
    """status(item, where=None) ... whether an index's vise or clamp is here: "missing", or as
    state says of the file of its name here: "current", "update" or "modified"."""
    path = localPath(item, where)
    if not os.path.exists(path):
        return "missing"
    return state(_sha256(path), item)


def libraryKey(address):
    """libraryKey(address) ... what tells two addresses of a library the same one: a GitHub
    repository's owner and name, on any branch; any other's index's address."""
    found = _github(address, GitHub + (GitHubRaw,))
    if found is not None:
        return "github:%s/%s" % (found[0].lower(), found[1].lower())
    return indexAddress(address)


def localStates(items, addresses=None):
    """localStates(items, addresses=None) ... the vises or clamps on this computer, as
    localItems lists them, against the indexes kept of the libraries at addresses, the user's
    when None, never fetched: for each, (state, the library's item), state as state says, or
    (None, None) for one no library among them lists. One is found in the library it is stamped
    with, by its id there; one not stamped, by its sha256 among those each has published."""
    addresses = sources() if addresses is None else addresses
    keys = {}
    for address in addresses:
        keys.setdefault(libraryKey(address), address)
    index = IndexCache(online=False).items
    found = []
    for item in items:
        sha = fileSha256(item["path"])
        listed = None
        if item.get("library"):
            address = keys.get(libraryKey(item["library"]))
            if address is not None and item.get("libraryItem"):
                listed = next(
                    (i for i in index(address, item["kind"]) if i["id"] == item["libraryItem"]),
                    None,
                )
        else:
            for address in keys.values():
                listed = next(
                    (
                        i
                        for i in index(address, item["kind"])
                        if sha == i["sha256"] or sha in history(i)
                    ),
                    None,
                )
                if listed is not None:
                    break
        found.append((state(sha, listed), listed) if listed is not None else (None, None))
    return found


def download(item, where=None):
    """download(item, where=None) ... an index's vise or clamp saved where they are kept, replacing
    one of its name: checked against the index's size and sha256, and as a vise's or a clamp's
    file, holding no Python, before it is put there. Returns its path; raises ValueError for one
    refused."""
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
        if item.get("kind", "vise") == "clamp":
            errors = _checkClamp(temporary)
        else:
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


def _checkClamp(path):
    """What is wrong with a clamp's file: Python in it, run when it is opened; no clamp in it."""
    import Path.Workholding.Items as PathItems

    errors = []
    found = PathCheck.pythonObjects(path)
    if found:
        errors.append(PathCheck.pythonMessage(found))
    files = PathCheck.filesLinked(path)
    if files:
        errors.append(PathCheck.linksMessage(files))
    if PathItems.clampFile(path) is None:
        errors.append(translate("CAM", "No clamp: no part, or no VarSet saying what kind it is"))
    return errors


# what a vise's or clamp's file says of itself, stamped in it where it was published: an About
# group in its settings VarSet, each property and the field it is read as
ABOUT = "About"
AboutFields = {
    "Library": "library",
    "LibraryItem": "id",
    "Type": "type",
    "Maker": "maker",
    "Model": "model",
    "License": "license",
    "Attribution": "attribution",
    "Source": "source",
}


def about(path):
    """about(path) ... what the vise's or clamp's file at path says of itself, read from it
    without opening it: label, its part's, and as stamped where it was published library, the
    library's address, id, type, maker, model, license, attribution and source; kind, "vise" or
    "clamp", and its settings, a vise's jawWidth and maxOpening in mm. Those not stamped are
    missing; {} for a file that cannot be read or holds no vise or clamp."""
    root = readDocumentXml(path)
    if root is None:
        return {}
    kinds = objectKinds(root)
    found = {}
    labels = {}
    groups = {}
    settings = None
    for name, props in objectProperties(root):
        label = props.get("Label")
        if label is not None and label.find("String") is not None:
            labels[name] = label.find("String").get("value")
        if kinds.get(name) == "App::Part" and props.get("Group") is not None:
            groups[name] = [link.get("value") for link in props["Group"].iter("Link")]
        if kinds.get(name) != "App::VarSet" or not ("Opening" in props or "Kind" in props):
            continue
        if settings is None:
            settings = name
            if "Opening" in props:
                found["kind"] = "vise"
                found["settings"] = {}
                for prop_name, key in (("JawWidth", "jawWidth"), ("MaxOpening", "maxOpening")):
                    value = props.get(prop_name)
                    if value is not None and value.find("Float") is not None:
                        found["settings"][key] = float(value.find("Float").get("value"))
            else:
                kind = props["Kind"].find("String")
                if kind is None or kind.get("value") not in CLAMP_KINDS:
                    settings = None
                    continue
                found["kind"] = "clamp"
        for prop_name, field in AboutFields.items():
            prop = props.get(prop_name)
            if prop is not None and prop.get("group") == ABOUT and prop.find("String") is not None:
                value = prop.find("String").get("value")
                if value:
                    found[field] = value
    if settings is None or not groups:
        return {}
    # the part holding the settings; a kit's, at the file's root, names none of its pieces
    parts = [n for n, links in groups.items() if settings in links]
    if parts and parts[0] in labels:
        found["label"] = labels[parts[0]]
    elif not parts and settings in labels:
        # a kit's, stamped on its settings
        found["label"] = labels[settings]
    return found


def thumbnail(path):
    """thumbnail(path) ... the thumbnail a FreeCAD file keeps, as PNG bytes; None if none."""
    return readMember(path, "thumbnails/Thumbnail.png")


def localItems(kind="vise", folders=None):
    """localItems(kind="vise", folders=None) ... the vises, or clamps, on this computer, in
    folders, where they are kept when None: each a dict as a library's index has its items, as
    its file says of itself, with path, its file's, its id its file's name and its label the
    file's name if it says none."""
    folders = [folder(kind)] if folders is None else folders
    items = []
    seen = set()
    for where in folders:
        if not where or not os.path.isdir(where):
            continue
        for name in sorted(os.listdir(where)):
            path = os.path.join(where, name)
            if not name.lower().endswith(".fcstd") or os.path.realpath(path) in seen:
                continue
            found = about(path)
            if found.get("kind") != kind:
                continue
            seen.add(os.path.realpath(path))
            stem = os.path.splitext(name)[0]
            item = dict(found, path=path, file=name, kind=kind)
            item["libraryItem"] = item.pop("id", "")
            item["id"] = stem
            item.setdefault("label", stem.replace("_", " "))
            items.append(item)
    return items


def fileSha256(path):
    """fileSha256(path) ... the sha256 of the file at path, "" if it cannot be read."""
    try:
        return _sha256(path)
    except OSError:
        return ""


def _sameDevice(a, b):
    try:
        return os.stat(a).st_dev == os.stat(os.path.dirname(b)).st_dev
    except OSError:
        return False


def _copy(source, target):
    with open(source, "rb") as f, open(target, "wb") as g:
        g.write(f.read())
