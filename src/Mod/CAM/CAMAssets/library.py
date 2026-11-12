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

"""Libraries of CAM assets to install one at a time: what machine and workholding libraries share.

A library is an index.json, at a web address or in a folder, listing its assets with each file's
sha256, and the sha256 of each earlier version. A hosted repository's address stands for
the index.json at the top of a branch (https://host/owner/repo/tree/branch). Libraries are
registered as content providers under a schema of their kind, each with a "repository" (an
address) or a "path" (a folder) and an optional "branch". An index is kept between fetches, so
a library can be listed when it cannot be reached."""

import hashlib
import http.client
import json
import os
import tempfile
import urllib.parse
import urllib.request

import FreeCAD
from freecad.content_provider import ContentProviderRegistry

translate = FreeCAD.Qt.translate

# seconds to wait for a web request
TIMEOUT = 20
# the most bytes read from one address
FETCH_LIMIT = 256 * 1024 * 1024
# the hosts of repository pages, and of their raw files
RepositoryHosts = ("github.com", "www.github.com")
RawHost = "raw.githubusercontent.com"


# Library addresses


def registered(schema, branches=None):
    """registered(schema, branches=None) ... Return the libraries content providers register
    under schema, as (label, address) pairs, the address on the provider's branch, each library
    once; branches maps a provider's name to the branch to use instead. A provider whose data
    gives no address as text is left out."""
    found = []
    keys = set()
    for provider in ContentProviderRegistry.find(schema):
        address = provider.data.get("repository") or provider.data.get("path")
        branch = (branches or {}).get(provider.name) or provider.data.get("branch") or ""
        if isinstance(address, os.PathLike):
            address = os.fspath(address)
        if not isinstance(address, str) or not address.strip() or not isinstance(branch, str):
            continue
        address = withBranch(address.strip(), branch.strip())
        if libraryKey(address) not in keys:
            keys.add(libraryKey(address))
            found.append((provider.label or provider.name, address))
    return found


def _repositoryParts(address, hosts=RepositoryHosts):
    """Split a hosted repository's address on one of hosts into (owner, repo, rest): the
    repository's name without .git and the path parts after it. None for any other address."""
    parsed = urllib.parse.urlparse(address)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc.lower() not in hosts or len(parts) < 2:
        return None
    repo = parts[1][: -len(".git")] if parts[1].endswith(".git") else parts[1]
    return parts[0], repo, parts[2:]


def withBranch(address, branch):
    """withBranch(address, branch) ... Return a library's address on branch: for a hosted
    repository, https://host/owner/repo/tree/branch, and the folder or file it named after
    its branch; any other address, or no branch, unchanged."""
    found = _repositoryParts(address) if branch else None
    if found is None:
        return address
    owner, repo, rest = found
    kept = rest[2:] if rest[:1] in (["tree"], ["blob"]) else []
    host = urllib.parse.urlparse(address).netloc
    return "https://%s/" % host + "/".join([owner, repo, "tree", branch] + kept)


def libraryName(address):
    """libraryName(address) ... Return a library's display name: a hosted repository's name,
    with its branch when one is given, or the name of the folder holding the index."""
    found = _repositoryParts(address)
    if found is not None:
        _, name, rest = found
        if len(rest) >= 2 and rest[0] == "tree":
            return "%s (%s)" % (name, rest[1])
        return name
    parsed = urllib.parse.urlparse(address)
    host = parsed.netloc.lower()
    parts = [p for p in parsed.path.split("/") if p]
    if host == RawHost and len(parts) >= 3:
        return parts[1] if parts[2] in ("HEAD", "main", "master") else "%s (%s)" % tuple(parts[1:3])
    path = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else address
    if parsed.scheme in ("http", "https"):
        path = parsed.path
    path = path.rstrip("/\\")
    if path.lower().endswith(".json"):
        path = os.path.dirname(path)
    return os.path.basename(path) or address


def libraryKey(address):
    """libraryKey(address) ... Return a key that is the same for two addresses of one library: a
    hosted repository's owner and name on any branch, or else its index's address."""
    found = _repositoryParts(address, RepositoryHosts + (RawHost,))
    if found is not None:
        return "repository:%s/%s" % (found[0].lower(), found[1].lower())
    return indexAddress(address)


def indexAddress(address):
    """indexAddress(address) ... Return the address of a library's index.json.

    - https://host/owner/repo: the index at the top of its default branch, as the host
      serves it raw; with /tree/branch[/folder], that branch and folder; with /blob/..., that
      file.
    - a folder: the index.json in it.
    - anything else: unchanged."""
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme in ("http", "https") and parsed.netloc.lower() in RepositoryHosts:
        found = _repositoryParts(address)
        if found is None:
            return address
        owner, repo, rest = found
        if rest[:1] in (["tree"], ["blob"]) and len(rest) >= 2:
            ref, path = rest[1], rest[2:]
        else:
            ref, path = "HEAD", []
        if not path or not path[-1].endswith(".json"):
            path = path + ["index.json"]
        return "https://%s/%s/%s/%s/%s" % (RawHost, owner, repo, ref, "/".join(path))
    # not by its scheme: a Windows path's drive letter reads as one
    if os.path.isdir(os.path.expanduser(address)):
        return os.path.join(os.path.expanduser(address), "index.json")
    return address


