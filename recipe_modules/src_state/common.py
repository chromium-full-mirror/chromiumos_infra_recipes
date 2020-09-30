# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods to allow having the same answers in both the test and non-test API.

"""

from collections import namedtuple

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

# api.path['start_dir'].join(WORKSPACE) is source root.
WORKSPACE = 'chromiumos_workspace'

_project_info = namedtuple('project_info', ['host', 'project', 'relpath'])
_manifests = dict(
    internal=_project_info('chrome-internal.googlesource.com',
                           'chromeos/manifest-internal', 'manifest-internal'),
    external=_project_info('chromium.googlesource.com', 'chromiumos/manifest',
                           'manifest'))


class ManifestProject(object):
  """Information about a manifest.

  Attributes:
    host (str): The gitiles host (e.g., 'chromium.googlesource.com')
    gerrit_host (str): The gerrit host.
    project (str): The project name.
    ref (str): The revision, typically 'refs/heads/master', may be a SHA.
    relpath (str): The location of the source tree, relative to the
      workspace_path.
    path (Path): The checked out source tree.
    url (str): The url for the project.
    as_gitiles_commit_proto (GitilesCommit): The GitilesCommit for this branch
      of the manifest.
  """

  def __init__(self, host, project, relpath, workspace_path, ref=None,
               gerrit_host=None):
    self.host = host
    self.project = project
    self.relpath = relpath
    gerrit_host = gerrit_host or host.replace('.', '-review.')
    self.ref = ref or 'refs/heads/master'
    self.gerrit_host = gerrit_host
    self.path = workspace_path.join(relpath)
    self.url = 'https://{}/{}'.format(host, project)

  def __str__(self):
    return self.url

  def __eq__(self, other):
    """Compare for equality."""
    # There are several attributes that are redundant:
    # - host, project: url handles these.
    # - relpath: path handles this.
    return (self.url == other.url and self.path == other.path and
            self.ref == other.ref and self.gerrit_host == other.gerrit_host)

  def __contains__(self, change):
    """Return whether |change| applies to this manifest.

    Args:
      change (GerritChange or PatchSet): the GerritChange or PatchSet to check.

    Returns:
      (bool) whether the change is to this manifest.
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
      (GitilesCommit) The gitiles commit for the manifest.
    """
    ret = GitilesCommit(host=self.host, project=self.project, ref=self.ref)
    return ret

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
