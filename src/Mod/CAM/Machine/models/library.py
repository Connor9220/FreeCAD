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

"""Machine libraries: machine definitions (.fcm) to download one at a time.

A library is an index.json, at a web address or in a folder, listing its machines with each
file's sha256. A GitHub repository's address stands for the index.json at the top of a branch.
The libraries are those FreeCAD and addons register as content providers under SCHEMA, with a
"repository" (an address) or a "path" (a folder), and an optional "branch". A machine picked is
saved in the user's Machines folder, where the machine lists find it."""

import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request

import FreeCAD
from freecad.content_provider import ContentProviderRegistry

# the content provider schema machine libraries are registered under
SCHEMA = "freecad:cam:machine:library"
# the newest index layout this FreeCAD reads
INDEX_FORMAT = 1
# seconds to wait for a web request
TIMEOUT = 20
# the most bytes read from one address
FETCH_LIMIT = 16 * 1024 * 1024

GitHub = ("github.com", "www.github.com")
GitHubRaw = "raw.githubusercontent.com"


def libraries():
    """libraries() ... Return the registered machine libraries as (label, address, branch),
    each address once. A provider whose data gives no address as text is left out."""
    found = []
    seen = set()
    for provider in ContentProviderRegistry.find(SCHEMA):
        address = provider.data.get("repository") or provider.data.get("path")
        branch = provider.data.get("branch") or ""
        if isinstance(address, os.PathLike):
            address = os.fspath(address)
        if not isinstance(address, str) or not address.strip() or not isinstance(branch, str):
            continue
        key = indexAddress(address.strip(), branch.strip())
        if key not in seen:
            seen.add(key)
            found.append((provider.label or provider.name, address.strip(), branch.strip()))
    return found


def indexAddress(address, branch=""):
    """indexAddress(address, branch="") ... Return the address of a library's index.json: for a
    GitHub repository, the raw file at the top of branch (its default when empty); for a folder,
    the index.json in it; anything else unchanged."""
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme in ("http", "https") and parsed.netloc.lower() in GitHub:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            repo = parts[1][: -len(".git")] if parts[1].endswith(".git") else parts[1]
            return "https://%s/%s/%s/%s/index.json" % (GitHubRaw, parts[0], repo, branch or "HEAD")
    if os.path.isdir(os.path.expanduser(address)):
        return os.path.join(os.path.expanduser(address), "index.json")
    return address


def fetch(address):
    """fetch(address) ... Return the bytes at a web address or a path. Raises OSError if they
    cannot be read, ValueError for more than FETCH_LIMIT."""
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme in ("http", "https"):
        address = urllib.parse.quote(address, safe=":/?#[]@!$&'()*+,;=%~")
        request = urllib.request.Request(address, headers={"User-Agent": "FreeCAD CAM"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(FETCH_LIMIT + 1)
    else:
        if parsed.scheme == "file":
            address = urllib.request.url2pathname(parsed.path)
        with open(os.path.expanduser(address), "rb") as f:
            data = f.read(FETCH_LIMIT + 1)
    if len(data) > FETCH_LIMIT:
        raise ValueError("%s holds more than %d bytes" % (address, FETCH_LIMIT))
    return data


def _entryAddress(index, relative):
    """The address of an index entry's file, given relative to the index's address."""
    if urllib.parse.urlparse(index).scheme in ("http", "https", "file"):
        return urllib.parse.urljoin(index, urllib.parse.quote(relative))
    return os.path.join(os.path.dirname(index), relative)


def cachedIndexPath(address, branch=""):
    """cachedIndexPath(address, branch="") ... Where a library's index is kept between
    fetches, to list its machines when it cannot be fetched."""
    name = hashlib.sha1(indexAddress(address, branch).encode("utf-8")).hexdigest() + ".json"
    return os.path.join(FreeCAD.getUserCachePath(), "CAM", "MachineIndexes", name)


def _writeAtomically(path, data):
    """Write data to path in one step, so a reader never finds it half written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def loadIndex(address, branch="", online=True):
    """loadIndex(address, branch="", online=True) ... Return the machines a library lists, each
    a dict as the index has it plus url (its file's address), and when the list is from the
    copy kept earlier, that copy's time (seconds since the epoch), else None. The index is
    fetched and kept; the kept copy is used when it cannot be fetched or online is False.
    Raises ValueError for an index neither fetched nor kept, or one too new to read."""
    where = indexAddress(address, branch)
    kept = cachedIndexPath(address, branch)
    data = None
    keptAt = None
    if online:
        try:
            data = fetch(where)
            json.loads(data.decode("utf-8"))
            try:
                _writeAtomically(kept, data)
            except OSError:
                pass
        except (OSError, ValueError):
            data = None
    if data is None:
        try:
            with open(kept, "rb") as f:
                data = f.read()
            keptAt = os.path.getmtime(kept)
        except OSError:
            raise ValueError("%s could not be read" % where)
    index = json.loads(data.decode("utf-8"))
    if index.get("format", 1) > INDEX_FORMAT:
        raise ValueError("%s is a newer index than this FreeCAD reads" % where)
    items = []
    for item in index.get("items", []):
        if item.get("kind", "machine") != "machine" or not item.get("file"):
            continue
        item = dict(item)
        item["url"] = _entryAddress(where, item["file"])
        items.append(item)
    return items, keptAt


def fileSha256(path):
    """fileSha256(path) ... The sha256 of a file's bytes, or None if it cannot be read."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def localPath(item, folder):
    """localPath(item, folder) ... Where a library's machine is saved in folder."""
    return os.path.join(folder, os.path.basename(item["file"]))


def status(item, folder):
    """status(item, folder) ... How a library's machine stands in folder: "absent", "current"
    (the same file), "update" (an earlier version the library had), or "modified" (changed
    here, or another machine of that file name)."""
    here = fileSha256(localPath(item, folder))
    if here is None:
        return "absent"
    if here == item.get("sha256"):
        return "current"
    if any(here == old.get("sha256") for old in item.get("history", [])):
        return "update"
    return "modified"


def download(item, folder):
    """download(item, folder) ... Save a library's machine in folder and return its path. Raises
    ValueError if what is fetched is not the file the index lists, or not a machine
    definition."""
    data = fetch(item["url"])
    if hashlib.sha256(data).hexdigest() != item.get("sha256"):
        raise ValueError("%s is not the file the library lists" % item["url"])
    try:
        machine = json.loads(data.decode("utf-8"))["machine"]
        if not isinstance(machine, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise ValueError("%s is not a machine definition" % item["url"])
    path = localPath(item, folder)
    _writeAtomically(path, data)
    return path
