# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods to allow having the same answers in both the test and non-test API.

"""

from collections import namedtuple

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

# api.path.cleanup_dir / WORKSPACE is source root.
WORKSPACE = 'chromiumos_workspace'

_project_info = namedtuple('project_info', ['host', 'project', 'relpath'])
_manifests = {
    'internal':
        _project_info('chrome-internal.googlesource.com',
                      'chromeos/manifest-internal', 'manifest-internal'),
    'external':
        _project_info('chromium.googlesource.com', 'chromiumos/manifest',
                      'manifest')
}

default_branch = 'main'
default_ref = 'refs/heads/{}'.format(default_branch)


class ManifestProject:
  """Information about a manifest.

  Attributes:
    host (str): The gitiles host (e.g., 'chromium.googlesource.com')
    gerrit_host (str): The gerrit host.
    remote (str): The name of the git remote used by repo for this project.
    project (str): The project name.
    ref (str): The revision, typically 'refs/heads/main', may be a SHA1 hash.
    relpath (str): The location of the source tree, relative to the
      workspace_path.
    path (Path): The checked out source tree.
    url (str): The url for the project.
    as_gitiles_commit_proto (GitilesCommit): The GitilesCommit for this branch
      of the manifest.
  """

  def __init__(self, host, project, relpath, workspace_path, ref=None,
               gerrit_host=None):
    external = (host == 'chromium.googlesource.com')
    self.host = host
    self.remote = ('cros' if external else 'cros-internal')
    self.project = project
    self.relpath = relpath
    gerrit_host = gerrit_host or host.replace('.', '-review.')
    self.ref = ref or 'refs/heads/{}'.format(
        'main' if external else default_branch)
    self.gerrit_host = gerrit_host
    self.path = workspace_path / relpath
    self.url = 'https://{}/{}'.format(host, project)

  def __str__(self):
    return self.url

  def __eq__(self, other):
    """Compare for equality."""
    # There are several attributes that are redundant:
    # - host, project: url handles these.
    # - relpath: path handles this.
    return (isinstance(other, ManifestProject) and self.url == other.url and
            self.path == other.path and self.ref == other.ref and
            self.gerrit_host == other.gerrit_host)

  def __hash__(self):
    """Any class with custom __eq__ must have __hash__ to work in sets/dicts."""
    return hash('{} {} {} {}'.format(self.url, self.path, self.ref,
                                     self.gerrit_host))

  def __contains__(self, change):
    """Return whether |change| applies to this manifest.

    Args:
      change (GerritChange, PatchSet, or GitilesCommit): the object to check.

    Returns:
      (bool) whether the object is for this manifest.
    """
    change_host = change.host.replace('-review', '')
    return (change_host, change.project) == (self.host, self.project)

  @property
  def branch(self):
    """Return the branch name from the ref."""
    return (self.ref[len('refs/heads/'):]
            if self.ref.startswith('refs/heads/') else self.ref)

  @property
  def as_gitiles_commit_proto(self):
    """Return a GitilesCommit protobuf.

    Returns:
      (GitilesCommit) The gitiles commit for the manifest.  The id field is
        unspecified.
    """
    ret = GitilesCommit(host=self.host, project=self.project, ref=self.ref)
    return ret

  @classmethod
  def by_gitiles_commit(cls, commit, workspace_path):
    """Return a ManifestProject for the gitiles commit.

    Args:
      commit (GitilesCommit): The gitiles_commit to use.
      workspace_path (Path): The workspace path (api.src_state.workspace_path).

    Returns:
      (ManifestProject) information about the manifest.
    """
    external = _manifests['external']
    if commit.host == external.host and commit.project == external.project:
      info = external
    else:
      info = _manifests['internal']
    return cls(info.host, info.project, info.relpath, workspace_path)

  @classmethod
  def by_name(cls, name, workspace_path):
    """Return a ManifestProject for the named manifest.

    Args:
      name (str): 'internal', 'external', or None for the default ('internal').
      workspace_path (Path): The workspace path (api.src_state.workspace_path).

    Returns:
      (ManifestProject) information about the manifest.
    """
    name = name or 'internal'
    info = _manifests.get(name)
    if not info:
      raise KeyError('Invalid manifest name: %s' % name)
    return cls(info.host, info.project, info.relpath, workspace_path)