def entryAddress(index, relative):
    """entryAddress(index, relative) ... Return the address of an index entry's file, given
    relative to the index's address. None when an index on the web gives one off it, such as a
    file on this computer."""
    scheme = urllib.parse.urlparse(index).scheme
    if scheme == "file":
        return urllib.parse.urljoin(index, relative)
    if scheme in ("http", "https"):
        address = urllib.parse.urljoin(index, relative)
        return address if urllib.parse.urlparse(address).scheme in ("http", "https") else None
    return os.path.join(os.path.dirname(os.path.expanduser(index)), relative)


def fetch(address):
    """fetch(address) ... Return the bytes at a web address, a file:// address or a path. Raises
    OSError if they cannot be read, ValueError for more than FETCH_LIMIT."""
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme in ("http", "https"):
        # a space or other character a web address cannot hold, quoted
        address = urllib.parse.quote(address, safe=":/?#[]@!$&'()*+,;=%~")
        request = urllib.request.Request(address, headers={"User-Agent": "FreeCAD CAM"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                data = response.read(FETCH_LIMIT + 1)
        except http.client.HTTPException as e:
            raise OSError("%s: %s" % (address, e))
    else:
        if parsed.scheme == "file":
            address = urllib.request.url2pathname(parsed.path)
        with open(os.path.expanduser(address), "rb") as f:
            data = f.read(FETCH_LIMIT + 1)
    if len(data) > FETCH_LIMIT:
        raise ValueError(translate("CAM", "%s holds more than %d bytes") % (address, FETCH_LIMIT))
    return data


def writeAtomically(path, data):
    """writeAtomically(path, data) ... Write data to path in one step, so a reader never finds
    it half written. Raises OSError if it cannot be written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


# Indexes


def cachedIndexPath(address, kept):
    """cachedIndexPath(address, kept) ... Return where a library's index is kept between fetches,
    in the cache folder named kept."""
    name = hashlib.sha1(indexAddress(address).encode("utf-8")).hexdigest() + ".json"
    return os.path.join(FreeCAD.getUserCachePath(), "CAM", kept, name)


def fetchIndex(address, kept):
    """fetchIndex(address, kept) ... Fetch a library's index, keep a copy, and return its bytes.
    Raises OSError or ValueError if it cannot be fetched or is not JSON."""
    data = fetch(indexAddress(address))
    json.loads(data.decode("utf-8"))
    try:
        writeAtomically(cachedIndexPath(address, kept), data)
    except OSError:
        pass
    return data


def readIndex(address, kept, newest, online=True):
    """readIndex(address, kept, newest, online=True) ... Return a library's index, a dict with
    its items, and when it is the copy kept earlier, that copy's time (seconds since the epoch),
    else None. The index is fetched and kept; the kept copy is read when it cannot be fetched or
    online is False. Raises ValueError for an index neither fetched nor kept, one not laid out
    as an index, or one newer than format newest."""
    data = None
    keptAt = None
    failed = None
    if online:
        try:
            data = fetchIndex(address, kept)
        except (OSError, ValueError) as e:
            failed = e
    if data is None:
        path = cachedIndexPath(address, kept)
        try:
            with open(path, "rb") as f:
                data = f.read()
            keptAt = os.path.getmtime(path)
        except OSError:
            raise ValueError(
                translate("CAM", "No library at %s: %s")
                % (address, failed or translate("CAM", "not fetched yet"))
            )
    try:
        index = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise ValueError(translate("CAM", "No library at %s: %s") % (address, e))
    if (
        not isinstance(index, dict)
        or not isinstance(index.get("format", 0), int)
        or not isinstance(index.get("items", []), list)
    ):
        raise ValueError(translate("CAM", "%s is not a library's index") % address)
    if index.get("format", 0) > newest:
        raise ValueError(
            translate("CAM", "%s is a library for a newer FreeCAD (format %s)")
            % (address, index.get("format"))
        )
    return index, keptAt


def listedItems(index, address, kinds, default):
    """listedItems(index, address, kinds, default) ... Return the items of an index whose kind
    (default when none is given) is one of kinds, each a dict as the index has it plus url (its
    file's address) and index (the library's address). One without its id, file or sha256, or
    whose file is off the web for an index on the web, is left out."""
    where = indexAddress(address)
    items = []
    for item in index.get("items", []):
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and item[key] for key in ("id", "file", "sha256")
        ):
            continue
        if item.get("kind", default) not in kinds:
            continue
        url = entryAddress(where, item["file"])
        if url is None:
            continue
        items.append(dict(item, url=url, index=address))
    return items


# Local copies and their state


def fileSha256(path):
    """fileSha256(path) ... The sha256 of a file's bytes, or None if it cannot be read."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def history(item):
    """history(item) ... Return the sha256s an index item was published with before, oldest
    first. An entry is a sha256 or, in indexes that record it, {"sha256", "commit"}."""
    return [e.get("sha256") if isinstance(e, dict) else e for e in item.get("history", [])]


def state(sha, item):
    """state(sha, item) ... Compare a file of sha256 sha with an index item: "current" if it is
    the library's file now, "update" if the library published it before, "modified" if it never
    did."""
    if sha == item["sha256"]:
        return "current"
    return "update" if sha in history(item) else "modified"


def fetchChecked(item):
    """fetchChecked(item) ... Return the bytes of an index item's file. Raises OSError if they
    cannot be fetched, ValueError if they are not the file the index lists."""
    data = fetch(item["url"])
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError(translate("CAM", "%s is not the file the library lists") % item["url"])
    return data
